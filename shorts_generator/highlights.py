"""
Highlight extraction via API-only LLM (Gemini / Groq / Nvidia / GLM /
Ollama via HTTP). Local llama-cpp-python execution path was removed by
Session 13 owner decision.

Professional 3-pass architecture:
  Pass 0: Persona Detection (fast model)
  Pass 1: Topic Indexing — map the entire transcript into distinct topics
  Pass 2: Per-Topic Clip Extraction — extract clips with multi-segment stitching
"""
import json
import re
import time
import threading
import concurrent.futures
from .logger import ui_logger, get_logger

_api_lock = threading.Lock()


# ── Per-model context-aware chunking ──────────────────────────────────────────

def _lookup_context_window(llm_path: str) -> int:
    """Return the context_window (tokens) for a given llm_path from LLM_CATALOG."""
    from .config import LLM_CATALOG
    for entry in LLM_CATALOG:
        if entry["filename"] == llm_path:
            return entry.get("context_window", 6144)
    # Fallback: if llm_path starts with "api:" but no catalog entry matched,
    # assume a modern API model with a large context
    if llm_path.startswith("api:"):
        return 128000
    return 6144


def _chunk_chars_for_model(llm_path: str) -> int:
    """Return max transcript chars per chunk based on the selected model's context window.

    3 chars ≈ 1 token reserve; leave 30% for system prompt + response overhead.
    Floor 2k (minimum useful chunk), ceiling 200k (prevents context-wandering).
    """
    ctx = _lookup_context_window(llm_path)  # tokens
    chars = int(ctx * 3 * 0.70)
    return max(2000, min(chars, 200000))


def analyze_past_performance(session_logs: list) -> dict:
    """Read past LLM logs to improve future prompts"""
    insights = {
        'avg_hook_score': 0,
        'common_failures': [],
        'best_performing_patterns': []
    }
    
    for log in session_logs:
        if log.get('type') == 'llm' and log.get('reasoning'):
            # Extract patterns from reasoning
            reasoning_lower = log['reasoning'].lower()
            if 'controversy' in reasoning_lower or 'contrarian' in reasoning_lower:
                insights['best_performing_patterns'].append('controversy')
            if 'curiosity gap' in reasoning_lower or 'curiosity' in reasoning_lower:
                insights['best_performing_patterns'].append('curiosity_gap')
        
        if log.get('error'):
            insights['common_failures'].append(log['error'])
    
    return insights

def build_enhanced_prompt(prompt_text: str, session_id: str) -> str:
    logger = get_logger(session_id)
    past_logs = logger.get_entries(filter_type='llm', limit=50)
    insights = analyze_past_performance(past_logs)
    
    base = prompt_text
    
    if insights['best_performing_patterns']:
        base += f"\n\nBased on past performance, emphasize: {', '.join(set(insights['best_performing_patterns']))}"
    
    return base


_VIRALITY_BASE = """You are an expert short-form video editor.
Your job is to identify highly engaging moments in the transcript that have the natural shape of a viral clip.

A strong viral clip typically has three parts:
1. THE HOOK: An entry point that creates an open question, challenges a belief, or just starts an interesting story.
2. THE BUILD: The context, story, or logic.
3. THE PAYOFF (Reward): A satisfying conclusion, punchline, or takeaway.

EXTRACTION RULES:
- BE CLEVER WITH BOUNDARIES: Instead of ignoring a good segment because the beginning is weak, find the exact spoken sentence where the "meat" of the thought starts, and use THAT as the start timestamp. Trim out weak introductory filler (e.g. "Um, so...").
- THE FINAL REWARD: The clip MUST end on a satisfying resolution. Do not leave the viewer hanging. Hunt for the exact sentence where the thought is fully resolved, and set the end timestamp there.
- YIELD HIGH VOLUME: Extract ANY engaging moment, insightful thought, funny exchange, or interesting story. Do NOT over-filter. If it is interesting, extract it! A 2-hour podcast should yield 20+ clips easily.
- STRONGER HOOKS: Generate `hook_text` as a 10-20 word pattern interrupt that creates stakes, names subjects, and reads like a human text message — not a marketing headline. The `hook_sentence` field is the longer social-media opening line (12-18 words). Both must be highly specific to THIS clip, not generic.
- DURATION & SOFT CAP: Prefer clip durations between 15 and 60 seconds to maximize viewer completion rate and retention. Do NOT force clips to end abruptly; prioritize a complete narrative arc. The absolute upper limit is {MAX_DURATION}s (currently {MAX_DURATION}s as the configured absolute bound).

NEVER EXTRACT any of the following regardless of how interesting the
words sound:
- Podcast or show intros: segments containing phrases like "welcome to",
  "welcome back", "today on", "in today's episode", "I'm your host",
  "on this podcast", "this week we're", "joining me today"
- Outros and closings: "thank you for listening", "subscribe",
  "follow us", "see you next", "that's all for today", "until next time"
- Sponsor reads and ad breaks: "this episode is sponsored by",
  "brought to you by", "use code", "link in the bio", "check out",
  "discount", "promo code"
- Segments where the speaker is only describing what they are ABOUT TO
  say rather than actually saying it — framing and setup language is
  not a clip
- Any segment whose primary function is to introduce, frame, or close
  the content rather than deliver the core insight or story
"""

_TRIGGER_WORDS = """
CONTEXTUAL HOOK GUIDANCE (use these to sharpen hook_text):
GOOD PATTERNS (pattern-interrupt hooks that stop the scroll):
- Specified Reveal: Name the person/subject, tell what happened in simple words. 
  Example: "I made $1,400 on Etsy last month. Here is where every dollar actually went."
- Personalized Stakes: State what they did, what happened after.
  Example: "He quit his 6-figure job at 35. His wife did not speak to him for 3 days."
- Contrarian X<->Y Swap: A common thing does the opposite of what people think.
  Example: "$9 coffee stopped her paycheck anxiety. Her therapist is the one who suggested it."
- Counting Surprise: Lead with a number that sounds impossible or counterintuitive.
  Example: "She sent 400 cold emails. One reply made her $18,000."

BAD PATTERNS (these sound like SEO headlines - DO NOT USE ANY OF THESE):
- Generic benefit statements: "The Smart Way to ___", "How to Win at ___", "Unlock Your ___"
- Template curiosity sinks: "Here is why ___", "The secret to ___", "What happens next"
- Marketing jargon: multiply, revolutionize, optimize, maximize, breakthrough
- Academic labels: "The [Noun] Trap", "The [Noun] Myth" — these are YouTube TITLES, not hooks.

FEEL RULE: If it sounds like a title card from a LinkedIn slide deck, it is a bad hook.
If it sounds like a text message from a friend who just found out something insane, it is a great hook.
"""

_HOOK_TYPES = """
PSYCHOLOGICAL HOOK TYPE — you must classify each clip's hook into exactly
one of these six types and set the hook_type field accordingly:

1. "curiosity_gap" — Information asymmetry. Imply knowledge the viewer
   lacks. Template: "The hidden cost of [SPECIFIC TOPIC]" or "Why [COMMON BELIEF] is wrong about [TOPIC]"
2. "loss_aversion" — Trigger fear of losing something or missing out.
   Example hook: "Stop wasting time on X before it's too late."
3. "self_identification" — Directly address a specific identity or
   struggle so the viewer feels seen. Example hook: "If you've ever
   struggled with X, this is for you."
4. "pattern_interrupt" — A contrarian statement that breaks the viewer's
   expected narrative. Example hook: "I quit X after 10 years. Here's
   what changed."
5. "open_loop" — Create an unresolved tension that demands completion.
   Example hook: "The third point is the one that actually matters."
6. "opinion_bomb" — A controversial take, hot opinion, or statement that
   contradicts mainstream advice. Example hook: "Most people are completely wrong about X."

Choose the type that best fits the clip's actual content and tone.
Do not force a type. If the clip is primarily educational with no strong
psychological trigger, use "curiosity_gap" as default.
"""



# -- LLM Management -----------------------------------------------------------

def _parse_json_loose(raw: str):
    if not raw or not isinstance(raw, str):
        return []
    text = raw.strip()

    # 1. Strip reasoning / thinking tags (e.g. , <thought>...</thought>, <reasoning>...</reasoning>)
    text = re.sub(r"<(?:think|thought|reasoning)>[\s\S]*?</(?:think|thought|reasoning)>", "", text, flags=re.IGNORECASE).strip()

    # 2. Strip markdown code blocks anywhere in text
    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m_block:
        candidate = m_block.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            text = candidate

    # 3. Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # 4. Try finding outermost bracket/brace by testing starting points
    for start_char, end_char in [('[', ']'), ('{', '}')]:
        end_idx = text.rfind(end_char)
        if end_idx != -1:
            all_starts = [i for i, c in enumerate(text) if c == start_char and i < end_idx]
            # Try from earlier to later, and then later to earlier
            for s_i in all_starts:
                try:
                    return json.loads(text[s_i:end_idx + 1])
                except Exception:
                    continue
            for s_i in reversed(all_starts):
                try:
                    return json.loads(text[s_i:end_idx + 1])
                except Exception:
                    continue

    return []


def query_llm_json(prompt: str, llm_path: str = "nvidia/minimaxai/minimax-m3", gpu_layers: int = 0, system: str = "You are a helpful AI assistant. Output ONLY valid JSON.") -> dict:
    """Execute a single-prompt LLM query and return the parsed JSON object."""
    results = _execute_with_fallback(llm_path, system, prompt, max_tokens=1500)
    if isinstance(results, dict):
        return results
    if isinstance(results, list) and len(results) > 0 and isinstance(results[0], dict):
        return results[0]
    return {}

import threading
import random

# Thread-safe concurrency semaphores per provider.
# Prevents multiple concurrent extraction threads from hammering provider rate/concurrency limits.
_PROVIDER_SEMAPHORES = {
    "tokenrouter": threading.Semaphore(1),  # Clean sequential execution to prevent free-tier queue stalls
    "nvidia": threading.Semaphore(1),       # Strictly 1 active request to honor 40 RPM & single-concurrency slots
    "openrouter": threading.Semaphore(2),   # 2 concurrent requests
    "groq": threading.Semaphore(2),         # 2 concurrent requests
    "gemini": threading.Semaphore(2),       # 2 concurrent requests
    "glm": threading.Semaphore(2),
    "ollama": threading.Semaphore(1),
}
# Minimum interval (seconds) between calls to the same provider key
# TokenRouter: 0.2s, NVIDIA NIM: 40 RPM (1.8s), Groq: 30 RPM (1.0s), Gemini: 15 RPM (2.0s), OpenRouter: (0.5s)
_PROVIDER_SLEEP = {"tokenrouter": 0.2, "nvidia": 1.8, "groq": 1.0, "gemini": 2.0, "openrouter": 0.5}
_PROVIDER_LOCK = threading.Lock()
_PROVIDER_LAST_CALL = {}


