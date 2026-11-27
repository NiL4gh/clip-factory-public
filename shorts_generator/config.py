import os
import sys

# Force UTF-8 encoding on Windows streams to prevent cp1252 charmap errors
os.environ["PYTHONUTF8"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(encoding="utf-8")

# ── Drive detection ──────────────────────────────────────────────
DRIVE_ROOT = "/content/drive/MyDrive"
IN_COLAB = os.path.exists("/content")
DRIVE_MOUNTED = os.path.exists(DRIVE_ROOT)

import sys
IS_FROZEN = getattr(sys, 'frozen', False)

# Calculate Repo root dynamically
if IS_FROZEN:
    REPO_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    EXE_DIR = os.path.dirname(sys.executable)
    BASE_DIR = os.getenv("BASE_DIR", EXE_DIR)
    WORK_DIR = os.getenv("WORK_DIR", os.path.join(EXE_DIR, "work"))
else:
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if IN_COLAB:
        if DRIVE_MOUNTED:
            BASE_DIR = os.getenv("BASE_DIR", f"{DRIVE_ROOT}/clip_factory")
        else:
            BASE_DIR = os.getenv("BASE_DIR", "/content/clip_factory")
        WORK_DIR = os.getenv("WORK_DIR", os.path.join(REPO_ROOT, "work"))
    else:
        BASE_DIR = os.getenv("BASE_DIR", REPO_ROOT)
        WORK_DIR = os.getenv("WORK_DIR", os.path.join(REPO_ROOT, "work"))

# Create a hidden system directory for internal data
SYSTEM_DIR = os.getenv("SYSTEM_DIR", os.path.join(BASE_DIR, ".system"))

# Persistent, large — must NOT move or models re-download (slow). Keep these paths stable.
LLM_DIR      = os.getenv("LLM_DIR",      os.path.join(SYSTEM_DIR, "models", "llm"))
WHISPER_DIR  = os.getenv("WHISPER_DIR",  os.path.join(SYSTEM_DIR, "models", "whisper"))
# Per-video data, outputs, resumable sessions, and diagnosis logs.
PROJECTS_DIR = os.getenv("PROJECTS_DIR", os.path.join(SYSTEM_DIR, "projects"))
SESSIONS_DIR = os.getenv("SESSIONS_DIR", os.path.join(SYSTEM_DIR, "sessions"))
OUTPUT_DIR   = os.getenv("OUTPUT_DIR",   os.path.join(BASE_DIR, "output"))
LOGS_DIR     = os.getenv("LOGS_DIR",     os.path.join(BASE_DIR, "logs"))
COOKIE_PATH  = os.getenv("COOKIE_PATH",  os.path.join(BASE_DIR, "cookies.txt"))

# Campaign lookup: repo-local campaigns/ folder first, then any legacy
# BASE_DIR/campaigns location. No hardcoded developer paths.
_candidate_campaign_dirs = [
    os.path.join(BASE_DIR, "campaigns"),
    os.path.join(REPO_ROOT, "campaigns"),
]
CAMPAIGNS_DIR = os.getenv("CAMPAIGNS_DIR")
if not CAMPAIGNS_DIR:
    for _cand in _candidate_campaign_dirs:
        if os.path.isdir(_cand):
            CAMPAIGNS_DIR = _cand
            break
if not CAMPAIGNS_DIR:
    CAMPAIGNS_DIR = os.path.join(BASE_DIR, "campaigns")

if not os.path.exists(CAMPAIGNS_DIR):
    try:
        os.makedirs(CAMPAIGNS_DIR, exist_ok=True)
    except OSError:
        pass


# Load .env file from BASE_DIR if it exists, otherwise default load_dotenv
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

# ── Environment configuration ─────────────────────────────────────



# ── Font Configuration ───────────────────────────────────────────
from pathlib import Path
FONT_DIR = Path(WORK_DIR) / "fonts"
if not FONT_DIR.exists() and (Path(REPO_ROOT) / "work" / "fonts").exists():
    FONT_DIR = Path(REPO_ROOT) / "work" / "fonts"
AVAILABLE_FONTS = {
    'montserrat': FONT_DIR / 'Montserrat-Bold.ttf',
    'montserrat bold': FONT_DIR / 'Montserrat-Bold.ttf',
    'montserrat semibold': FONT_DIR / 'Montserrat-SemiBold.ttf',
    'montserrat-semibold': FONT_DIR / 'Montserrat-SemiBold.ttf',
    'montserrat black': FONT_DIR / 'Montserrat-Black.ttf',
    'montserrat-black': FONT_DIR / 'Montserrat-Black.ttf',
    'bebas': FONT_DIR / 'BebasNeue-Regular.ttf',
    'bebas neue': FONT_DIR / 'BebasNeue-Regular.ttf',
    'inter': FONT_DIR / 'Inter-Bold.ttf',
    'roboto': FONT_DIR / 'Roboto-Bold.ttf',
    'poppins': FONT_DIR / 'Poppins-Bold.ttf',
}
# Retain original case keys for backwards-compatibility and references
AVAILABLE_FONTS.update({
    'Montserrat': AVAILABLE_FONTS['montserrat'],
    'Montserrat SemiBold': AVAILABLE_FONTS['montserrat semibold'],
    'Montserrat Black': AVAILABLE_FONTS['montserrat-black'],
    'Bebas Neue': AVAILABLE_FONTS['bebas neue'],
    'Inter': AVAILABLE_FONTS['inter'],
    'Roboto': AVAILABLE_FONTS['roboto'],
    'Poppins': AVAILABLE_FONTS['poppins'],
})
FONT_PATH = AVAILABLE_FONTS['Montserrat']

# Warn on import if fonts missing
for name, path in AVAILABLE_FONTS.items():
    if not path.exists():
        print(f'⚠️  Font missing: {name} at {path}')

# ── API-only LLM catalog ────────────────────────────────────────────
# NIMStats-verified lineup (https://github.com/MauroDruwel/NIMStats
# benchmarks 22 NIM models hourly at nimsynth.maurodruwel.com/top).
#
# Removed: nvidia/llama-3.1-nemotron-70b-instruct (404 on every call -
#   NVIDIA retired it post-Nemotron winter 2025 — duplicate entry in
#   old catalog meant 2× 404 overhead per pipeline).
# Restored: deepseek-v4-flash and deepseek-v4-pro (confirmed real by
#   NIMStats; were incorrectly removed in Session 9 C15 as "hallucinated").
#
# Local model support (llama-cpp-python) removed by Session 13 owner
# decision. Go to Settings → API Keys to add GEMINI/GROQ/NVIDIA/OPENROUTER/GLM keys.
LLM_CATALOG = [
    # ── TokenRouter API (Fast Flagship - Free Tier) ───────────────
    {"label": "👑 TokenRouter: Qwen 3.8 Max (Flagship - Free)",
     "filename": "qwen/qwen3.8-max-free",
     "repo": "tokenrouter",
     "gpu_layers": 0,
     "context_window": 128000},

    # ── NVIDIA NIM API (Active Fast Models) ───────────────────────
    {"label": "🏆 NVIDIA: Nemotron 3 Super 120B",
     "filename": "nvidia/nemotron-3-super-120b-a12b",
     "repo": "nvidia",
     "gpu_layers": 0,
     "context_window": 128000},
    {"label": "⚡ NVIDIA: Step 3.7 Flash",
     "filename": "stepfun-ai/step-3.7-flash",
     "repo": "nvidia",
     "gpu_layers": 0,
     "context_window": 128000},
    {"label": "💎 NVIDIA: Laguna XS 2.1",
     "filename": "poolside/laguna-xs-2.1",
     "repo": "nvidia",
     "gpu_layers": 0,
     "context_window": 128000},
    {"label": "🧠 NVIDIA: GPT OSS 120B",
     "filename": "openai/gpt-oss-120b",
     "repo": "nvidia",
     "gpu_layers": 0,
     "context_window": 128000},
    {"label": "👑 OpenRouter: Claude 3.5 Sonnet",
     "filename": "anthropic/claude-3.5-sonnet",
     "repo": "openrouter",
     "gpu_layers": 0,
     "context_window": 200000},

    # ── Groq API (High Speed 70B) ───────────────────────────────
    {"label": "⚡ Groq: Llama 3.3 70B Versatile",
     "filename": "llama-3.3-70b-versatile",
     "repo": "groq",
     "gpu_layers": 0,
     "context_window": 128000},

    # ── Gemini API (Google DeepMind) ───────────────────────────
    {"label": "✨ Google: Gemini 2.0 Flash",
     "filename": "gemini-2.0-flash",
     "repo": "gemini",
     "gpu_layers": 0,
     "context_window": 1000000},
    {"label": "✨ Google: Gemini 1.5 Pro",
     "filename": "gemini-1.5-pro",
     "repo": "gemini",
     "gpu_layers": 0,
     "context_window": 2000000},
]

WHISPER_CATALOG = [
    {"label": "🐢 tiny",     "size": "tiny"},
    {"label": "🐇 base",     "size": "base"},
    {"label": "🏃 small",    "size": "small"},
    {"label": "⭐ medium",   "size": "medium"},
    {"label": "🌟 large-v2", "size": "large-v2"},
    {"label": "💎 large-v3", "size": "large-v3"},
]