def _parse_llm_target(llm_str: str) -> tuple:
    """Parse an LLM string into (provider_id, model_name)."""
    import os
    from .config import LLM_CATALOG
    
    if not llm_str or not isinstance(llm_str, str):
        return "tokenrouter", "qwen/qwen3.8-max-free"
    
    s = llm_str.strip()
    
    # First, check if it's explicitly in LLM_CATALOG by filename or label
    for entry in LLM_CATALOG:
        if entry["filename"] == s or entry["label"] == s:
            return entry.get("repo", "nvidia"), entry["filename"]

    if s.startswith("api:"):
        parts = s.split(":", 2)
        if len(parts) == 3:
            provider = parts[1].lower()
            model = parts[2]
            return provider, model
        elif len(parts) == 2:
            provider = parts[1].lower()
            default_models = {
                "tokenrouter": "qwen/qwen3.8-max-free",
                "nvidia": "nvidia/nemotron-3-super-120b-a12b",
                "openrouter": "meta-llama/llama-3.3-70b-instruct",
                "groq": "llama-3.3-70b-versatile",
                "gemini": "gemini-2.0-flash",
                "glm": "glm-4-flash",
                "ollama": "llama3.1",
            }
            return provider, default_models.get(provider, "qwen/qwen3.8-max-free")

    for prefix in ("tokenrouter:", "openrouter:", "groq:", "gemini:", "nvidia:", "glm:", "ollama:"):
        if s.startswith(prefix):
            return prefix[:-1], s[len(prefix):]
    
    # Auto-detect from model name patterns
    if s.startswith("qwen/qwen3.8") or "tokenrouter" in s:
        return "tokenrouter", s
    if s.startswith("meta-llama/") or s.startswith("deepseek/") or s.startswith("google/") or s.startswith("anthropic/"):
        return "openrouter", s
    if s.startswith("nvidia/") or s.startswith("meta/") or s.startswith("mistralai/") or s.startswith("deepseek-ai/") or s.startswith("minimaxai/") or s.startswith("openai/") or s.startswith("stepfun-ai/") or s.startswith("poolside/"):
        return "nvidia", s
    
    return "nvidia", s


# ── Cooperative cancellation hook ─────────────────────────────────────────
# server.main installs a callable that returns True when the user pressed Stop.
# LLM phases poll it between calls so Stop interrupts the strategy phases —
# urllib requests themselves block until the current HTTP response/timeout,
# which is the finest-grained interruption point available here.
_cancel_check = None


def set_cancel_check(fn):
    """Install (or clear with None) the server-side cancel flag reader."""
    global _cancel_check
    _cancel_check = fn


def is_cancelled() -> bool:
    return bool(_cancel_check) and bool(_cancel_check())


def _execute_with_fallback(llm, system: str, prompt: str, max_tokens: int = 4096, session_id: str = "global") -> list:
    import time
    from shorts_generator.logger import get_logger
    logger = get_logger(session_id)
    
    start_time = time.time()
    
    def log_llm_call(model_used: str, response_text: str, error: str = None):
        latency = (time.time() - start_time) * 1000
        reasoning = None
        if response_text and "<reasoning>" in response_text:
            try:
                reasoning = response_text.split("<reasoning>")[1].split("</reasoning>")[0].strip()
            except:
                pass
        logger.log_llm(
            model=model_used,
            prompt=prompt,
            response=response_text or "",
            reasoning=reasoning,
            latency_ms=latency,
            error=error
        )

    # Accept api:repo:model-id or clean model-id (repo auto-detected)
    if not isinstance(llm, str) or not llm.strip():
        ui_logger.log(f"Refusing empty/non-string LLM selection: {llm!r}")
        log_llm_call("empty-rejected", "", error=f"empty llm: {llm!r}")
        return []

    import os, time, socket, urllib.request, json

    selected_provider, model_name = _parse_llm_target(llm)
    
    def get_keys(env_var):
        val = os.getenv(env_var, "").strip()
        return [k.strip() for k in val.split(",") if k.strip()]
        
    providers_config = {
        "tokenrouter": {
            "keys": get_keys("TOKENROUTER_API_KEY"),
            "url_func": lambda model, key: "https://api.tokenrouter.com/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.3,
                # qwen3.8-max-free is a REASONING model: thinking tokens and the JSON
                # answer share ONE completion budget and this router offers no
                # enable_thinking switch. With the default effort, every extraction
                # call burned 5-15K reasoning tokens and truncated before the JSON.
                # Verified live: reasoning_effort "low" cuts reasoning to ~0.2-3K
                # tokens (fail: 14.8K reasoning / 206s -> pass: 3.2K / 41s) while
                # keeping clip quality. The 8192 floor guarantees the JSON itself
                # never gets truncated on short calls either (max != consumption).
                # Only "low"/"medium"/"xhigh" are valid here ("none" -> HTTP 400).
                "reasoning_effort": "low",
                "max_tokens": max(mx if mx else 4096, 8192),
                "max_completion_tokens": max(mx if mx else 4096, 8192),
                "response_format": {"type": "json_object"}
            },
            "extract_response": lambda res: (
                (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                or (res.get("choices", [{}])[0].get("message", {}).get("reasoning_content") or "").strip()
            ),
            "fallback_model": "qwen/qwen3.8-max-free",
            "auth_header": True,
            "extra_headers": {}
        },
        "gemini": {
            "keys": get_keys("GEMINI_API_KEY"),
            "url_func": lambda model, key: f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            "format_payload": lambda model, sys, pr, mx: {
                "contents": [{"parts": [{"text": f"System Instructions:\n{sys}\n\nUser Request:\n{pr}"}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.55, "maxOutputTokens": mx if mx else 2000}
            },
            "extract_response": lambda res: res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", ""),
            "fallback_model": "gemini-2.0-flash",
            "auth_header": False,
            "extra_headers": {}
        },
        "groq": {
            "keys": get_keys("GROQ_API_KEY"),
            "url_func": lambda model, key: "https://api.groq.com/openai/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.55,
                "max_tokens": mx if mx else 4096,
                "response_format": {"type": "json_object"}
            },
            "extract_response": lambda res: (
                (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                or (res.get("choices", [{}])[0].get("message", {}).get("reasoning_content") or "").strip()
            ),
            "fallback_model": "llama-3.3-70b-versatile",
            "auth_header": True,
            "extra_headers": {}
        },
        "openrouter": {
            "keys": get_keys("OPENROUTER_API_KEY"),
            "url_func": lambda model, key: "https://openrouter.ai/api/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.55,
                "max_tokens": mx if mx else 4096,
                "response_format": {"type": "json_object"}
            },
            "extract_response": lambda res: (
                (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                or (res.get("choices", [{}])[0].get("message", {}).get("reasoning_content") or "").strip()
            ),
            "fallback_model": "meta-llama/llama-3.3-70b-instruct",
            "auth_header": True,
            "extra_headers": {
                "HTTP-Referer": "https://clipfactory.ai",
                "X-Title": "ClipFactory AI Director"
            }
        },
        "glm": {
            "keys": get_keys("GLM_API_KEY"),
            "url_func": lambda model, key: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.55,
                "max_tokens": mx if mx else 4096
            },
            "extract_response": lambda res: res.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "fallback_model": "glm-4-flash",
            "auth_header": True,
            "extra_headers": {}
        },
        "ollama": {
            "keys": ["local"],
            "url_func": lambda model, key: "http://localhost:11434/api/generate",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "system": sys,
                "prompt": pr,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.55, "num_predict": mx if mx else 4096}
            },
            "extract_response": lambda res: res.get("response", ""),
            "fallback_model": "llama3.1",
            "auth_header": False,
            "extra_headers": {}
        },
        "nvidia": {
            "keys": get_keys("NVIDIA_API_KEY"),
            "url_func": lambda model, key: "https://integrate.api.nvidia.com/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.55,
                # Most NVIDIA NIM flagships (nemotron family) are REASONING models:
                # with thinking on they spend 5-20K tokens deliberating and often
                # truncate before emitting JSON. NIM accepts enable_thinking=false
                # (verified live: identical prompt returned clean JSON in ~6s with
                # zero reasoning tokens). Models without reasoning ignore the flag.
                "max_tokens": mx if mx else 4096,
                "chat_template_kwargs": {"enable_thinking": False}
            },
            "extract_response": lambda res: (
                (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                or (res.get("choices", [{}])[0].get("message", {}).get("reasoning_content") or "").strip()
            ),
            "fallback_model": "nvidia/nemotron-3-super-120b-a12b",
            "auth_header": True,
            "extra_headers": {}
        }
    }
    
    # Build fallback order: TokenRouter first, then NVIDIA, Gemini, Groq, GLM
    # Build fallback order: TokenRouter first, then NVIDIA, Groq, Gemini, GLM, OpenRouter
    all_known_providers = ["tokenrouter", "nvidia", "groq", "gemini", "glm", "openrouter"]
    fallback_order = [selected_provider] + [p for p in all_known_providers if p != selected_provider]

    # Warn immediately if the selected provider has no key configured
    selected_pconfig = providers_config.get(selected_provider, {})
    if not selected_pconfig.get("keys"):
        ui_logger.error(f"⚠️ No API key found for {selected_provider.upper()} — check Settings → API Keys. Trying fallback providers...")

    _warned_fallback = False

    for provider_id in fallback_order:
        if is_cancelled():
            ui_logger.log("✋ LLM call skipped — execution was stopped by the user.")
            return []
        pconfig = providers_config.get(provider_id)
        if not pconfig or not pconfig["keys"]:
            continue

        if provider_id != selected_provider and not _warned_fallback:
            ui_logger.log(f"⚠️ {selected_provider.upper()} unavailable — switching to {provider_id.upper()} as fallback")
            _warned_fallback = True

        banned_models = ("meta/llama-3.1-70b-instruct", "meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-v4-flash")
        models_to_try = [model_name] if (provider_id == selected_provider and model_name not in banned_models) else [pconfig["fallback_model"]]
        if provider_id == "tokenrouter":
            models_to_try = ["qwen/qwen3.8-max-free"]
        elif provider_id == "nvidia":
            if provider_id == selected_provider and model_name and model_name not in banned_models:
                models_to_try = [model_name]
            else:
                models_to_try = ["nvidia/nemotron-3-super-120b-a12b"]
            for fallback_m in [
                "nvidia/nemotron-3-super-120b-a12b",
                "stepfun-ai/step-3.7-flash",
                "poolside/laguna-xs-2.1",
                "openai/gpt-oss-120b"
            ]:
                if fallback_m not in models_to_try and fallback_m not in banned_models:
                    models_to_try.append(fallback_m)
        elif provider_id == "openrouter":
            for fallback_m in [
                "meta-llama/llama-3.3-70b-instruct",
                "deepseek/deepseek-chat",
                "qwen/qwen-2.5-72b-instruct"
            ]:
                if fallback_m not in models_to_try:
                    models_to_try.append(fallback_m)
        elif provider_id == "groq":
            for fallback_m in ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile"]:
                if fallback_m not in models_to_try:
                    models_to_try.append(fallback_m)
        elif provider_id == "gemini":
            for fallback_m in ["gemini-2.0-flash", "gemini-1.5-pro"]:
                if fallback_m not in models_to_try:
                    models_to_try.append(fallback_m)

        for current_model in models_to_try:
            for key_idx, key in enumerate(pconfig["keys"]):
                url = pconfig["url_func"](current_model, key)
                headers = {"Content-Type": "application/json"}
                if pconfig["auth_header"] and key != "local":
                    headers["Authorization"] = f"Bearer {key}"
                if pconfig.get("extra_headers"):
                    headers.update(pconfig["extra_headers"])

                payload = pconfig["format_payload"](current_model, system, prompt, max_tokens)
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

                max_retries = 3
                for attempt in range(max_retries):
                    sem = _PROVIDER_SEMAPHORES.get(provider_id)
                    if sem:
                        sem.acquire()
                    try:
                        min_interval = _PROVIDER_SLEEP.get(provider_id, 0)
                        if min_interval > 0:
                            with _PROVIDER_LOCK:
                                last_t = _PROVIDER_LAST_CALL.get(provider_id, 0)
                                elapsed = time.time() - last_t
                                if elapsed < min_interval:
                                    time.sleep(min_interval - elapsed)
                                _PROVIDER_LAST_CALL[provider_id] = time.time()

                        ui_logger.log(f"Querying {provider_id} API ({current_model}) with key #{key_idx + 1}...")
                        # Per-provider read timeout: NVIDIA NIM genuinely needs 150s+ for 70B+ completions
                        timeout_sec = {"tokenrouter": 90, "nvidia": 150}.get(provider_id, 120)
                        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                            res_data = json.loads(response.read().decode("utf-8"))
                            raw_text = pconfig["extract_response"](res_data).strip()
                            parsed = _parse_json_loose(raw_text)
                            log_llm_call(f"{provider_id}:{current_model}", raw_text)
                            if isinstance(parsed, list) and len(parsed) > 0:
                                return parsed
                            if isinstance(parsed, dict) and parsed:
                                res = parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
                                if res:
                                    return res
                            ui_logger.log(f"⚠️ Empty/malformed response from {provider_id}:{current_model} — trying fallback...")
                            break
                    except Exception as e:
                        _reason = getattr(e, "reason", None)
                        if isinstance(e, (socket.timeout, TimeoutError, ConnectionError)) or isinstance(_reason, (socket.timeout, TimeoutError, ConnectionError, ConnectionResetError)):
                            # Timeout = slow call on free tier / network hiccup — try the SAME model once more
                            # before giving up on it. A single timeout must not kill a topic.
                            if attempt < max_retries - 1:
                                ui_logger.log(f"⏱️ {provider_id.upper()} ({current_model}) timed out (attempt {attempt + 1}/{max_retries}) — retrying...")
                                log_llm_call(f"{provider_id}:{current_model}", "", error=str(e))
                                time.sleep(2.0 + random.uniform(0.5, 2.0))
                                continue
                            ui_logger.log(f"⏱️ {provider_id.upper()} ({current_model}) timed out after {max_retries} attempts — switching to fallback.")
                            log_llm_call(f"{provider_id}:{current_model}", "", error=str(e))
                            break
                        err_code = getattr(e, "code", 500)
                        if err_code == 404:
                            ui_logger.log(f"⚠️ Model {current_model} not found (404) on {provider_id.upper()}. Moving to next model.")
                            break
                            
                        if err_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                            backoff = (2 ** attempt * 2) + random.uniform(0.5, 2.0)
                            ui_logger.log(f"⏱️ Transient error on {provider_id.upper()} (HTTP {err_code}) — backing off {backoff:.1f}s and retrying...")
                            time.sleep(backoff)
                            continue
                        
                        if err_code == 429:
                            ui_logger.log(f"⏱️ Rate limit hit on {provider_id.upper()} (429) — moving to next model.")
                        elif err_code in (401, 403):
                            ui_logger.error(f"🔑 {provider_id.upper()} API key rejected ({err_code}) — trying next key.")
                        else:
                            ui_logger.log(f"{provider_id} API Error (key #{key_idx + 1}): HTTP {err_code}")
                        log_llm_call(f"{provider_id}:{current_model}", "", error=str(e))
                        break
                    finally:
                        if sem:
                            sem.release()

    ui_logger.error("❌ All LLM providers failed — 0 clips will be generated. Fix: add a working API key in Settings → API Keys, then retry.")
    return []


# -- Transcript Formatting ----------------------------------------------------

def _build_text(transcript_data) -> tuple:
    """Returns (text_for_llm, raw_word_list)."""
    if isinstance(transcript_data, list):
        words = transcript_data
        lines = []
        curr_group = []
        for i, w in enumerate(words):
            if curr_group:
                prev_w = curr_group[-1]
                # Secondary pause check: split when speaker pauses exceed 2.0s
                if w["start"] - prev_w["end"] > 2.0 or len(curr_group) >= 15:
                    lines.append(f"[{curr_group[0]['start']:.1f}s] {' '.join(x['word'] for x in curr_group)}")
                    curr_group = []
            curr_group.append(w)
        if curr_group:
            lines.append(f"[{curr_group[0]['start']:.1f}s] {' '.join(x['word'] for x in curr_group)}")
        return "\n".join(lines), words
    if isinstance(transcript_data, dict):
        segs = transcript_data.get("segments", [])
        return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segs), []
    if isinstance(transcript_data, tuple):
        return transcript_data[0], []
    return str(transcript_data), []


def _get_text_slice(full_text: str, start_time: float, end_time: float, llm_path: str = "") -> str:
    """Extract lines from the timestamped transcript within [start_time, end_time]."""
    lines = full_text.split('\n')
    result = []
    for line in lines:
        m = re.match(r'^\[(\d+\.?\d*)s\]', line.strip())
        if m:
            t = float(m.group(1))
            if start_time - 5 <= t <= end_time + 5:
                result.append(line)
    if result:
        return "\n".join(result)
    # Fallback: return first N chars based on model context
    limit = _chunk_chars_for_model(llm_path) if llm_path else 8000
    return full_text[:limit]

def _map_quotes_to_segments(llm_segments: list, raw_words: list, search_start_time: float = None, search_end_time: float = None) -> list:
    if not llm_segments or not raw_words:
        return []

    segments = []
    current_segment = None

    # Calculate starting search index based on search_start_time hint (if provided)
    search_idx = 0
    if search_start_time is not None:
        target_t = max(0.0, float(search_start_time) - 15.0)
        for idx, w in enumerate(raw_words):
            if w.get("start", 0) >= target_t:
                search_idx = idx
                break

    import unicodedata
    def normalize_word(w):
        if not w:
            return ""
        normalized = "".join(c for c in w if not unicodedata.category(c).startswith(('P', 'S')))
        return normalized.lower()

    raw_normalized = [normalize_word(w["word"]) for w in raw_words]

    def find_anchor(anchor_words, start_search_idx, max_search_idx=None):
        if not anchor_words:
            return -1
        anchor_len = len(anchor_words)
        end_boundary = (max_search_idx if max_search_idx is not None else len(raw_normalized)) - anchor_len + 1

        for i in range(start_search_idx, max(start_search_idx + 1, end_boundary)):
            if i + anchor_len > len(raw_normalized):
                break
            match = True
            for j in range(anchor_len):
                if raw_normalized[i+j] != anchor_words[j]:
                    match = False
                    break
            if match:
                return i

        if anchor_len > 2:
            two_boundary = (max_search_idx if max_search_idx is not None else len(raw_normalized)) - 1
            for i in range(start_search_idx, max(start_search_idx + 1, two_boundary)):
                if i + 1 >= len(raw_normalized):
                    break
                if raw_normalized[i] == anchor_words[0] and raw_normalized[i+1] == anchor_words[1]:
                    return i
        return -1

    for seg_data in llm_segments:
        start_q = seg_data.get("start_quote", "")
        end_q = seg_data.get("end_quote", "")

        start_words = [normalize_word(w) for w in start_q.split()]
        start_words = [w for w in start_words if w][:5]

        end_words = [normalize_word(w) for w in end_q.split()]
        end_words = [w for w in end_words if w][-5:]

        if not start_words:
            continue

        # Optional upper search bound if search_end_time is provided
        max_idx = None
        if search_end_time is not None:
            target_et = float(search_end_time) + 20.0
            for idx in range(search_idx, len(raw_words)):
                if raw_words[idx].get("start", 0) > target_et:
                    max_idx = idx
                    break

        start_idx = find_anchor(start_words, search_idx, max_search_idx=max_idx)
        # If not found within local window, fall back to global search
        if start_idx == -1 and search_idx > 0:
            start_idx = find_anchor(start_words, 0)
        if start_idx == -1:
            continue

        if end_words:
            end_idx = find_anchor(end_words, start_idx, max_search_idx=max_idx)
            if end_idx == -1 and max_idx is not None:
                end_idx = find_anchor(end_words, start_idx)
            if end_idx == -1:
                end_idx = start_idx + len(start_words) - 1
            else:
                end_idx = end_idx + len(end_words) - 1
        else:
            end_idx = start_idx + len(start_words) - 1

        end_idx = min(end_idx, len(raw_words) - 1)

        st = raw_words[start_idx].get("start", 0)
        et = raw_words[end_idx].get("end", raw_words[end_idx].get("start", 0) + 0.5)

        # Walk-backward sentence-boundary cuts for the start
        best_extended_st = st
        for prev_idx in range(start_idx - 1, -1, -1):
            prev_w = raw_words[prev_idx]
            prev_end = prev_w.get("end", prev_w.get("start", 0))
            if st - prev_end > 6.0:
                break

            has_punc = any(p in prev_w["word"] for p in [".", "!", "?", "।", "|"])
            pause_before = False
            if prev_idx + 1 < len(raw_words):
                next_start = raw_words[prev_idx + 1].get("start", prev_end)
                pause_before = (next_start - prev_end) > 0.4

            if has_punc or pause_before:
                best_extended_st = raw_words[prev_idx + 1]["start"]
                break

        st = best_extended_st

        # Trim filler words from the clip start: walk FORWARD from the start
        # word index, skipping short filler words (um, uh, like, you know, etc.)
        # until we hit the first substantive word (4+ chars or not in filler set).
        _FILLER_WORDS = {
            "um", "uh", "er", "ah", "eh", "oh", "hm", "mm", "hmm", "mhm", "yeah",
            "so", "like", "well", "basically", "literally", "actually", "honestly",
            "anyway", "right", "okay", "ok", "alright", "look", "listen", "hey",
            "i", "mean", "you", "know", "just", "really", "kind", "kinda", "sort",
            "sorta", "gonna", "wanna", "gotta", "let", "me", "tell", "us", "get",
            "they", "we",  "say", "said", "thing", "things", "stuff",
        }
        for fwd in range(start_idx, min(start_idx + 15, len(raw_words))):
            fw_text = raw_words[fwd].get("word", "").strip().lower()
            # Guard: don't advance past 3 seconds (sentence-start in fast speech)
            if raw_words[fwd].get("start", 0) - st > 3.0:
                break
            # If this word is NOT a filler, set st to its start and stop
            if len(fw_text) >= 4 or fw_text not in _FILLER_WORDS:
                st = raw_words[fwd].get("start", st)
                break
            # If skipped a filler word, advance st to this filler's end
            st = raw_words[fwd].get("end", st)

        # Walk-forward sentence-boundary cuts for the end
        best_extended_et = et
        found_clean_end = False
        
        # Check if the current end word already has sentence-ending punctuation
        current_end_w = raw_words[end_idx]
        if any(p in current_end_w["word"] for p in [".", "!", "?", "।", "|"]):
            found_clean_end = True

        if not found_clean_end:
            for next_idx in range(end_idx + 1, min(end_idx + 50, len(raw_words))):
                next_w = raw_words[next_idx]
                next_start = next_w.get("start", best_extended_et)
                if next_start - best_extended_et > 10.0:
                    break
                best_extended_et = next_w.get("end", next_start)
                has_punc = any(p in next_w["word"] for p in [".", "!", "?", "।", "|"])
                pause_after = False
                if next_idx + 1 < len(raw_words):
                    next_next_start = raw_words[next_idx + 1].get("start", next_w.get("end", next_start))
                    pause_after = (next_next_start - next_w.get("end", next_start)) > 0.4
                if has_punc or pause_after:
                    found_clean_end = True
                    break
            et = best_extended_et

        # If still no clean end found, walk backward from original end_idx to
        # find the nearest previous sentence punctuation. Better to clip early
        # at a clean sentence than mid-thought.
        if not found_clean_end:
            for prev in range(end_idx, -1, -1):
                pw = raw_words[prev].get("word", "")
                if any(p in pw for p in [".", "!", "?", "।", "|"]):
                    et = raw_words[prev].get("end", et)
                    found_clean_end = True
                    break

        search_idx = end_idx + 1

        if current_segment is None:
            current_segment = {"start_time": st, "end_time": et, "incomplete_endpoint": not found_clean_end}
        else:
            gap = st - current_segment["end_time"]
            if gap < 1.5:
                current_segment["end_time"] = max(current_segment["end_time"], et)
                current_segment["incomplete_endpoint"] = not found_clean_end
            else:
                segments.append(current_segment)
                current_segment = {"start_time": st, "end_time": et, "incomplete_endpoint": not found_clean_end}

    if current_segment:
        segments.append(current_segment)

    return _snap_timestamps_to_sentence_boundaries(segments, raw_words)


def _snap_timestamps_to_sentence_boundaries(segments: list, raw_words: list) -> list:
    """
    Snap segment start and end timestamps to the nearest sentence boundary
    (capitalization or punctuation . ! ? । |) in raw_words.
    """
    if not segments or not raw_words:
        return segments

    snapped_segments = []
    for seg in segments:
        st = seg.get("start_time", 0)
        et = seg.get("end_time", 0)

        # Find word index for start
        st_idx = 0
        for i, w in enumerate(raw_words):
            if w.get("start", 0) >= st:
                st_idx = i
                break

        # Search backward up to 8 words for sentence start (punctuation on preceding word)
        new_st_idx = st_idx
        for i in range(st_idx - 1, max(-1, st_idx - 9), -1):
            w_prev = raw_words[i]
            prev_end = w_prev.get("end", w_prev.get("start", 0))
            if st - prev_end > 5.0:
                break
            if any(p in w_prev.get("word", "") for p in [".", "!", "?", "।", "|"]):
                new_st_idx = i + 1
                break

        # Find word index for end
        et_idx = len(raw_words) - 1
        for i in range(len(raw_words) - 1, -1, -1):
            if raw_words[i].get("end", 0) <= et:
                et_idx = i
                break

        # Search forward up to 25 words for sentence end punctuation.
        # If none, fall back to the nearest previous sentence punctuation.
        new_et_idx = et_idx
        for i in range(et_idx, min(len(raw_words), et_idx + 25)):
            w_cur = raw_words[i]
            cur_start = w_cur.get("start", et)
            if cur_start - et > 8.0:
                break
            word = w_cur.get("word", "")
            if any(p in word for p in [".", "!", "?", "।", "|"]):
                new_et_idx = i
                break
        else:
            for i in range(et_idx, max(-1, et_idx - 25), -1):
                w_cur = raw_words[i]
                word = w_cur.get("word", "")
                if any(p in word for p in [".", "!", "?", "।", "|"]):
                    new_et_idx = i
                    break

        final_st = float(raw_words[min(new_st_idx, len(raw_words)-1)].get("start", st))
        final_et = float(raw_words[min(new_et_idx, len(raw_words)-1)].get("end", et))
        if final_et > final_st:
            snapped_segments.append({
                "start_time": final_st,
                "end_time": final_et,
                "incomplete_endpoint": seg.get("incomplete_endpoint", False)
            })
        else:
            snapped_segments.append(seg)
    return snapped_segments


def _map_text_to_stitched_segments(ideal_transcript: str, raw_words: list) -> list:
    """Bridge between ideal_transcript (free text) and _map_quotes_to_segments.

    The LLM returns ideal_transcript as a block of text. This function
    extracts the first and last words to build synthetic start_quote/end_quote
    pairs, then delegates to the existing anchor-based mapper.
    """
    if not ideal_transcript or not raw_words:
        return []

    words = ideal_transcript.split()
    if len(words) < 2:
        return []

    # Build a single segment request from the full ideal_transcript
    synth_segments = [{
        "start_quote": " ".join(words[:5]),
        "end_quote": " ".join(words[-5:])
    }]

    return _map_quotes_to_segments(synth_segments, raw_words)


def _get_video_duration(word_timestamps: list) -> float:
    """Get total video duration in seconds from word timestamps."""


# Soft-cap absolute bound. 15-60s is the LLM-preferred sweet spot;
# the bound is a hard ceiling so a runaway LLM can't produce a multi-minute clip.
# Owner decision 2026-07-12 (session 11): rejected the panic-driven 45s cap.
DEFAULT_MAX_DURATION = 90   # seconds, 15 ≤ x ≤ DEFAULT_MAX_DURATION

def _get_video_duration(word_timestamps: list) -> float:
    """Get total video duration in seconds from word timestamps."""
    if not word_timestamps:
        return 0.0
    return word_timestamps[-1].get("end", 0) - word_timestamps[0].get("start", 0)


def _format_duration(seconds: float) -> str:
    """Format seconds as 'Xm Ys' or 'Xh Ym'."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m {s}s"
    h = m // 60
    m = m % 60
    return f"{h}h {m}m"


# -- Estimated Clip Density ---------------------------------------------------

# Quality-budget ceiling: clip count scales with duration (1 per 4 min) so
# short videos aren't diluted and long videos aren't starved of coverage,
# but a runaway multi-hour upload can't produce an unbounded render queue.
MAX_CLIP_CEILING = 60

def estimate_clip_potential(word_timestamps: list) -> int:
    """Estimate how many clips a video could produce based on its duration."""
    if not word_timestamps:
        return 6
    duration_secs = _get_video_duration(word_timestamps)
    duration_mins = duration_secs / 60.0
    # Rule of thumb (owner decision 2026-08-17): ~1 clip per 2 minutes, floor 6,
    # ceiling MAX_CLIP_CEILING. The old 1-per-4-min formula capped an 18-min video
    # at exactly 5 while extraction actually found 18 viable candidates — verified
    # in a real run the same day. Strategies are free previews (owner picks which
    # to render), so a denser budget costs only a few extra LLM seconds per video.
    return max(6, min(MAX_CLIP_CEILING, int(duration_mins / 2)))


# ── Post-LLM Validation ─────────────────────────────────────────────────────

# Phrases that indicate the LLM copied schema instructions instead of generating content
_HOOK_TEXT_POISON_PHRASES = [
    "exact first", "bold, original", "prompt instructions", "curiosity gap. not a summary",
    "do not copy", "do not use generic", "specific payload", "declarative statement",
    "scroll-stopping", "3-5 words of the segment",
]

# Words/phrases that make hooks feel generic clickbait — small models ignore the prompt ban,
# so we enforce it in code as a post-generation filter.
_HOOK_FORBIDDEN_PATTERN = re.compile(
    r"\b(here.s why|the secret to|what happens next|nobody tells you|"
    r"you won.t believe|mind[ -]?blowing|game[ -]?changer|"
    r"the hidden|the dark (secret|truth)|"
    r"(shocking|unexpected|nobody knows).{0,20}(what|who|how)|"
    r"multiply your|unlock the|revolutionize your)\b",
    re.IGNORECASE,
)


def _sanitize_hook_text(raw_hook_text: str, fallback_hook_sentence: str) -> str:
    """Return clean hook_text.

    Falls back to hook_sentence when the LLM leaked schema instructions or
    used generic clickbait words that the prompt bans but small models ignore.
    """
    text = (raw_hook_text or "").strip()

    if not text:
        return fallback_hook_sentence

    text_lower = text.lower()

    # Detect prompt instruction leakage
    if any(phrase in text_lower for phrase in _HOOK_TEXT_POISON_PHRASES):
        return fallback_hook_sentence

    # Detect forbidden clickbait words — try hook_sentence first, then strip the offending word
    if _HOOK_FORBIDDEN_PATTERN.search(text):
        fallback = (fallback_hook_sentence or "").strip()
        if fallback and not _HOOK_FORBIDDEN_PATTERN.search(fallback):
            return fallback
        # Both are contaminated — strip the forbidden word(s) from the shorter text
        cleaned = _HOOK_FORBIDDEN_PATTERN.sub("", text).strip(" .,!?-")
        return cleaned if len(cleaned) > 4 else text  # keep original if stripping made it empty

    return text


_INTRO_OUTRO_PHRASES = re.compile(
    r"\b(welcome to|welcome back|today on|in today'?s episode|i'?m your host|"
    r"on this podcast|this week we'?re|joining me today|thank you for (listening|watching)|"
    r"don'?t forget to subscribe|hit the subscribe|follow us|see you next|"
    r"that'?s all for today|until next time|this episode is sponsored|"
    r"brought to you by|use code |link in (the |my )?bio|check out our|"
    r"promo code|discount code)\b",
    re.IGNORECASE,
)

_SELF_REFERENTIAL_FILTER = re.compile(
    r"\b(we'?ve got (a lot of videos|more) on that|subscribe to my channel|"
    r"in this video|in my channel|link in the description|go watch my|in the next video|"
    r"in my last video)\b",
    re.IGNORECASE
)

_SELF_REFERENTIAL_FLAG = re.compile(
    r"\b(as I mentioned|like I said before|mentioned earlier|as we discussed earlier|"
    r"like I mentioned|like we said|as said before)\b",
    re.IGNORECASE
)

def _validate_clips(clips: list, raw_words: list, max_duration: int = DEFAULT_MAX_DURATION) -> list:
    valid = []
    for clip in clips:
        segments = clip.get("segments", [])
        if not segments:
            continue

        total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)

        # Smart expansion if duration is slightly under minimum (8-14s)
        if total_dur < 15 and raw_words and segments and total_dur >= 8.0:
            first_st = segments[0]["start_time"]
            last_et = segments[-1]["end_time"]
            st_idx = 0
            et_idx = len(raw_words) - 1
            for idx, w in enumerate(raw_words):
                if w.get("start", 0) >= first_st:
                    st_idx = idx
                    break
            for idx in range(st_idx, len(raw_words)):
                if raw_words[idx].get("end", 0) >= last_et:
                    et_idx = idx
                    break
            
            while (raw_words[et_idx]["end"] - raw_words[st_idx]["start"] < 16.0):
                expanded = False
                if et_idx + 1 < len(raw_words):
                    et_idx += 1
                    expanded = True
                if st_idx > 0 and (raw_words[et_idx]["end"] - raw_words[st_idx]["start"] < 16.0):
                    st_idx -= 1
                    expanded = True
                if not expanded:
                    break
            
            segments[0]["start_time"] = raw_words[st_idx]["start"]
            segments[-1]["end_time"] = raw_words[et_idx]["end"]
            total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)
            ui_logger.log(f"  Smart duration expansion for '{clip.get('title', '?')}': expanded to {total_dur:.1f}s")

        if total_dur < 15 or total_dur > max_duration:
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': duration {total_dur:.0f}s out of bounds (limit 15-{max_duration}s)")
            continue

        # Content-based intro/outro/sponsor guard (defense-in-depth; prompt rule alone isn't enough)
        check_text = f"{clip.get('title', '')} {clip.get('ideal_transcript', '')[:200]}"
        if _INTRO_OUTRO_PHRASES.search(check_text):
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': matches intro/outro/sponsor phrase")
            continue

        clip["duration"] = total_dur
        clip["is_stitched"] = len(segments) > 1
        valid.append(clip)

    return valid

def _get_effective_llm_path(llm_path: str, pass_type: str) -> str:
    """
    Autonomous Multi-Layer Model Orchestrator.
    If generic NVIDIA or OpenRouter API is selected or in autonomous mode,
    dynamically route each pipeline pass to its specialized model.
    If the user explicitly selected a specific model (e.g. Gemini, Groq, OpenRouter, or a specific NVIDIA model),
    preserve user choice.
    """
    import os
    if not llm_path:
        return llm_path
    s = llm_path.strip()

    # Check if TokenRouter is available (highest priority ultra-fast flagship)
    has_tokenrouter = bool(os.getenv("TOKENROUTER_API_KEY", "").strip())
    has_nvidia = bool(os.getenv("NVIDIA_API_KEY", "").strip())
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())

    # If generic auto or default is requested
    if s in ("default", "auto", "tokenrouter-auto", "tokenrouter", "api:tokenrouter", "api:tokenrouter:"):
        if has_tokenrouter:
            ui_logger.log(f"🤖 Autonomous Orchestrator [{pass_type.upper()}]: Routing to TokenRouter Qwen 3.8 Max")
            return "api:tokenrouter:qwen/qwen3.8-max-free"
        elif has_nvidia:
            return "api:nvidia:nvidia/nemotron-3-super-120b-a12b"
        elif has_groq:
            return "api:groq:llama-3.3-70b-versatile"
        elif has_gemini:
            return "api:gemini:gemini-2.0-flash"

    # Check if generic nvidia routing is requested
    is_generic_nvidia = (
        s in ("nvidia", "api:nvidia", "api:nvidia:", "nvidia-auto")
    )
    
    if is_generic_nvidia:
        target = "nvidia/nemotron-3-super-120b-a12b"
        routed = f"api:nvidia:{target}"
        ui_logger.log(f"🤖 Autonomous NVIDIA Orchestrator [{pass_type.upper()}]: Routing to {target}")
        return routed

    # If the user selected an explicit model or provider, preserve it
    return llm_path

# ── Pass 0: Persona Detection ───────────────────────────────────────────────
def detect_video_persona(transcript_data, llm_path: str, gpu_layers: int = 35, session_id: str = "global") -> dict:
    """Run a fast pass to detect video genre, tone, target audience, and suggested styles."""
    if not llm_path:
        return {}
        
    text, _ = _build_text(transcript_data)
    llm = _get_effective_llm_path(llm_path, "persona")
    
    system = "You are an expert video analyst. Output ONLY raw JSON. No markdown."
    prompt = (
        "Analyze the following video transcript chunk and determine its core persona.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "genre": "Podcast|Tutorial|Vlog|Rant|Interview|Comedy|Educational",\n'
        '  "tone": "Casual|Professional|High-Energy|Calm|Controversial",\n'
        '  "target_audience": "Brief description of who this is for",\n'
        '  "suggested_brand_kit": "Hormozi|Ali Abdaal|MrBeast|Standard",\n'
        '  "suggested_bgm": "Lofi / Chill|High Energy / Phonk|Suspense / Dark|Corporate / Upbeat"\n'
        "}\n\n"
        f"Transcript (first 5000 chars):\n{text[:5000]}"
    )
    
    try:
        results = _execute_with_fallback(llm, system, prompt, session_id=session_id)
        if isinstance(results, list) and len(results) > 0:
            return results[0]
        if isinstance(results, dict):
            return results
    except Exception as e:
        ui_logger.log(f"Persona detection failed: {e}")
        
    return {
        "genre": "General", 
        "tone": "Neutral", 
        "target_audience": "Broad",
        "suggested_brand_kit": "Standard",
        "suggested_bgm": "Lofi / Chill"
    }


# -- Pass 1: Topic Indexing ---------------------------------------------------

def get_topic_index(transcript_data, llm_path: str, gpu_layers: int = 35, language: str = "", session_id: str = "global") -> list:
    """
    First pass: Map the entire transcript into distinct discussion topics.
    Returns a list of topics with their timestamp ranges.
    """
    text, _ = _build_text(transcript_data)
    if not llm_path:
        raise RuntimeError("llm_path is required.")

    llm = _get_effective_llm_path(llm_path, "topic_index")
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are a content analyst. Your job is to identify distinct discussion topics in a video transcript."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown."
    )

    topic_schema = (
        '{\n'
        '  "topics": [\n'
        '    {\n'
        '      "topic": "Short descriptive title of the discussion topic (5-10 words)",\n'
        '      "start_time": 0.0,\n'
        '      "end_time": 180.0,\n'
        '      "summary": "1-sentence summary of what is discussed"\n'
        '    }\n'
        '  ]\n'
        '}'
    )

    # Process transcript in large chunks to identify topics across the full video
    
    # Smart Sliding Window Chunking — cap to 8000 chars (~5-7 mins of content)
    # so long videos (1-2h+) generate 15-25 granular topic blocks instead of 3-5 macro blocks
    chunk_chars = min(_chunk_chars_for_model(llm_path), 8000)
    # Overlap by 1000 characters to prevent splitting context/stories across boundaries
    overlap = 1000
    step = max(500, chunk_chars - overlap)
    chunks = []
    
    # Split by lines to ensure we don't cut words or timestamps in half
    lines = text.split('\n')
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) > chunk_chars and len(current_chunk) > overlap:
            chunks.append(current_chunk)
            # Find a clean newline boundary near -overlap so we don't cut in the middle of a line
            overlap_text = current_chunk[-overlap:]
            first_nl = overlap_text.find('\n')
            if first_nl != -1:
                overlap_text = overlap_text[first_nl + 1:]
            current_chunk = overlap_text + '\n' + line
        else:
            current_chunk += line + '\n'
    if current_chunk:
        chunks.append(current_chunk)

    all_topics = []

    def process_topic_chunk(idx, chunk):
        ui_logger.log(f"Topic indexing chunk {idx + 1}/{len(chunks)}...")
        prompt = (
            "Analyze this transcript section and identify distinct moments.\n\n"
            "You are hunting for MOMENTS, not topics. A moment is a short passage\n"
            "where something genuinely interesting happens. Ignore filler, logistics,\n"
            "introductions, and transitions entirely.\n\n"
            "Hunt specifically for these moment types, in priority order:\n\n"
            "1. REVELATION (HIGHEST PRIORITY) — The speaker says something surprising, counterintuitive,\n"
            "   or that directly contradicts mainstream advice, industry consensus, or popular belief.\n"
            "   This is the highest priority moment type. Signal phrases: \"most\n"
            "   people think\", \"what nobody tells you\", \"the truth is\", \"I found out\".\n\n"
            "2. TENSION OR DISAGREEMENT — The speaker pushes back on an idea, admits\n"
            "   a mistake, or challenges the audience. Signal phrases: \"but here's the\n"
            "   problem\", \"I was wrong about\", \"this is where people get it wrong\".\n\n"
            "3. SPECIFIC NUMBERS OR PROOF — The speaker cites a concrete number,\n"
            "   statistic, personal result, or named example. Signal: any dollar\n"
            "   amount, percentage, timeframe, or named person/company as evidence.\n\n"
            "4. STRONG PERSONAL OPINION (OPINION BOMB) — The speaker makes a controversial declarative claim\n"
            "   they clearly believe strongly. Signal phrases: \"I genuinely believe\",\n"
            "   \"most people will never\", \"the reason X fails is\", \"nobody wants to\n"
            "   hear this but\".\n\n"
            "5. STORY WITH STAKES — A personal anecdote or scenario where something\n"
            "   is at risk (money, reputation, relationship, health). Must have a\n"
            "   clear beginning setup and an implied outcome.\n\n"
            "SKIP any passage that is:\n"
            "- Explaining who the guest or host is\n"
            "- Discussing the show, episode, or sponsor\n"
            "- Transitioning between subjects with no clear point\n"
            "- Generic advice with no specific example or proof\n"
            "- A question without an answer in the same passage\n\n"
            "Rules:\n"
            "- Each topic must have accurate start_time and end_time from the transcript timestamps\n"
            "- Topics should NOT overlap\n"
            "- Include ALL sections — do not skip any part of the transcript\n"
            "- A 3-minute section typically has 1-3 topics\n"
            "- Identify at least 2 distinct topics for this section if possible to ensure we don't group everything together\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON object containing a 'topics' array:\n{topic_schema}"
        )
        try:
            results = _execute_with_fallback(llm, system, prompt, max_tokens=2000, session_id=session_id)
            if isinstance(results, list) and len(results) > 0:
                return results
            if isinstance(results, dict) and results:
                topics_list = results.get("topics", results.get("moments", [results]))
                if isinstance(topics_list, list) and len(topics_list) > 0:
                    return topics_list
        except Exception as e:
            ui_logger.log(f"Warning: Topic indexing chunk {idx + 1} failed — {e}")

        # Fallback for this chunk so no section of the video is lost:
        ts_matches = [float(m) for m in re.findall(r"\[([0-9.]+)s\]", chunk)]
        if ts_matches:
            c_start = ts_matches[0]
            c_end = ts_matches[-1]
            if c_end - c_start >= 15:
                mid = (c_start + c_end) / 2
                return [
                    {"topic": f"Key Discussion Segment {idx + 1}A", "start_time": c_start, "end_time": mid, "summary": "Discussion moment."},
                    {"topic": f"Key Discussion Segment {idx + 1}B", "start_time": mid, "end_time": c_end, "summary": "Discussion moment."}
                ]
            elif c_end > c_start:
                return [{"topic": f"Key Discussion Segment {idx + 1}", "start_time": c_start, "end_time": c_end, "summary": "Discussion moment."}]
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_topic_chunk, idx, chunk): idx for idx, chunk in enumerate(chunks)}
        for future in concurrent.futures.as_completed(futures):
            all_topics.extend(future.result())

    # Validate topics and pad windows. Clips must be 15-90s; a 30s topic window
    # cannot reliably yield such a clip, so pad every topic to >= 45s.
    MIN_TOPIC_WINDOW = 45.0
    valid_topics = []
    for t in all_topics:
        if not isinstance(t, dict):
            continue
        try:
            st = float(t.get("start_time", 0))
            et = float(t.get("end_time", 0))
            if et > st:
                st_adj = max(0.0, st)
                et_adj = et
                if et_adj - st_adj < MIN_TOPIC_WINDOW:
                    mid = (st_adj + et_adj) / 2
                    st_adj = max(0.0, mid - MIN_TOPIC_WINDOW / 2)
                    et_adj = mid + MIN_TOPIC_WINDOW / 2
                valid_topics.append({
                    "topic": t.get("topic", "Untitled Topic"),
                    "start_time": st_adj,
                    "end_time": et_adj,
                    "summary": t.get("summary", ""),
                })
        except Exception:
            continue

    # Sort by start time
    valid_topics.sort(key=lambda x: x["start_time"])

    # Merge near-adjacent micro-topics (<20s gap, combined span <=120s) into one
    # analysis window so each extraction call gets enough material to work with.
    # Overlapping windows are fine — dedup handles any duplicate clips downstream.
    merged = []
    for t in valid_topics:
        if merged:
            prev = merged[-1]
            gap = t["start_time"] - prev["end_time"]
            combined_span = t["end_time"] - prev["start_time"]
            if gap < 20.0 and combined_span <= 120.0:
                prev["end_time"] = max(prev["end_time"], t["end_time"])
                if prev["topic"] != t["topic"]:
                    prev["topic"] = f"{prev['topic']} / {t['topic']}"
                continue
        merged.append(dict(t))
    valid_topics = merged
    
    ui_logger.log(f"Identified {len(valid_topics)} discussion topics across the video.")
    return valid_topics


# ——— Pass 2: Per-Topic Clip Extraction ————————————————————————————————————————————

# 5 one-shot viral hook examples labeled by persona type (L1)
_VIRAL_HOOKS_EXAMPLES = """
VIRAL HOOK ONE-SHOT EXAMPLES BY PERSONA TYPE:
- DEBATE: Name the person and the clash directly. Example: "[Name] said taxes are theft. The host's 8-word response killed him."
- INTERVIEW: Pull the specific emotional bomb. Example: "She invested her life savings at 63. The bank called her 2 days later."
- MONOLOGUE: State the transformation bluntly with stakes. Example: "I tracked every dollar for 90 days. By day 17, I wanted to quit my job."
"""

_DEBATE_PROMPT_ADDITION = """
PERSONA STYLE: DEBATE
Focus intensely on conflict, contrarian opinions, rapid-fire back-and-forth arguments, high-tension disagreements, and bold rebuttals.
Make sure the hook highlights the intellectual clash or the contrarian take.
"""

_INTERVIEW_PROMPT_ADDITION = """
PERSONA STYLE: INTERVIEW
Focus on deep emotional revelations, shocking answers, high-value expert secrets, dramatic pauses, or mind-blowing question-and-answer exchanges.
Make sure the hook highlights the host's framing or the guest's sudden realization/opinion bomb.
"""

_MONOLOGUE_PROMPT_ADDITION = """
PERSONA STYLE: MONOLOGUE
Focus on direct-to-camera storytelling, step-by-step advice, personal breakthrough realizations, clear educational insights, and actionable tips.
Make sure the hook builds intense curiosity or promises a specific transformation.
"""

def get_highlights(
    transcript_data,
    num_clips: int = 5,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_clips: int = 30,
    language: str = "",
    angle: str = "multi-angle",
    topics: list = None,
    energy_peaks: list = None,
    scene_peaks: list = None,
    persona: dict = None,
    session_id: str = "global",
    campaign_brief: str = None,
    allow_natural_recomposition: bool = False,
    max_duration: int = DEFAULT_MAX_DURATION,
) -> dict:
    """
    Extract viral clips from the transcript using multi-segment stitching.
    If topics are provided (from Pass 1), extract clips per-topic for comprehensive coverage.
    """
    text, raw_words = _build_text(transcript_data)
    logger = get_logger(session_id)
    logger.log_app_event('extraction', 'started', {
        'transcript_length': len(text) if text else 0,
        'model_preference': llm_path,
        'requested_clips': num_clips,
        'angle': angle
    })

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_effective_llm_path(llm_path, "highlights")
    
    # Calculate video duration for the prompt
    video_dur = _get_video_duration(raw_words) if raw_words else 0
    video_duration_str = _format_duration(video_dur) if video_dur > 0 else "Unknown"
    
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are an elite AI director for TikTok, Instagram Reels, and YouTube Shorts."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown, no explanation whatsoever."
    )

    # New schema focused on semantic text extraction (strict Title formatting L2)
    schema = (
        '{\n'
        '  "clips": [\n'
        '    {\n'
        '      "title": "SHORT TOPIC TAG (4-7 words). A punchy ALL-CAPS banner label for the clip — readable as a fast scan, NOT a full sentence (e.g. \\"THE MONEY TRAP\\", \\"FIRST JOB MISTAKES\\", \\"WHY YOUR SAVINGS PLAN IS BROKEN\\"). Keep it tight; the viewer hook lives in hook_text.",\n'
        '      "virality_score": 85,\n'
        '      "start_timestamp": 12.4,\n'
        '      "end_timestamp": 54.1,\n'
        '      "segments": [\n'
        '        {\n'
        '          "start_quote": "The exact first 3-5 spoken words of this segment, copied verbatim from the transcript. No timestamps.",\n'
        '          "end_quote": "The exact last 3-5 spoken words of this segment, copied verbatim from the transcript. No timestamps."\n'
        '        }\n'
        '      ],\n'
        '      "virality_reason": "1-2 sentences explaining WHY this clip would go viral — what psychological trigger or content quality makes it shareable.",\n'
        '      "source_topic": "The topic name this clip was extracted from.",\n'
        '      "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '      "music_query": "A 3-4 word search term for no-copyright background music (e.g., upbeat phonk, calm lofi, dark suspense)",\n'
        '      "broll_keywords": ["2-3 concrete visual nouns that match the clip content, e.g., money, laptop, crowd"],\n'
        '      "emoji_moments": ["🔥"],\n'
        '      "hook_text": "Write a SPECIFIC punchy hook (10-20 words) that creates a pattern interrupt — something that makes a stranger stop mid-scroll because it is surprising, emotionally charged, or challenges something they believe. Rules: (1) BE SPECIFIC — name the person, subject, or situation being called out. (2) CREATE STAKES — what happens right after this moment? (3) USE AT LEAST ONE OF: a concrete number or stat, a direct contrarian claim (X actually does the opposite of Y), or a raw emotional revelation. Do NOT summarize the clip. Do NOT use any of these banned phrases: here is why, the secret to, what happens next will shock you, you will not believe, nobody tells you, game changer, mind blowing. Write how a human would text a friend — not like a marketing headline or SEO title. Must be highly original and specific to this exact clip.",\n'
        '      "hook_sentence": "A REWRITTEN scroll-stopping opening line (12-18 words) authored for social media — NOT copied from the transcript. Write an original hook tailored to the specific content of the clip. DO NOT copy the template examples from the prompt. Must be highly specific, punchy, and original. Max 18 words.",\n'
        '      "hook_type": "one of exactly: \\"curiosity_gap\\" | \\"loss_aversion\\" | \\"self_identification\\" | \\"pattern_interrupt\\" | \\"open_loop\\" | \\"opinion_bomb\\""\n'
        '    }\n'
        '  ]\n'
        '}'
    )

    all_highlights = []

    # Fork prompts dynamically based on whether detected persona is a Debate, Interview, or Monologue (L3)
    persona_genre = (persona or {}).get("genre", "Monologue")
    persona_addition = _MONOLOGUE_PROMPT_ADDITION
    if any(k in persona_genre for k in ["Debate", "Rant", "Controversial"]):
        persona_addition = _DEBATE_PROMPT_ADDITION
    elif any(k in persona_genre for k in ["Interview", "Podcast"]):
        persona_addition = _INTERVIEW_PROMPT_ADDITION

    # Build the virality prompt with dynamic video duration, structured hook examples, and persona additions.
    # Soft-cap absolute bound is substituted from runtime parameter (owner-locked soft cap session 2026-07-12).
    _virality_base_dynamic = _VIRALITY_BASE.replace("{MAX_DURATION}", str(max_duration))
    virality_prompt = f"{_virality_base_dynamic}\n\n{_VIRAL_HOOKS_EXAMPLES}\n\n{persona_addition}"
    virality_prompt += f"\n\nThe source video is approximately {video_duration_str} long."
    virality_prompt += f"\n\n{_TRIGGER_WORDS}\n\n{_HOOK_TYPES}"

    angle_instructions = ""
    if angle == "contrarian":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: CONTRARIAN / HOT TAKES. Focus strictly on controversial claims, unpopular opinions, and contrarian perspectives.\n"
            "Prioritize segments where the speaker goes against mainstream thought, challenges beliefs, or exposes industry myths."
        )
    elif angle == "educational":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: ACTIONABLE SECRETS. Focus strictly on actionable advice, tutorials, step-by-step methods, and educational secrets.\n"
            "Prioritize segments where the speaker clearly teaches the viewer how to solve a specific problem or explains a clear concept."
        )
    elif angle == "story":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: EMOTIONAL STORIES. Focus strictly on narrative-driven passages, personal anecdotes, struggles, failures, and triumphs.\n"
            "Prioritize clips that tell a cohesive personal story with clear emotional resonance."
        )
    elif angle == "multi-angle":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: MULTI-ANGLE MIX. Extract a diverse mix of highlights across different angles: some contrarian hot takes, some educational secrets, and some personal stories, ensuring a wide variety of content."
        )
    virality_prompt += angle_instructions

    if campaign_brief and campaign_brief.strip():
        virality_prompt += f"\n\nCAMPAIGN BRIEF — HIGHEST PRIORITY INSTRUCTIONS:\n{campaign_brief.strip()}\nApply these instructions above all other defaults. Only extract clips that fit this brief."

    if allow_natural_recomposition:
        virality_prompt += (
            "\n\nNATURAL RECOMPOSITION PERMISSION:\n"
            "You MAY stitch non-contiguous moments into a single multi-segment clip using the existing `segments` array when both:\n"
            "(a) The non-contiguous moments clearly belong to the same narrative (returning to the same idea from different angles, completing a setup→payoff arc, or building a single argument across multiple scenes).\n"
            "(b) The stitched version is more coherent than the parts standalone.\n"
            "When in doubt, prefer NOT stitching. A frankenstein clip is worse than two good clips."
        )

    virality_prompt += (
        "\n\n=======================================================\n"
        "TIMESTAMP EXTRACTION RULES:\n"
        "- The 'start_timestamp' and 'end_timestamp' fields must be floating point numbers (in seconds).\n"
        "- They must correspond precisely to the bracketed timestamps (e.g., [12.5s]) inside the transcript.\n"
        "- Example: If the perfect clip starts at '[25.1s] So here is why...' and ends at '[58.6s] ...and that is it.', then set 'start_timestamp': 25.1 and 'end_timestamp': 58.6.\n"
    )
    virality_prompt += """
---
SELF-VALIDATION — MANDATORY BEFORE RETURNING OUTPUT
Before returning the JSON array, silently verify every item in this list.
If any check fails, fix the output before returning. Do not explain the
fix. Simply return the corrected JSON.

□ Every clip has all required fields: title, segments,
  virality_score, start_timestamp, end_timestamp, hook_sentence, hook_text,
  hook_type, virality_reason, theme, music_query, broll_keywords,
  emoji_moments, source_topic
□ hook_type is exactly one of: curiosity_gap | loss_aversion |
  self_identification | pattern_interrupt | open_loop | opinion_bomb
□ hook_text is a 3-7 word VIEWER HOOK specific to THIS clip's subject. Generic filler ("Nobody talks about this", "This changed everything", "Wait, seriously?") is BANNED — these exact phrases are forbidden output. Also BANNED: any hook containing "secret", "shocking", "truth", "surprising", "harsh truth", "dark secret", or "nobody tells you". The hook must include at least one of: specific number, contrarian claim, or named subject challenged. Generic benefit-only hooks (e.g. "The Smart Way to Buy", "Multiply Your Income") are BANNED.
□ virality_score is an integer between 0 and 100 — not a string, not a float
□ broll_keywords is a list of strings, not a single string
□ emoji_moments is a list of strings
□ segments is a list of objects each with start_quote (string) and end_quote (string) — exact words from the transcript
□ No field has a null value — use empty string "" or empty list [] as fallback
□ Output is a valid JSON array only — no markdown, no commentary, no
  explanation outside the array

---
"""

    if topics and len(topics) > 0:
        # -- Topic-Aware Extraction --
        clips_per_topic = max(2, min(6, -(-num_clips // max(1, len(topics)))))
        
        def process_topic(tidx, topic):
            ui_logger.log(f"Topic {tidx + 1}/{len(topics)}: \"{topic['topic']}\"")
            topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"], llm_path=llm_path)
            if not topic_text.strip(): return []

            topic_peaks = [] if not energy_peaks else [
                p for p in energy_peaks
                if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
            ]
            topic_scene_peaks = [] if not scene_peaks else [
                p for p in scene_peaks
                if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
            ]

            energy_hint = ""
            if topic_peaks:
                peak_times = ", ".join(f"{p['time']:.1f}" for p in topic_peaks)
                energy_hint = (
                    f"\n\nHIGH-ENERGY AUDIO MOMENTS detected in this topic (laughter, volume\n"
                    f"spikes, excitement peaks) at these timestamps in seconds:\n"
                    f"{peak_times}\n"
                    f"Strongly prefer clips that contain or start near these timestamps.\n"
                    f"These moments have proven audio engagement signals beyond the text."
                )

            scene_hint = ""
            if topic_scene_peaks:
                scene_times = ", ".join(f"{p['time']:.1f}" for p in topic_scene_peaks)
                scene_hint = (
                    f"\n\nHIGH-ATTENTION VISUAL MOMENTS detected in this topic (scene changes —\n"
                    f"content cuts, screen transitions). Timestamps in seconds:\n"
                    f"{scene_times}\n"
                    f"Weight clip selection around these — the visual context shifted at these moments."
                )

            prompt = (
                f"{virality_prompt}\n\n"
                f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                f"Extract the most engaging moments from this section.\n"
                f"MINIMUM OUTPUT RULE: You MUST return at least 2 clips from this section. "
                f"Every spoken section of a video contains at least one quotable statement, claim, or insight — "
                f"find them. Only return an empty list if the section is literally silent or pure noise. "
                f"Do NOT return {{\"clips\": []}} just because nothing feels 100% viral; a solid 75-scoring moment is far better than nothing. "
                f"Aim for {clips_per_topic} clips.\n"
                f"Clip length: each clip must be 20-45 seconds of spoken content. Never extract a clip shorter than 15 seconds.\n"
                f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (20-45s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.{energy_hint}{scene_hint}\n\n"
                f"Transcript:\n{topic_text}\n\n"
                f"Respond ONLY with a JSON object containing a 'clips' array:\n{schema}"
            )
            try:
                final_prompt = build_enhanced_prompt(prompt, session_id)
                results = _execute_with_fallback(llm, system, final_prompt, max_tokens=4096, session_id=session_id)
                if isinstance(results, dict):
                    results = results.get("clips", results.get("highlights", [results]))
                if not isinstance(results, list):
                    results = []
                valid_clips = []
                for clip in results:
                    if isinstance(clip, dict):
                        clip["source_topic"] = topic["topic"]
                        clip["source_topic_idx"] = tidx
                        clip["topic_start"] = topic.get("start_time", 0)
                        clip["topic_end"] = topic.get("end_time", 9999)
                        valid_clips.append(clip)
                return valid_clips
            except Exception as e:
                ui_logger.log(f"Warning: Topic {tidx + 1} extraction failed — {e}")
                logger.log_app_event('extraction_topic', 'failed', {'topic': topic['topic'], 'error': str(e)})
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(process_topic, tidx, topic): tidx for tidx, topic in enumerate(topics)}
            for future in concurrent.futures.as_completed(futures):
                all_highlights.extend(future.result())

        if not all_highlights and topics:
            ui_logger.log(f"Recovering clip candidates directly from {len(topics)} identified topic timestamps...")
            for tidx, top in enumerate(topics):
                t_st = float(top.get("start_time", 0))
                t_et = float(top.get("end_time", 0))
                if t_et - t_st >= 15.0:
                    clip_dur = min(60.0, t_et - t_st)
                    all_highlights.append({
                        "title": top.get("topic", f"Discussion Highlight {tidx + 1}"),
                        "virality_score": 85,
                        "start_timestamp": t_st,
                        "end_timestamp": t_st + clip_dur,
                        "segments": [],
                        "virality_reason": top.get("summary", "Key discussion moment."),
                        "source_topic": top.get("topic", "General"),
                        "theme": "Educational",
                        "music_query": "upbeat lo-fi",
                        "broll_keywords": [],
                        "emoji_moments": [],
                        "hook_text": top.get("topic", "Key Discussion"),
                        "hook_sentence": top.get("topic", "Key Discussion"),
                        "hook_type": "curiosity_gap"
                    })
    else:
        # ── Fallback: Run topic indexing first, then extract per-topic ──
        ui_logger.log("No topics provided — running automatic topic indexing (Pass 1)...")
        auto_topics = get_topic_index(transcript_data, llm_path, gpu_layers, language, session_id=session_id)

        if auto_topics:
            clips_per_topic = max(2, min(6, -(-num_clips // max(1, len(auto_topics)))))
            for tidx, topic in enumerate(auto_topics):
                ui_logger.log(f"Topic {tidx + 1}/{len(auto_topics)}: \"{topic['topic']}\"")
                topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"], llm_path=llm_path)
                if not topic_text.strip():
                    continue

                topic_peaks = [] if not energy_peaks else [
                    p for p in energy_peaks
                    if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
                ]
                topic_scene_peaks = [] if not scene_peaks else [
                    p for p in scene_peaks
                    if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
                ]

                energy_hint = ""
                if topic_peaks:
                    peak_times = ", ".join(f"{p['time']:.1f}" for p in topic_peaks)
                    energy_hint = (
                        f"\n\nHIGH-ENERGY AUDIO MOMENTS detected in this topic (laughter, volume\n"
                        f"spikes, excitement peaks) at these timestamps in seconds:\n"
                        f"{peak_times}\n"
                        f"Strongly prefer clips that contain or start near these timestamps.\n"
                        f"These moments have proven audio engagement signals beyond the text."
                    )

                scene_hint = ""
                if topic_scene_peaks:
                    scene_times = ", ".join(f"{p['time']:.1f}" for p in topic_scene_peaks)
                    scene_hint = (
                        f"\n\nHIGH-ATTENTION VISUAL MOMENTS detected in this topic (scene changes —\n"
                        f"content cuts, screen transitions). Timestamps in seconds:\n"
                        f"{scene_times}\n"
                        f"Weight clip selection around these — the visual context shifted at these moments."
                    )

                prompt = (
                    f"{virality_prompt}\n\n"
                    f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                    f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                    f"Extract the most engaging moments from this section.\n"
                    f"MINIMUM OUTPUT RULE: You MUST return at least 2 clips from this section. "
                    f"Every spoken section of a video contains at least one quotable statement, claim, or insight — "
                    f"find them. Only return an empty list if the section is literally silent or pure noise. "
                    f"Do NOT return {{\"clips\": []}} just because nothing feels 100% viral; a solid 75-scoring moment is far better than nothing.\n"
                    f"Clip length: each clip must be 20-45 seconds of spoken content. Never extract a clip shorter than 15 seconds.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (20-45s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.{energy_hint}{scene_hint}\n\n"
                    f"Transcript:\n{topic_text}\n\n"
                    f"Respond ONLY with a JSON object containing a 'clips' array:\n{schema}"
                )
                try:
                    prompt = build_enhanced_prompt(prompt, session_id)
                    results = _execute_with_fallback(llm, system, prompt, max_tokens=4096, session_id=session_id)
                    if isinstance(results, dict):
                        results = results.get("clips", results.get("highlights", [results]))
                    if not isinstance(results, list):
                        results = []
                    for clip in results:
                        if isinstance(clip, dict):
                            clip["source_topic"] = topic["topic"]
                            clip["source_topic_idx"] = tidx
                            clip["topic_start"] = topic.get("start_time", 0)
                            clip["topic_end"] = topic.get("end_time", 9999)
                            all_highlights.append(clip)
                except Exception as e:
                    ui_logger.log(f"Warning: Topic {tidx + 1} extraction failed — {e}")
        else:
            ui_logger.log("WARNING: Topic indexing returned no topics. Extracting from chunks as last resort.")
            
            # Use the same sliding window logic — per-model context window
            chunk_chars = _chunk_chars_for_model(llm_path)
            overlap = 1000
            step = max(500, chunk_chars - overlap)
            fallback_chunks = []
            current_chunk = ""
            for line in text.split('\n'):
                if len(current_chunk) + len(line) > chunk_chars and len(current_chunk) > overlap:
                    fallback_chunks.append(current_chunk)
                    current_chunk = current_chunk[-overlap:] + '\n' + line
                else:
                    current_chunk += line + '\n'
            if current_chunk:
                fallback_chunks.append(current_chunk)
                
            for idx, f_chunk in enumerate(fallback_chunks):
                prompt = (
                    f"{virality_prompt}\n\n"
                    f"Extract the most engaging moments from this chunk.\n"
                    f"MINIMUM OUTPUT RULE: You MUST return at least 2 clips from this chunk. Every spoken section of a video contains at least one quotable statement, claim, or insight — find them. Only return an empty list if the chunk is literally silent or pure noise. Do NOT return {{\"clips\": []}} just because nothing feels 100% viral; a solid 75-scoring moment is far better than nothing.\n"
                    f"Clip length: each clip must be 20-45 seconds of spoken content. Never extract a clip shorter than 15 seconds.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (20-45s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.\n\n"
                    f"Transcript (Part {idx+1}/{len(fallback_chunks)}):\n{f_chunk}\n\n"
                    f"Respond ONLY with a JSON object containing a 'clips' array:\n{schema}"
                )
                try:
                    prompt = build_enhanced_prompt(prompt, session_id)
                    results = _execute_with_fallback(llm, system, prompt, max_tokens=4096, session_id=session_id)
                    if isinstance(results, dict):
                        results = results.get("clips", results.get("highlights", [results]))
                    if not isinstance(results, list):
                        results = []
                    all_highlights.extend(results)
                except Exception as e:
                    ui_logger.log(f"Warning: Chunk {idx+1} fallback extraction failed — {e}")

    # ── Coverage sweep: guarantee every spoken region of the video got analyzed ──
    # Even when the LLM fails on some sections (empty results, timeouts), those
    # regions must not die silently. Find un-covered stretches and extract from them.
    def _candidate_span(clip: dict):
        """Return (start, end) timestamp span for a raw LLM clip candidate."""
        segs = clip.get("segments", [])
        for s in segs if isinstance(segs, list) else []:
            # LLMs sometimes leak transcript brackets into quotes — use them as hints
            if isinstance(s, dict):
                m = re.search(r"\[([0-9.]+)s\]", f"{s.get('start_quote', '')} {s.get('end_quote', '')}")
                if m:
                    hint = float(m.group(1))
                    return (hint, hint + 1.0)
        try:
            st = float(clip.get("start_timestamp"))
            et = float(clip.get("end_timestamp"))
            if et > st:
                return (st, et)
        except (TypeError, ValueError):
            pass
        try:
            t_st = float(clip.get("topic_start", 0))
            t_et = float(clip.get("topic_end", 0))
            if t_et > t_st:
                return (t_st, t_et)
        except (TypeError, ValueError):
            pass
        return None

    covered = []
    for cand in all_highlights:
        if isinstance(cand, dict):
            span = _candidate_span(cand)
            if span:
                covered.append(span)
    covered.sort()
    merged_spans = []
    for sp_st, sp_et in covered:
        if merged_spans and sp_st <= merged_spans[-1][1] + 30.0:
            merged_spans[-1][1] = max(merged_spans[-1][1], sp_et)
        else:
            merged_spans.append([sp_st, sp_et])

    sweep_windows = []
    if raw_words and video_dur > 60.0:
        video_start = raw_words[0].get("start", 0.0)
        video_end = video_dur
        prev_end = video_start
        for sp_st, sp_et in merged_spans:
            if sp_st - prev_end >= 45.0:
                sweep_windows.append((prev_end, sp_st))
            prev_end = max(prev_end, sp_et)
        if video_end - prev_end >= 45.0:
            sweep_windows.append((prev_end, video_end))

        # Long gaps get split into ~95s sub-windows so each LLM call sees a
        # focused section (and can return 2+ clips from it).
        split_windows = []
        for g_st, g_et in sweep_windows:
            while g_et - g_st > 110.0:
                split_windows.append((g_st, g_st + 95.0))
                g_st += 95.0
            if g_et - g_st >= 45.0:
                split_windows.append((g_st, g_et))
        sweep_windows = split_windows

        # Bound sweep cost: at most ~1 extra call per 2 minutes of video, hard cap 6
        sweep_cap = min(6, max(2, int(video_dur / 120) + 1))
        if len(sweep_windows) > sweep_cap:
            sweep_windows = sorted(sweep_windows, key=lambda w: w[1] - w[0], reverse=True)[:sweep_cap]
            sweep_windows.sort()

    if sweep_windows and not is_cancelled():
        ui_logger.log(f"Coverage sweep: {len(sweep_windows)} un-analyzed region(s) detected — extracting from them now.")
        for sw_idx, (sw_start, sw_end) in enumerate(sweep_windows):
            if is_cancelled():
                break
            sweep_text = _get_text_slice(text, sw_start, sw_end, llm_path=llm_path)
            if not sweep_text.strip() or len(sweep_text) < 150:
                continue
            # Cap sweep input so a huge gap can't exceed the model context window
            if len(sweep_text) > 12000:
                sweep_text = sweep_text[:12000]
            sw_prompt = (
                f"{virality_prompt}\n\n"
                f"You are analyzing a section of the video ({sw_start:.0f}s to {sw_end:.0f}s) that has not been analyzed yet.\n"
                f"MINIMUM OUTPUT RULE: You MUST return at least 2 clips from this section. "
                f"Every spoken section of a video contains at least one quotable statement, claim, or insight — find them. "
                f"Only return an empty list if the section is literally silent or pure noise.\n"
                f"Clip length: each clip must be 20-45 seconds of spoken content. Never extract a clip shorter than 15 seconds.\n"
                f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. Extract ONE cohesive clip (20-45s) per moment.\n"
                f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote — only raw spoken words. You MUST also output start_timestamp and end_timestamp floating-point keys.\n\n"
                f"Transcript:\n{sweep_text}\n\n"
                f"Respond ONLY with a JSON object containing a 'clips' array:\n{schema}"
            )
            try:
                sw_prompt = build_enhanced_prompt(sw_prompt, session_id)
                results = _execute_with_fallback(llm, system, sw_prompt, max_tokens=4096, session_id=session_id)
                if isinstance(results, dict):
                    results = results.get("clips", results.get("highlights", [results]))
                if not isinstance(results, list):
                    results = []
                for clip in results:
                    if isinstance(clip, dict):
                        clip["source_topic"] = f"Untouched section {sw_idx + 1} ({sw_start:.0f}-{sw_end:.0f}s)"
                        clip["topic_start"] = sw_start
                        clip["topic_end"] = sw_end
                        all_highlights.append(clip)
                ui_logger.log(f"Coverage sweep section {sw_idx + 1}: {len(results)} candidate(s) recovered.")
            except Exception as e:
                ui_logger.log(f"Warning: Coverage sweep section {sw_idx + 1} extraction failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} raw candidates. Validating and scoring...")

    # -- Normalize LLM output into consistent format --
    normalized = []
    for h in all_highlights:
        try:
            ideal_transcript = h.get("ideal_transcript", "")
            
            start_ts = h.get("start_timestamp")
            end_ts = h.get("end_timestamp")
            hint_st = float(start_ts) if start_ts is not None else h.get("topic_start")
            hint_et = float(end_ts) if end_ts is not None else h.get("topic_end")
            
            # Always use exact text mapping if raw_words are available, as LLMs hallucinate timestamps
            segments = []
            if raw_words:
                # Primary: use LLM's segments array (start_quote/end_quote pairs)
                llm_segments = h.get("segments", [])
                if llm_segments and isinstance(llm_segments, list) and all(
                    isinstance(s, dict) and ("start_quote" in s or "end_quote" in s)
                    for s in llm_segments
                ):
                    segments = _map_quotes_to_segments(llm_segments, raw_words, search_start_time=hint_st, search_end_time=hint_et)

                # Fallback: use ideal_transcript text for anchor-based mapping
                if not segments and ideal_transcript:
                    segments = _map_text_to_stitched_segments(ideal_transcript, raw_words)

            # Last resort: LLM timestamps
            if not segments and start_ts is not None and end_ts is not None:
                try:
                    s_t = float(start_ts)
                    e_t = float(end_ts)
                    if e_t > s_t:
                        raw_seg = [{"start_time": s_t, "end_time": e_t, "incomplete_endpoint": False}]
                        segments = _snap_timestamps_to_sentence_boundaries(raw_seg, raw_words) if raw_words else raw_seg
                except (ValueError, TypeError):
                    segments = []
            
            if not segments:
                ui_logger.log(f"DEBUG Discarding clip '{h.get('title', '?')}' because segments is empty. start_ts={start_ts}, end_ts={end_ts}, has_raw={bool(raw_words)}")
                continue

            if raw_words and segments:
                matching_words = [w for w in raw_words if "start" in w and segments[0]["start_time"] <= w["start"] <= segments[-1]["end_time"]]
                ideal_transcript = " ".join(w["word"] for w in matching_words)
            else:
                ideal_transcript = "No transcript text available."

            # Self-referential language detection — flagged for user review,
            # NOT auto-discarded. Both regexes are surfaced via the UI badge.
            has_self_ref = False
            self_ref_phrase = ""
            if _SELF_REFERENTIAL_FILTER.search(ideal_transcript):
                has_self_ref = True
                self_ref_phrase = _SELF_REFERENTIAL_FILTER.search(ideal_transcript).group(0)
            self_ref_match = _SELF_REFERENTIAL_FLAG.search(ideal_transcript)
            if self_ref_match:
                has_self_ref = True
                self_ref_phrase = self_ref_match.group(0)

            score_val = h.get("virality_score", h.get("score", 50))
            try:
                score = max(0, min(100, int(float(score_val))))
            except (ValueError, TypeError):
                score = 50

            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            overall_st = segments[0]["start_time"]
            overall_et = segments[-1]["end_time"]

            # Composite Scoring (P3)
            clip_peaks = [p["energy"] for p in (energy_peaks or []) if overall_st - 2 <= p["time"] <= overall_et + 2]
            hook_type = h.get("hook_type", "curiosity_gap")
            
            # Prioritize hook types: opinion_bomb (+15), pattern_interrupt (+10), curiosity_gap (+8)
            hook_bonus = 0
            if hook_type == "opinion_bomb":
                hook_bonus = 15
            elif hook_type == "pattern_interrupt":
                hook_bonus = 10
            elif hook_type == "curiosity_gap":
                hook_bonus = 8

            if clip_peaks:
                # Energy data available — blend virality + energy
                energy_score = int(max(clip_peaks) * 100)
                composite_score = int((score * 0.6) + (energy_score * 0.4)) + hook_bonus
            else:
                # No energy coverage for this timestamp — rank on virality alone.
                energy_score = 0
                composite_score = score + hook_bonus
            composite_score = min(100, composite_score)

            sentences = re.split(r'(?<=[.!?।|])\s+', ideal_transcript.strip())
            # Read from LLM output, fallback to first sentence if empty/missing
            hook_sentence = h.get("hook_sentence", "").strip()
            if not hook_sentence:
                hook_sentence = sentences[0] if sentences else ""
                
            clip_title = h.get("title", "Untitled Clip")
            
            normalized.append({
                "title": clip_title,
                "ideal_transcript": ideal_transcript,
                "segments": segments,
                "start_time": overall_st,
                "end_time": overall_et,
                "score": composite_score,
                "virality_score": score,
                "energy_score": energy_score,
                "hook_sentence": hook_sentence,
                "hook_text": _sanitize_hook_text(h.get("hook_text", ""), hook_sentence),
                "word_timestamps": matching_words if 'matching_words' in locals() else [],
                "viral_hook_angles": {
                    "curiosity": f"The Secret Behind {(clip_title or hook_sentence)[:30]}...",
                    "contrarian": f"Why Everyone Is Wrong About {(clip_title or hook_sentence)[:28]}",
                    "financial": f"The $100K Secret To {(clip_title or hook_sentence)[:30]}",
                    "story": f"He Didn't Realize What Happened Next...",
                    "actionable": f"Do This Immediately If You Want Results",
                },
                "hook_type": hook_type,
                "virality_reason": h.get("virality_reason", ""),
                "theme": theme,
                "music_query": h.get("music_query", ""),
                "broll_keywords": h.get("broll_keywords", []),
                "emoji_moments": h.get("emoji_moments", []),
                "source_topic": h.get("source_topic", "General"),
                "incomplete_endpoint": segments[-1].get("incomplete_endpoint", False) if segments else False,
                "has_self_ref": has_self_ref,
                "self_ref_phrase": self_ref_phrase,
            })
        except Exception as e:
            ui_logger.log(f"Warning: Failed to normalize clip candidate: {e}")
            continue

    # ── Post-LLM Validation ──
    ui_logger.log(f"Running post-LLM validation on {len(normalized)} candidates...")
    validated = _validate_clips(normalized, raw_words, max_duration=max_duration)
    
    # Sort by score
    validated.sort(key=lambda x: x["score"], reverse=True)

    # Dedup using timestamp overlap (>50% of the shorter clip)
    deduped = []
    for h in validated:
        h_st = h["start_time"]
        h_et = h["end_time"]
        h_dur = h_et - h_st

        is_duplicate = False
        for existing in deduped:
            e_st = existing["start_time"]
            e_et = existing["end_time"]
            e_dur = e_et - e_st

            overlap_start = max(h_st, e_st)
            overlap_end = min(h_et, e_et)
            overlap_dur = max(0, overlap_end - overlap_start)

            if h_dur > 0 and e_dur > 0:
                min_dur = min(h_dur, e_dur)
                if overlap_dur / min_dur > 0.50:
                    is_duplicate = True
                    break
        if not is_duplicate:
            deduped.append(h)

    final = deduped[:max_clips]
    ui_logger.log(f"Done. {len(final)} top clips passed validation.")
    logger.log_app_event('extraction', 'completed', {
        'clips_found': len(final),
        'avg_virality': sum(c.get('virality_score', 0) for c in final) / len(final) if final else 0
    })
    return {"highlights": final}


# backwards-compat alias
get_viral_clips = get_highlights
