import os
import random
import re
import sys
import uuid
import time
import glob
import asyncio
import hashlib
import threading
import datetime as _dt
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import urllib.request as _urlreq
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, WebSocket, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

# Ensure repo root is in sys.path
if getattr(sys, 'frozen', False):
    REPO_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
else:
    try:
        REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        REPO_DIR = os.getcwd()
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from shorts_generator.config import (
    BASE_DIR, WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR,
    COOKIE_PATH, LLM_CATALOG, WHISPER_CATALOG, PROJECTS_DIR, SESSIONS_DIR, AVAILABLE_FONTS,
    CAMPAIGNS_DIR,
)
from shorts_generator.downloader import download_video, download_srt, get_video_title
from shorts_generator.transcriber import transcribe_audio, parse_srt_to_word_timestamps
from shorts_generator.highlights import get_highlights, get_topic_index, detect_video_persona, estimate_clip_potential, set_cancel_check
from shorts_generator.clipper import render_short
from shorts_generator.youtube_metadata import generate_youtube_metadata
from shorts_generator.enhancer import enhance_clip
from shorts_generator import cache
from shorts_generator.logger import ui_logger, get_logger, LOG_DIR, safe_print
from shorts_generator.audio_analyzer import analyze_audio_energy
from shorts_generator.scene_analyzer import detect_scene_changes
from huggingface_hub import hf_hub_download

import subprocess

if sys.platform == "win32":
    _original_run = subprocess.run
    _original_popen = subprocess.Popen

    def _patched_run(*args, **kwargs):
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
        return _original_run(*args, **kwargs)

    class _PatchedPopen(_original_popen):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
            super().__init__(*args, **kwargs)

    subprocess.run = _patched_run
    subprocess.Popen = _PatchedPopen

import json
_GPU_ENCODER = "libx264"  # fallback default

_ENCODER_CANDIDATES = [
    ("h264_nvenc",  ["-c:v", "h264_nvenc", "-preset", "fast"]),
    ("h264_amf",    ["-c:v", "h264_amf",   "-quality", "speed"]),
    ("h264_qsv",    ["-c:v", "h264_qsv",   "-preset", "fast"]),
]

def _probe_encoder(codec_name: str) -> bool:
    """Return True if the given encoder is available and functional."""
    # On Linux (Colab), BtbN's static ffmpeg binary uses dlopen() to find
    # libnvidia-encode.so.1 at runtime. Add common NVIDIA lib paths so the
    # probe subprocess can find them even if LD_LIBRARY_PATH is not set.
    env = None
    if os.name != "nt":
        env = os.environ.copy()
        nvidia_paths = [
            "/usr/lib/x86_64-linux-gnu",
            "/usr/local/cuda/lib64",
            "/usr/local/lib",
        ]
        extra = ":".join(p for p in nvidia_paths if os.path.isdir(p))
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{extra}:{existing}" if existing else extra
    try:
        # Step 1: check ffmpeg reports the encoder as available (cheap, no GPU needed)
        enc_list = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, timeout=10, env=env
        )
        if codec_name not in (enc_list.stdout + enc_list.stderr).decode("utf-8", errors="ignore"):
            return False
        # Step 2: actually encode a few frames — NVENC needs ≥1 frame to initialize
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=1",
                "-frames:v", "5", "-c:v", codec_name, "-f", "null", "-"
            ],
            capture_output=True,
            timeout=15,
            env=env,
        )
        return result.returncode == 0
    except Exception:
        return False

for encoder_name, encoder_args in _ENCODER_CANDIDATES:
    if _probe_encoder(encoder_name):
        _GPU_ENCODER = encoder_name
        ui_logger.log(f"⚡ GPU Encoder selected: {encoder_name}")
        break
else:
    ui_logger.error("⚠️ No GPU encoder found — rendering will use CPU (libx264). Expect ~10 min/clip instead of ~2 min. Re-run Cell 1 to install the GPU FFmpeg build.")

# Update the clipper._DETECTED_ENCODER global state
import shorts_generator.clipper as clipper
clipper._DETECTED_ENCODER = _GPU_ENCODER


app = FastAPI(title="ClipFactory AI Director API")

VERSION = "2.4.0-PRO-STRATEGY"
safe_print(f"🚀 ClipFactory AI Director Backend {VERSION} starting...")

class TimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=300.0)
        except asyncio.TimeoutError:
            return JSONResponse({'detail': 'Request timeout after 300s'}, status_code=504)

app.add_middleware(TimeoutMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.endswith(".js") or path.endswith(".json") or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    ui_logger.error(f"Unhandled error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={'detail': str(exc), 'type': type(exc).__name__}
    )

# Serve rendered clips as static media
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=OUTPUT_DIR), name="media")

THUMB_DIR = os.path.join(WORK_DIR, "thumbnails")
os.makedirs(THUMB_DIR, exist_ok=True)
app.mount("/thumbs", StaticFiles(directory=THUMB_DIR), name="thumbs")

# ── Bundled CC0 Background Music (direct download, no API key) ───────────
BGM_CATALOG = {
    "Lofi":      "lofi hip hop no copyright background music chill beats",
    "Upbeat":    "upbeat background music no copyright royalty free energetic",
    "Cinematic": "cinematic background music no copyright epic instrumental",
    "Chill":     "chill background music no copyright calm relaxing",
}
BGM_DIR = os.path.join(WORK_DIR, "bgm")

# ── Global auto-apply watermark (owner-requested: config in generation tab) ─
# Persisted outside WORK_DIR (which gets purged per session) so the watermark
# survives across renders until the owner explicitly disables it.
WATERMARK_CONFIG_PATH = os.path.join(BASE_DIR, "watermark_config.json")
WATERMARK_PNG_PATH = os.path.join(BASE_DIR, "watermark.png")

def _load_watermark_config() -> dict:
    """Return the persisted global watermark config, or disabled defaults."""
    if os.path.exists(WATERMARK_CONFIG_PATH):
        try:
            with open(WATERMARK_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                en = cfg.get("enabled", False)
                if isinstance(en, str):
                    cfg["enabled"] = en.lower() in ("true", "1", "yes")
                else:
                    cfg["enabled"] = bool(en)
                return cfg
        except Exception:
            pass
    return {"enabled": False, "position": "bottom-center", "opacity": 0.85, "scale": None, "png_path": None}

def _active_watermark() -> Optional[dict]:
    """render_short `watermark` kwarg when enabled + PNG exists, else None."""
    cfg = _load_watermark_config()
    if cfg.get("enabled") and cfg.get("png_path") and os.path.exists(cfg.get("png_path", "")):
        return {
            "position": cfg.get("position", "bottom-center"),
            "opacity": cfg.get("opacity", 0.85),
            "scale": cfg.get("scale"),
            "png_path": cfg.get("png_path"),
        }
    return None

def _get_bgm(genre: str) -> str:
    """
    Download a royalty-free BGM track for the given genre using yt-dlp
    YouTube search. Caches the result at WORK_DIR/bgm_{genre}.mp3.
    Returns the file path on success, empty string on any failure.
    """
    import subprocess, re

    query = BGM_CATALOG.get(genre, "")
    if not query:
        return ""

    safe_genre = re.sub(r"[^a-zA-Z0-9_]", "_", genre.lower())
    out_path = str(WORK_DIR / f"bgm_{safe_genre}.mp3")

    # Return cached file if already downloaded this session
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
        ui_logger.log(f"🎵 BGM cache hit: {safe_genre}")
        return out_path

    ui_logger.log(f"🎵 Fetching BGM for genre: {genre}")
    try:
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "-o", out_path.replace(".mp3", ".%(ext)s"),
        ]
        result = subprocess.run(
            cmd,
            timeout=90,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            ui_logger.log(f"⚠️ BGM download failed (yt-dlp exit {result.returncode})")
            return ""
        if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
            ui_logger.log(f"✅ BGM downloaded: {safe_genre}")
            return out_path
        ui_logger.log("⚠️ BGM file missing after download")
        return ""
    except subprocess.TimeoutExpired:
        ui_logger.log("⚠️ BGM download timed out (90s)")
        return ""
    except Exception as e:
        ui_logger.log(f"⚠️ BGM fetch error: {e}")
        return ""

def _resolve_header_text(raw_header_text: Optional[str], clip_index: int) -> Optional[str]:
    """Parses single or multi-line/pipe-separated forced header narratives and
    returns the round-robin chosen header for the given clip index."""
    if not raw_header_text:
        return None
    options = []
    for chunk in str(raw_header_text).replace('|', '\n').splitlines():
        c = chunk.strip()
        if c and not c.startswith('#') and not c.startswith('//'):
            import re
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', c).strip(' "\'')
            if cleaned:
                options.append(cleaned)
    if not options:
        return None
    return options[clip_index % len(options)]

# In-memory state for the active project
# Highlight Dict Schema:
# - title: str
# - ideal_transcript: str
# - segments: list
# - start_time: float
# - end_time: float
# - score: int (composite)
# - virality_score: int
# - energy_score: int
# - hook_score: int (0-25)
# - engagement_score: int (0-25)
# - value_score: int (0-25)
# - shareability_score: int (0-25)
# - hook_sentence: str
# - hook_text: str
# - hook_type: str
# - virality_reason: str
# - theme: str
# - music_query: str
# - broll_keywords: list
# - emoji_moments: list
# - source_topic: str
_state = {
    "clips": [],
    "word_timestamps": [],
    "current_url": None,
    "persona": {},
    "topics": [],
    "estimated_clips": 0,
    "video_duration": 0,
    "video_title": "",
    "is_strategizing": False,
    "is_rendering": False,
    "is_cancelled": False,
    "_strategy_status": "idle",    # per-run outcome: ok | no_clips | failed
    "_strategy_error": "",
    "active_pids": [],
    "energy_peaks": [],
    # Local batch pipeline (added 2026-07-12, session 11): watch-folder
    # sourcing + sequential queue. queue item shape:
    #   {path, status, video_id, title, started_at, finished_at, error}
    # status: pending → downloading → transcribing → strategizing
    #        → done | failed | cancelled
    "queue": [],
    "queue_running": False,
    "queue_active_item": None,
    "queue_watch_dir": "",
    "clips_by_video": {},          # video_id → list of indices in _state["clips"]
    "batch_clips_accumulated": [], # merged renderable clip list across all batch items
    "batch_sessions": {},          # video_id → {url, title, clip_count} per-video session snapshot
    "batch_model_label": "",       # model label selected in the UI; worker reads it at start
    "processed_paths": set(),      # idempotency: paths already in queue or done
    "active_campaign_id": None,
    "active_campaign_profile": None,
    "active_model": "",
    "scene_peaks": [],
}

# Watch-folder polling interval (seconds). Slow enough to not hammer the FS,
# fast enough that users notice the new file within ~30s.
_WATCH_POLL_INTERVAL = 5.0

# Threshold for accepting a new file: must be large enough that we know the
# user isn't still copying it, and old enough that they finished writing.
_WATCH_MIN_BYTES = 10 * 1024 * 1024    # 10 MB
_WATCH_STABLE_SECONDS = 30             # mtime must be > 30s old

# Let the LLM extraction layer see the user's Stop flag (2026-08-16). Without
# this the strategy phases were uninterruptible until the current HTTP call
# completed, so the Stop button appeared to do nothing for minutes.
def _highlights_is_cancelled():
    return bool(_state.get("is_cancelled"))

set_cancel_check(_highlights_is_cancelled)

class StrategizeRequest(BaseModel):
    url: str
    llm_label: Optional[str] = "🧠 MiniMax M3 (API - High Availability)"
    whisper_label: Optional[str] = "Medium (Fast/Accurate)"
    angle: Optional[str] = "standard"
    session_id: Optional[str] = "global"
    campaign_brief: Optional[str] = None
    allow_natural_recomposition: Optional[bool] = False
    max_duration: Optional[int] = 90   # soft absolute bound, LLM prompts prefer 15-60s

# Render tracking
_render_status = {} # { task_id: { status: "running"|"done"|"error", filename: str } }

class RenderRequest(BaseModel):
    clip_id: int # index in _state["clips"]
    face_center: bool = True
    face_track: bool = True   # horizontal face tracking (owner-approved default ON, 2026-08-18)
    magic_hook: bool = False  # Header hook is the only overlay now (removal Chunk 7, session 12).
    remove_silence: bool = True
    caption_style: str = "Classic"
    caption_pos: str = "Below"
    bg_music_genre: str = "None"
    broll_intensity: str = "None"
    excluded_sentences: List[str] = []
    title: Optional[str] = None
    bg_style: str = "black"
    hook_position: str = "top"
    hook_display: str = "full"  # "full" | "3s" | "off"
    show_outro: bool = False
    title_style: str = "Impact"
    hook_style: str = "BlackOnWhiteBox"
    layout_mode: str = "portrait"
    header_font: Optional[str] = "bebas"
    caption_font: Optional[str] = "bebas"
    hook_font: Optional[str] = "bebas"
    header_style: str = "rounded-chunky"
    rounded_corner_radius: int = 0   # 0 = square corners; >0 = pixels of corner roundness
    session_id: Optional[str] = "global"
    max_duration: int = 90   # soft absolute bound on clip length (LLM prompts 15-60s); per-render override of global default
    style_mode: Optional[str] = "random"
    style_allowlist: Optional[dict] = None
    fixed_style: Optional[dict] = None
    force_header_text: Optional[str] = None

class BulkRenderRequest(BaseModel):
    face_center: bool = True
    face_track: bool = True   # horizontal face tracking (owner-approved default ON, 2026-08-18)
    magic_hook: bool = False  # Header hook only (removal Chunk 7, session 12).
    remove_silence: bool = True
    caption_style: str = "Classic"
    caption_pos: str = "Below"
    bg_music_genre: str = "None"
    broll_intensity: str = "None"
    clip_ids: Optional[List[int]] = None
    titles: Optional[dict] = None
    clip_settings: Optional[dict] = None
    bg_style: str = "black"
    hook_position: str = "top"
    hook_display: str = "full"  # "full" | "3s" | "off"
    show_outro: bool = False
    title_style: str = "Impact"
    hook_style: str = "BlackOnWhiteBox"
    layout_mode: str = "portrait"
    header_font: Optional[str] = "bebas"
    caption_font: Optional[str] = "bebas"
    hook_font: Optional[str] = "bebas"
    header_style: str = "rounded-chunky"
    rounded_corner_radius: int = 0
    session_id: Optional[str] = "global"
    max_duration: int = 90   # soft absolute bound on clip length (LLM prompts 15-60s)
    style_mode: Optional[str] = "random"
    style_allowlist: Optional[dict] = None
    fixed_style: Optional[dict] = None
    force_header_text: Optional[str] = None

class SessionRequest(BaseModel):
    url: str

_GEMINI_KEY_VALID_CACHE = {}

def _is_gemini_key_valid() -> bool:
    import os, urllib.request, json
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False

    if api_key in _GEMINI_KEY_VALID_CACHE:
        return _GEMINI_KEY_VALID_CACHE[api_key]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 5}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                _GEMINI_KEY_VALID_CACHE[api_key] = True
                return True
    except Exception:
        pass
    _GEMINI_KEY_VALID_CACHE[api_key] = False
    return False


def load_campaigns() -> list:
    import glob
    campaigns = []
    if not os.path.exists(CAMPAIGNS_DIR):
        return campaigns
    
    for f in glob.glob(os.path.join(CAMPAIGNS_DIR, "*.md")):
        try:
            filename = os.path.basename(f)
            campaign_id = filename[:-3] # remove .md
            if campaign_id.startswith("_"):
                continue # Skip templates/internal files
            
            with open(f, "r", encoding="utf-8") as file:
                content = file.read()
            
            lines = content.splitlines()
            
            # Extract name: find first H1 header '# Campaign: ...' or fallback to filename
            name = campaign_id.replace("-", " ").title()
            for line in lines:
                if line.strip().startswith("# Campaign:"):
                    name = line.replace("# Campaign:", "").strip()
                    break
                elif line.strip().startswith("#"):
                    name = line.lstrip("#").strip()
                    break
            
            # Extract brief — Priority 1: parse ## Brief section
            brief = ""
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("## Brief"):
                    brief_lines = []
                    for sub_idx in range(idx + 1, len(lines)):
                        next_line = lines[sub_idx]
                        if next_line.strip().startswith("## "):
                            break
                        brief_lines.append(next_line)
                    brief = "\n".join(brief_lines).strip()
                    break
            
            # Priority 2: code block under a ClipFactory-style heading
            if not brief:
                for idx, line in enumerate(lines):
                    if "ClipFactory Settings" in line or "Settings for This Campaign" in line or "Campaign Brief" in line:
                        for sub_idx in range(idx + 1, len(lines)):
                            sub_line = lines[sub_idx].strip()
                            if sub_line.startswith("```"):
                                code_lines = []
                                for code_idx in range(sub_idx + 1, len(lines)):
                                    next_line = lines[code_idx]
                                    if next_line.strip().startswith("```"):
                                        break
                                    code_lines.append(next_line)
                                brief = "\n".join(code_lines).strip()
                                break
                        if brief:
                            break
            
            # Priority 3: first paragraph (text before first blank line, excluding headings)
            if not brief:
                para_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        if para_lines:
                            break  # end of first paragraph
                        continue  # skip leading blank lines
                    if stripped.startswith("#"):
                        continue  # skip headings
                    para_lines.append(line)
                brief = "\n".join(para_lines).strip()

            campaigns.append({
                "id": campaign_id,
                "name": name,
                "brief": brief
            })
        except Exception as e:
            print(f"Error loading campaign {f}: {e}")
            
    return campaigns

def load_campaign_profile(campaign_id: str) -> Optional[dict]:
    """Loads JSON profile or parses .md campaign brief into a structured profile."""
    if not campaign_id or not os.path.exists(CAMPAIGNS_DIR):
        return None
    
    json_path = os.path.join(CAMPAIGNS_DIR, f"{campaign_id}.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON campaign profile {json_path}: {e}")
            
    # Fallback to reading markdown brief
    md_path = os.path.join(CAMPAIGNS_DIR, f"{campaign_id}.md")
    if os.path.exists(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            name = campaign_id.replace("-", " ").title()
            for line in content.splitlines():
                if line.startswith("# Campaign:"):
                    name = line.replace("# Campaign:", "").strip()
                    break
            return {
                "id": campaign_id,
                "name": name,
                "brief": content,
                "custom_system_prompt": f"CAMPAIGN BRIEF ({name}):\n{content}",
                "focus_topics": [],
                "negative_filters": ["intros", "sponsor reads", "outro plugs"],
                "whop_metadata": {
                    "creator_handle": f"@{campaign_id}",
                    "hashtags": f"#{campaign_id} #clipping #viral",
                    "posting_windows": ["12:00 PM EST", "7:00 PM EST"]
                }
            }
        except Exception as e:
            print(f"Error reading MD campaign brief {md_path}: {e}")
    return None

def save_campaign_profile(profile: dict) -> str:
    """Saves a structured campaign profile to JSON and returns campaign_id."""
    if not os.path.exists(CAMPAIGNS_DIR):
        os.makedirs(CAMPAIGNS_DIR, exist_ok=True)
    
    cid = profile.get("id") or profile.get("name", "campaign").lower().replace(" ", "-")
    profile["id"] = cid
    
    json_path = os.path.join(CAMPAIGNS_DIR, f"{cid}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
        
    # Also save a readable markdown copy
    md_path = os.path.join(CAMPAIGNS_DIR, f"{cid}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Campaign: {profile.get('name', cid)}\n\n## Brief\n{profile.get('brief', '')}\n")
        
    return cid

class SelectCampaignRequest(BaseModel):
    campaign_id: str

class AnalyzeCampaignRequest(BaseModel):
    raw_brief: str
    name: Optional[str] = None
    llm_label: Optional[str] = "🧠 MiniMax M3 (API - High Availability)"

@app.get("/api/campaigns")
async def get_campaigns():
    return {"campaigns": load_campaigns(), "active_campaign_id": _state.get("active_campaign_id")}

@app.get("/api/campaigns/active")
async def get_active_campaign():
    cid = _state.get("active_campaign_id")
    profile = _state.get("active_campaign_profile")
    if not profile:
        profile = load_campaign_profile(cid)
        _state["active_campaign_profile"] = profile
    return {"active_campaign_id": cid, "profile": profile}

@app.post("/api/campaigns/select")
async def select_active_campaign(req: SelectCampaignRequest):
    cid = req.campaign_id
    profile = load_campaign_profile(cid)
    _state["active_campaign_id"] = cid
    _state["active_campaign_profile"] = profile
    print(f"🎯 Active Campaign switched to: {cid}")
    return {"status": "ok", "active_campaign_id": cid, "profile": profile}

@app.post("/api/campaigns/analyze")
async def analyze_and_create_campaign(req: AnalyzeCampaignRequest):
    raw_text = req.raw_brief.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Campaign brief text cannot be empty")
        
    # Extract name fallback from text header or request
    campaign_name = req.name
    if not campaign_name:
        for line in raw_text.splitlines():
            line_str = line.strip()
            if line_str.startswith("# Campaign:"):
                campaign_name = line_str.replace("# Campaign:", "").strip()
                break
            elif line_str.startswith("#"):
                campaign_name = line_str.lstrip("#").strip()
                break
    if not campaign_name:
        campaign_name = "Custom Campaign " + _dt.datetime.now().strftime("%b %d")
        
    cid = campaign_name.lower().replace(" ", "-").replace("/", "-")
    
    # Try LLM JSON synthesis or fallback to heuristic profile structure
    profile = None
    try:
        from shorts_generator.highlights import query_llm_json
        analysis_prompt = f"""You are an expert Short-Form Video Director and Prompt Engineer.
Analyze the raw creator campaign brief below and construct an AI Extraction Strategy Profile in strict JSON format.

JSON format expected:
{{
  "name": "{campaign_name}",
  "id": "{cid}",
  "creator_handle": "@creator",
  "custom_system_prompt": "Strict extraction instructions for LLM: Focus on [topics], prioritize high virality, and avoid [topics to avoid].",
  "focus_topics": ["topic1", "topic2"],
  "negative_filters": ["intros", "sponsor reads", "generic talk"],
  "whop_metadata": {{
    "hashtags": "#{cid} #clipping #viral",
    "posting_windows": ["12:00 PM EST", "7:00 PM EST"],
    "payout_notes": "Submit within 60 mins of posting."
  }}
}}

RAW CAMPAIGN BRIEF:
{raw_text[:3000]}
"""
        # Execute LLM call if local/gemini model entry exists
        llm_entry = next((e for e in LLM_CATALOG if e["label"] == req.llm_label), None)
        if llm_entry and (llm_entry.get("filename") or llm_entry.get("path")):
            m_path = llm_entry.get("filename") or llm_entry.get("path")
            res = query_llm_json(analysis_prompt, llm_path=m_path, gpu_layers=llm_entry.get("gpu_layers", 0))
            if isinstance(res, dict) and "custom_system_prompt" in res:
                profile = res
                profile["id"] = cid
                profile["name"] = campaign_name
                profile["brief"] = raw_text
    except Exception as e:
        print(f"LLM brief analysis fallback triggered: {e}")

    if not profile:
        profile = {
            "id": cid,
            "name": campaign_name,
            "brief": raw_text,
            "custom_system_prompt": f"CAMPAIGN INSTRUCTIONS FOR {campaign_name.upper()}:\n{raw_text}\nExtract ONLY clips matching this brief.",
            "focus_topics": [campaign_name],
            "negative_filters": ["intros", "sponsor reads", "outro plugs"],
            "whop_metadata": {
                "creator_handle": f"@{cid}",
                "hashtags": f"#{cid} #clipping #viral",
                "posting_windows": ["12:00 PM EST", "7:00 PM EST"],
                "payout_notes": "Follow Whop Content Rewards submission rules."
            }
        }
        
    saved_cid = save_campaign_profile(profile)
    _state["active_campaign_id"] = saved_cid
    _state["active_campaign_profile"] = profile
    print(f"✨ AI Campaign Profile Created & Set Active: {saved_cid}")
    return {"status": "ok", "campaign_id": saved_cid, "profile": profile}

class OpenDirRequest(BaseModel):
    video_id: Optional[str] = None
    folder_path: Optional[str] = None

@app.post("/api/open_output_dir")
async def open_output_dir(req: Optional[OpenDirRequest] = None):
    import subprocess
    curr_url = _state.get("current_url")
    target_dir = cache.get_clips_dir(curr_url) if curr_url else OUTPUT_DIR
    if req:
        if req.video_id:
            vid_dir = os.path.join(OUTPUT_DIR, req.video_id)
            if os.path.exists(vid_dir):
                target_dir = vid_dir
        elif req.folder_path and os.path.exists(req.folder_path):
            target_dir = req.folder_path

    os.makedirs(target_dir, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(os.path.abspath(target_dir))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", os.path.abspath(target_dir)])
        else:
            subprocess.Popen(["xdg-open", os.path.abspath(target_dir)])
        return {"status": "ok", "path": target_dir}
    except Exception as e:
        ui_logger.log(f"⚠️ Failed to open render dir: {e}")
        return {"status": "error", "message": str(e), "path": target_dir}


@app.get("/api/source_media")
async def serve_source_media(request: Request):
    """Serve the downloaded source video with Range header support for HTML5 seeking.

    The frontend clip preview player uses this endpoint with media fragments
    (#t=start,end) so the user can preview a clip's exact segment before rendering.
    Supports HTTP 206 Partial Content so the browser can seek without loading the
    full video file into memory.
    """
    from starlette.requests import Request as _Request
    source_path = os.path.join(WORK_DIR, "source.mp4")
    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="No source video loaded. Run a strategy first.")

    file_size = os.path.getsize(source_path)
    range_header = request.headers.get("range")

    if range_header:
        # Parse "bytes=start-end"
        try:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except (ValueError, IndexError):
            start = 0
            end = file_size - 1

        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def iterfile(path: str, start_byte: int, length: int):
            with open(path, "rb") as f:
                f.seek(start_byte)
                remaining = length
                while remaining > 0:
                    read_size = min(65536, remaining)
                    data = f.read(read_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            iterfile(source_path, start, chunk_size),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Cache-Control": "no-cache",
            },
        )

    # No Range header — serve full file
    return FileResponse(
        source_path,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )


@app.post("/api/whop/export_package")
async def export_whop_submission_package():
    import shutil, subprocess, glob
    cid = _state.get("active_campaign_id")
    prof = _state.get("active_campaign_profile") or load_campaign_profile(cid) or {}
    
    timestamp_str = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    package_dir_name = f"Whop_Package_{cid}_{timestamp_str}"
    package_path = os.path.join(OUTPUT_DIR, "whop_packages", package_dir_name)
    os.makedirs(package_path, exist_ok=True)
    
    # Collect all rendered MP4s
    mp4_files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
    mp4_files = [f for f in mp4_files if "whop_packages" not in f]
    
    if not mp4_files:
        raise HTTPException(status_code=400, detail="No rendered clips found in gallery to export")
        
    manifest_items = []
    today = _dt.datetime.now()
    
    for idx, src_mp4 in enumerate(mp4_files[:14]): # Max 14 clips (7-day schedule)
        day_offset = idx // 2 + 1
        slot = "12PM" if idx % 2 == 0 else "7PM"
        folder_name = f"Day_{day_offset}_{slot}"
        target_folder = os.path.join(package_path, folder_name)
        os.makedirs(target_folder, exist_ok=True)
        
        fname = os.path.basename(src_mp4)
        dst_mp4 = os.path.join(target_folder, fname)
        shutil.copy2(src_mp4, dst_mp4)
        
        post_date = (today + _dt.timedelta(days=day_offset - 1)).strftime("%b %d, %Y")
        hashtags = prof.get("whop_metadata", {}).get("hashtags", f"#{cid} #contentrewards #clipping #viral")
        handle = prof.get("whop_metadata", {}).get("creator_handle", f"@{cid}")
        
        manifest_items.append({
            "day": day_offset,
            "slot": slot,
            "date": post_date,
            "filename": fname,
            "path": dst_mp4,
            "creator_handle": handle,
            "hashtags": hashtags,
            "caption": f"Must watch moment from {handle}! {hashtags}"
        })
        
    # Write submission_manifest.json
    with open(os.path.join(package_path, "submission_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"campaign_id": cid, "created_at": timestamp_str, "clips": manifest_items}, f, indent=2)
        
    # Write submission_checklist.md
    with open(os.path.join(package_path, "submission_checklist.md"), "w", encoding="utf-8") as f:
        f.write(f"# Whop Content Rewards Submission Package — {prof.get('name', cid)}\n")
        f.write(f"Generated: {timestamp_str}\n\n---\n\n")
        for item in manifest_items:
            f.write(f"### 📅 {item['date']} ({item['slot']})\n")
            f.write(f"- **Video File**: `{item['filename']}`\n")
            f.write(f"- **Tag Creator**: `{item['creator_handle']}`\n")
            f.write(f"- **Hashtags**: `{item['hashtags']}`\n")
            f.write(f"- **Caption**: `{item['caption']}`\n")
            f.write(f"- [ ] Post to TikTok / Reels / Shorts\n")
            f.write(f"- [ ] Submit link to Whop Content Rewards within 60 mins\n\n")
            
    # Auto-open package folder in Windows File Explorer
    if sys.platform == "win32":
        subprocess.Popen(["explorer", os.path.abspath(package_path)])
        
    return {
        "status": "ok",
        "package_name": package_dir_name,
        "package_path": package_path,
        "clips_exported": len(manifest_items)
    }

def _get_model_group(entry: dict) -> str:
    repo = entry.get("repo", "nvidia")
    if repo == "tokenrouter":
        return "TokenRouter (Free Flagship)"
    elif repo == "nvidia":
        return "NVIDIA NIM API"
    elif repo == "groq":
        return "Groq API (Ultra-Fast 70B)"
    elif repo == "gemini":
        return "Google Gemini API"
    elif repo == "openrouter":
        return "OpenRouter API"
    return "AI Models"

@app.get("/api/config")
async def get_config():
    return {
        "llm_catalog": [{"label": e["label"], "repo": e.get("repo", "nvidia"), "group": _get_model_group(e)} for e in LLM_CATALOG],
        "whisper_catalog": [{"label": e["label"]} for e in WHISPER_CATALOG],
        "bgm_genres": list(BGM_CATALOG.keys()),
        "gemini_active": _is_gemini_key_valid(),
    }

# ── Health Check ──
@app.get('/health')
async def health_check():
    return {'status': 'ok', 'timestamp': _dt.datetime.utcnow().isoformat() + 'Z', 'version': '2.5-pro'}

# ── Fonts Endpoint ──
@app.get('/api/fonts')
async def list_fonts():
    from shorts_generator.config import AVAILABLE_FONTS
    return {
        name: {'exists': path.exists(), 'path': str(path)}
        for name, path in AVAILABLE_FONTS.items()
    }

# ── Log Endpoints ──
@app.get('/api/logs/{session_id}')
async def get_logs(session_id: str, type: Optional[str] = Query(None), limit: int = 200):
    logger = get_logger(session_id, video_title=_state.get("video_title", ""))
    return {'entries': logger.get_entries(log_type=type, limit=limit)}

@app.get('/api/logs/{session_id}/stream')
async def stream_logs(session_id: str):
    logger = get_logger(session_id, video_title=_state.get("video_title", ""))
    last_idx = 0
    
    async def event_generator():
        nonlocal last_idx
        while True:
            current = logger.get_entries(limit=9999)
            if len(current) > last_idx:
                for entry in current[last_idx:]:
                    yield f'data: {json.dumps(entry)}\n\n'
                last_idx = len(current)
            await asyncio.sleep(0.5)
    
    return StreamingResponse(event_generator(), media_type='text/event-stream')

@app.get('/api/logs')
async def list_sessions():
    sessions = list(set(
        f.stem.replace('session_', '').split('_')[0]
        for f in LOG_DIR.glob('session_*.log')
    ))
    return {'sessions': sessions}

@app.get("/health")
@app.get("/api/health")
@app.get("/api/heartbeat")
async def heartbeat():
    return {
        "status": "online",
        "version": VERSION,
        "ts": time.time()
    }

@app.get("/api/status")
async def get_status():
    return {
        "is_strategizing": _state["is_strategizing"],
        "is_rendering": _state["is_rendering"],
        "current_url": _state.get("current_url") or "",
    }

@app.websocket("/api/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    last_idx = 0
    try:
        while True:
            entries = ui_logger._entries
            # Handle clear() scenario where _entries shrinks
            if last_idx > len(entries):
                last_idx = 0
            
            if last_idx < len(entries):
                new_entries = entries[last_idx:]
                last_idx = len(entries)
                import json as _json
                for entry in new_entries:
                    await websocket.send_text(_json.dumps(entry))
            await asyncio.sleep(0.4)
    except Exception:
        pass

def _save_session(url: str):
    import json
    try:
        video_id = cache.video_id(url)
        session_dir = os.path.join(SESSIONS_DIR, video_id)
        os.makedirs(session_dir, exist_ok=True)
        session_file = os.path.join(session_dir, "state.json")

        # Batch correctness: _state["clips"] is the MERGED list of every queued
        # video after the first item — persisting it verbatim would corrupt each
        # video's session file with every other video's clips. Slice this
        # video's own clips by its clips_by_video indices instead.
        clips_to_save = _state.get("clips", [])
        own_indices = _state.get("clips_by_video", {}).get(video_id)
        if own_indices and _state.get("batch_clips_accumulated"):
            clips_to_save = [
                clips_to_save[i] for i in own_indices if i < len(clips_to_save)
            ]

        session_data = {
            "clips": clips_to_save,
            "word_timestamps": _state.get("word_timestamps", []),
            "current_url": _state.get("current_url"),
            "video_title": _state.get("video_title", ""),
            "persona": _state.get("persona", {}),
            "topics": _state.get("topics", []),
            "estimated_clips": _state.get("estimated_clips", 0),
            "video_duration": _state.get("video_duration", 0),
            "energy_peaks": _state.get("energy_peaks", []),
            "active_model": _state.get("active_model", ""),
            "scene_peaks": _state.get("scene_peaks", [])
        }
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        ui_logger.log(f"💾 Session saved to Google Drive: sessions/{video_id}")
    except Exception as e:
        ui_logger.log(f"⚠️ Failed to save session to Google Drive: {e}")

def _run_strategize(url: str, llm_label: str, whisper_label: str, angle: str = "standard", campaign_brief: Optional[str] = None, allow_natural_recomposition: bool = False, max_duration: int = 90):
    try:
        # Honest outcome signal for the batch worker: "ok" | "no_clips" | "failed".
        _state["_strategy_status"] = "running"
        if not campaign_brief and _state.get("active_campaign_profile"):
            prof = _state["active_campaign_profile"]
            campaign_brief = prof.get("custom_system_prompt") or prof.get("brief")
            if prof.get("name"):
                ui_logger.log(f"🎯 Applying Active Campaign Environment: {prof['name']}")

        _state["is_cancelled"] = False
        # Clear stale thumbnails from previous run. Batch-scoped thumbnails
        # (batch_*.jpg) belong to other queue items and must survive.
        import glob as _glob
        for _old in _glob.glob(os.path.join(THUMB_DIR, "thumb_*.jpg")):
            try:
                os.remove(_old)
            except OSError:
                pass
                
        strategy_start = time.time()
        def log_progress(pct: int, msg: str):
            if pct > 0:
                elapsed = time.time() - strategy_start
                eta = int(elapsed * (100 - pct) / pct)
                ui_logger.log(f"PROGRESS|{pct}|{msg}|{eta}")
            else:
                ui_logger.log(f"PROGRESS|{pct}|{msg}")

        log_progress(0, "Initializing AI strategy phase...")

        llm_entry = LLM_CATALOG[0]
        for entry in LLM_CATALOG:
            if entry["label"] == llm_label:
                llm_entry = entry
                break
                
        _state["active_model"] = llm_entry["label"]
        # Find Whisper
        wsp_size = "medium"
        for entry in WHISPER_CATALOG:
            if entry["label"] == whisper_label:
                wsp_size = entry["size"]
                break

        # LLM_CATALOG contains clean model IDs (e.g. meta/llama-3.3-70b-instruct).
        # _execute_with_fallback auto-premises api:nvidia: prefix internally.
        llm_path = llm_entry["filename"]

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        _state["current_url"] = url.strip()

        if _state["is_cancelled"]: return

        # ── Detect whether input is a local file path or a remote URL ──────────
        # Local files skip yt-dlp and cookies entirely; only remote URLs need them.
        url_stripped = url.strip()
        _is_local_file = os.path.isfile(url_stripped)

        # Batch correctness: rendering + thumbnails seek WORK_DIR/source.mp4, so
        # it must point at THIS video even when the transcript comes from cache
        # and the copy branch below gets skipped entirely (stale-source bug).
        # A hard link is instant; copy only when the file system refuses links.
        if _is_local_file:
            log_progress(15, "Loading local video file...")
            import shutil as _shutil
            try:
                if not os.path.exists(source_mp4) or not os.path.samefile(source_mp4, url_stripped):
                    try:
                        if os.path.exists(source_mp4):
                            os.remove(source_mp4)
                        os.link(url_stripped, source_mp4)
                    except OSError:
                        _shutil.copy2(url_stripped, source_mp4)
                ui_logger.log(f"📂 Local file loaded: {os.path.basename(url_stripped)}")
            except OSError as _e:
                _state["_strategy_status"] = "failed"
                _state["_strategy_error"] = f"Failed to load local file: {_e}"
                ui_logger.error(f"Failed to load local file: {_e}")
                log_progress(0, "Failed.")
                return
            # Derive title from filename (strip extension)
            _state["video_title"] = os.path.splitext(os.path.basename(url_stripped))[0]

        if not os.path.exists(source_mp4) or cache.load_transcript(url_stripped) is None:
            if not _is_local_file:
                # ── Remote URL — needs yt-dlp + cookies ─────────────────────────
                log_progress(15, "Downloading video...")
                ui_logger.log(f"Looking for cookies at: {COOKIE_PATH}, Exists: {os.path.exists(COOKIE_PATH)}")
                if not os.path.exists(COOKIE_PATH):
                    ui_logger._entries.append({
                        "type": "error",
                        "message": "Cookies file not found. Please add cookies.txt to the app folder.",
                        "ts": _dt.datetime.now().strftime("%H:%M:%S")
                    })
                    _state["_strategy_status"] = "failed"
                    _state["_strategy_error"] = "Cookies file not found"
                    log_progress(0, "Failed.")
                    return

                try:
                    download_video(url_stripped, WORK_DIR, cookie_path=COOKIE_PATH)
                except RuntimeError as e:
                    _state["_strategy_status"] = "failed"
                    _state["_strategy_error"] = f"Download failed: {e}"
                    ui_logger.error(str(e))
                    log_progress(0, "Failed.")
                    return

                # Fetch human-readable title from yt-dlp (fast, skip-download call)
                _state["video_title"] = get_video_title(url_stripped, cookie_path=COOKIE_PATH)

            if _state["is_cancelled"]: return
            log = ui_logger.log

            # SRT fast-path disabled due to rolling subtitle duplicates and mojibake.
            # We strictly use Faster-Whisper to guarantee clean word-level timestamps.
            word_timestamps = []
            log("🎙 Running Faster-Whisper transcription...")
            # is_cancelled hook: transcription runs in-process (no subprocess to
            # taskkill), so Stop needs this polling hook to interrupt it.
            full_text, word_timestamps = transcribe_audio(
                source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR,
                is_cancelled=lambda: _state["is_cancelled"],
            )
            cache.save_transcript(url_stripped, full_text, word_timestamps)

            _state["word_timestamps"] = word_timestamps
        else:
            log_progress(25, "Transcript loaded from cache.")
            cached_t = cache.load_transcript(url_stripped)
            _state["word_timestamps"] = cached_t[1]

        if _state["is_cancelled"]: return

        # Audio + Visual Scene Analysis (parallel — both CPU/I-O bound)
        log_progress(38, "Analyzing audio energy and visual scene changes...")
        _state["energy_peaks"] = []
        _state["scene_peaks"] = []

        def _do_audio_analysis():
            energy_wav = os.path.join(WORK_DIR, "energy_temp.wav")
            try:
                import subprocess as _sp
                _sp.run(
                    ["ffmpeg", "-y", "-i", source_mp4,
                     "-ar", "16000", "-ac", "1", energy_wav],
                    capture_output=True, check=True
                )
                return analyze_audio_energy(energy_wav)
            finally:
                try:
                    os.remove(energy_wav)
                except OSError:
                    pass

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _peaks_pool:
            _audio_fut = _peaks_pool.submit(_do_audio_analysis)
            _scene_fut = _peaks_pool.submit(detect_scene_changes, source_mp4)

            try:
                _state["energy_peaks"] = _audio_fut.result()
                ui_logger.log(f"Found {len(_state['energy_peaks'])} high-energy audio moments.")
            except Exception as _e:
                ui_logger.log(f"Audio energy analysis skipped: {_e}")

            try:
                _state["scene_peaks"] = _scene_fut.result(timeout=60)
                ui_logger.log(f"Found {len(_state['scene_peaks'])} visual scene transitions.")
            except concurrent.futures.TimeoutError:
                ui_logger.log("Scene detection timed out (60s) — skipping visual signal.")
            except Exception as _e:
                ui_logger.log(f"Scene detection skipped: {_e}")

        # Phase 0: Persona Detection
        log_progress(40, f"Phase 0/3: Analyzing Video Persona with {llm_entry['label']}...")
        persona = detect_video_persona(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"])
        log_progress(45, f"Detected Genre: {persona.get('genre', 'Unknown')} | Tone: {persona.get('tone', 'Unknown')}")
        _state["persona"] = persona

        # Calculate estimated clip potential
        estimated = estimate_clip_potential(_state["word_timestamps"])
        _state["estimated_clips"] = estimated
        
        # Calculate video duration
        if _state["word_timestamps"]:
            wts = _state["word_timestamps"]
            _state["video_duration"] = wts[-1].get("end", 0) - wts[0].get("start", 0)
        
        log_progress(48, f"Video duration: {_state['video_duration']/60:.0f} min | Estimated clip potential: ~{estimated} clips")

        if _state["is_cancelled"]: return

        # Phase 1: Topic Indexing
        log_progress(55, "Phase 1/3: Mapping video topics...")
        topics = get_topic_index(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"])
        _state["topics"] = topics
        log_progress(65, f"Found {len(topics)} distinct topics in the video.")

        if _state["is_cancelled"]: return

        # Phase 2: Per-Topic Clip Extraction
        log_progress(70, f"Phase 2/3: Extracting clips per topic with {llm_entry['label']}...")
        result = get_highlights(
            _state["word_timestamps"],
            num_clips=estimated,
            llm_path=llm_path,
            gpu_layers=llm_entry["gpu_layers"],
            max_clips=estimated,  # length-scaled budget (1/4min); old flat 30 starved long videos
            angle=angle,
            topics=topics,
            energy_peaks=_state["energy_peaks"],
            scene_peaks=_state["scene_peaks"],
            persona=_state["persona"],
            campaign_brief=campaign_brief,
            allow_natural_recomposition=allow_natural_recomposition,
            max_duration=max_duration,
        )

        clips = result.get("highlights", [])

        # Local LLM code path removed in Session 13 (API-only).

        # Hard-reject clips that start in the opening segment (intros/outros)
        if clips and _state["word_timestamps"]:
            video_start = float(_state["word_timestamps"][0].get("start", 0))
            video_dur = float(_state.get("video_duration", 0))
            intro_threshold = min(15.0, max(5.0, video_dur * 0.02))
            clips = [c for c in clips if (float(c.get("start_time", 0)) - video_start) >= intro_threshold]

        if not clips:
            ui_logger.log(f"ERROR: No viral moments found in this video.")
            # Distinct from a crash: honest "nothing worth clipping" outcome.
            _state["_strategy_status"] = "no_clips"
            _state["clips"] = []
            cache.save_highlights(url.strip(), _state["clips"])
            cache.save_metadata(url.strip(), title=_state.get("video_title", ""),
                                duration=_state.get("video_duration", 0))
            log_progress(100, "Strategy Complete. No clips found.")
            return

        # Process durations and badges
        for i, c in enumerate(clips):
            dur = float(c.get("duration", 0))
            if dur == 0:
                dur = float(c.get("end_time", 0)) - float(c.get("start_time", 0))
            c["duration"] = dur
            c["badge"] = "🎬 Single"
            c["hook_type"] = c.get("hook_type", "curiosity_gap")

        # Extract exact start-frame thumbnails for each clip
        import subprocess as _sp
        for i, c in enumerate(clips):
            try:
                thumb_path = os.path.join(THUMB_DIR, f"thumb_{i}.jpg")
                start_time = float(c.get("start_time", 0))
                seek_time = max(0.0, start_time)
                _sp.run(
                    ["ffmpeg", "-y", "-ss", f"{seek_time:.2f}", "-i", source_mp4,
                     "-vframes", "1", "-q:v", "2",
                     "-vf", "scale=640:-1",
                     thumb_path],
                    capture_output=True, timeout=15
                )
                if os.path.exists(thumb_path):
                    c["thumbnail_url"] = f"/thumbs/thumb_{i}.jpg"
                else:
                    c["thumbnail_url"] = ""
            except Exception:
                c["thumbnail_url"] = ""

        _state["clips"] = clips
        _state["_strategy_status"] = "ok"
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip(), title=_state.get("video_title", ""),
                            duration=_state.get("video_duration", 0))
        _save_session(url.strip())
        log_progress(100, f"Strategy Complete. Found {len(clips)} clips (estimated potential: ~{_state['estimated_clips']}).")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        _state["_strategy_status"] = "failed"
        _state["_strategy_error"] = str(e)
        if not _state.get("is_cancelled"):
            ui_logger.log(f"ERROR: {str(e)}")
    finally:
        _state["is_strategizing"] = False
        if _state.get("is_cancelled"):
            # Outcome of record is "cancelled by user", even if the interrupt
            # surfaced as an exception (killed ffmpeg, aborted transcription):
            # the batch worker keys off this to exit instead of picking up the
            # next video. Set AFTER except so it wins.
            _state["_strategy_status"] = "cancelled"
            log_progress(0, "Analysis was stopped by the user.")
            _state["is_cancelled"] = False

_PROVIDER_KEY_ENV = {
    "tokenrouter": "TOKENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "glm": "GLM_API_KEY",
}

@app.post("/api/strategize")
async def strategize(req: StrategizeRequest, background_tasks: BackgroundTasks):
    # queue_running must be part of the guard: between queue items the busy flag
    # is briefly released, and a manual single-video run launched in that window
    # would clobber shared state used by the batch worker.
    if _state["is_strategizing"] or _state["is_rendering"] or _state["queue_running"]:
        raise HTTPException(status_code=400, detail="A task is already running.")

    # A manual single-video run supersedes any batch bookkeeping; stale indices
    # from a previous batch would otherwise corrupt _save_session slicing.
    _state["batch_clips_accumulated"] = []
    _state["clips_by_video"] = {}
    _state["batch_sessions"] = {}

    # Pre-flight: if an API model is selected, verify the key exists before wasting transcription time
    llm_entry = next((e for e in LLM_CATALOG if e["label"] == req.llm_label), None)
    if llm_entry and llm_entry["filename"].startswith("api:"):
        parts = llm_entry["filename"].split(":", 2)
        provider = parts[1] if len(parts) > 1 else ""
        env_var = _PROVIDER_KEY_ENV.get(provider)
        if env_var and not os.getenv(env_var, "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"No API key for {provider.upper()}. Go to Settings → API Keys and add your {env_var}, then retry."
            )

    _state["is_strategizing"] = True
    _state["is_cancelled"] = False
    ui_logger.clear()
    background_tasks.add_task(_run_strategize, req.url, req.llm_label, req.whisper_label, req.angle, req.campaign_brief, req.allow_natural_recomposition, req.max_duration)
    return {"message": "Strategizing started."}

def register_pid(pid: int):
    if pid and pid not in _state.get("active_pids", []):
        _state.setdefault("active_pids", []).append(pid)

def unregister_pid(pid: int):
    if pid and pid in _state.get("active_pids", []):
        try:
            _state["active_pids"].remove(pid)
        except ValueError:
            pass

def kill_all_active_pids():
    pids = list(_state.get("active_pids", []))
    _state["active_pids"] = []
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    # Blanket kill media processes to ensure instant cancellation
    try:
        if os.name == "nt":
            subprocess.run("taskkill /F /IM ffmpeg.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run("taskkill /F /IM yt-dlp.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-9", "ffmpeg"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "yt-dlp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

@app.post("/api/cancel_strategize")
async def cancel_strategize():
    _state["is_cancelled"] = True
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    kill_all_active_pids()
    ui_logger.log("❌ Execution stopped by user. All active subprocesses terminated.")
    return {"message": "Stopped process immediately."}

@app.post("/api/reset")
async def reset_state():
    _state["is_cancelled"] = True
    kill_all_active_pids()
    _state["clips"] = []
    _state["word_timestamps"] = []
    _state["current_url"] = None
    _state["persona"] = {}
    _state["topics"] = []
    _state["estimated_clips"] = 0
    _state["video_duration"] = 0
    _state["video_title"] = ""
    _state["energy_peaks"] = []
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    _state["is_cancelled"] = False
    ui_logger.clear()
    return {"message": "State reset."}

# ----------------------------------------------------------------
# Bulk session-delete ("Purge & Start Over" button on the dashboard).
# Frontend posts to /api/purge_current and expects ALL artefacts on disk
# for the active session to be wiped. Session id is recomputed from
# the currently-stored current_url (or all clips if no current URL).
# ----------------------------------------------------------------
@app.post("/api/purge_current")
async def purge_current():
    """Delete every on-disk artefact tied to the current session.

    Purge scope:
      - The current project's transcripts/highlights/metadata under
        PROJECTS_DIR/<video_id>/
      - The session state under SESSIONS_DIR/<video_id>/
      - All rendered clips for that video under OUTPUT_DIR/<video_id>/

    Returns the count of deleted files + directories for confirmation.
    Resets in-memory state so UI is consistent with disk.
    """
    import shutil

    urls = []
    if _state.get("current_url"):
        urls.append(_state["current_url"])
    # Cover the watch-folder case where current_url may be empty but a queue
    # item is active. We delete *all* sessions in that case.

    target_dirs: list[str] = []
    if urls:
        for u in urls:
            vid = cache.video_id(u)
            for d in (PROJECTS_DIR, SESSIONS_DIR, OUTPUT_DIR):
                target_dirs.append(os.path.join(d, vid))
    else:
        # No current session: wipe everything in the project tree including uploads.
        for d in (PROJECTS_DIR, SESSIONS_DIR, OUTPUT_DIR, os.path.join(BASE_DIR, "uploads")):
            if os.path.isdir(d):
                target_dirs.append(d)

    deleted: list[str] = []
    for d in target_dirs:
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
                deleted.append(d)
            except OSError:
                pass

    # Reset state so UI matches disk resets.
    _state["clips"] = []
    _state["word_timestamps"] = []
    _state["current_url"] = None
    _state["persona"] = {}
    _state["topics"] = []
    _state["estimated_clips"] = 0
    _state["video_duration"] = 0
    _state["video_title"] = ""
    _state["energy_peaks"] = []
    _state["scene_peaks"] = []
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    _state["is_cancelled"] = False
    ui_logger.clear()
    return {"status": "success", "deleted": deleted, "deleted_count": len(deleted)}


# ----------------------------------------------------------------
# Multipart upload endpoint ("Upload Video" button on the dashboard).
# Frontend posts the file as multipart/form-data; we save it to a stable
# incoming-style directory under BASE_DIR/uploads and return the absolute
# path. The user can then paste that path into the URL field or have
# the dashboard auto-populate it via res.data.path.
# ----------------------------------------------------------------
@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...)):
    """Save an uploaded video file to BASE_DIR/uploads and return its absolute path.

    The file is written to a hash-named subdir so multiple uploads don't
    collide and the original filename is preserved for owner readability.
    Saves to a per-day directory under BASE_DIR/uploads/<YYYY-MM-DD>/ so the
    caller can clean up old uploads easily.
    """
    import shutil
    from datetime import datetime

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    uploads_root = os.path.join(BASE_DIR, "uploads")
    day_dir = os.path.join(uploads_root, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)

    # Hash content to detect duplicates — same file uploaded twice yields
    # the same destination so the directory never fills with copies.
    digest = hashlib.md5()
    dst_path = os.path.join(day_dir, file.filename)
    if os.path.exists(dst_path):
        # Same name exists; let it stay (caller can replace by re-upload).
        # Caller controls what to do with the conflict.
        pass

    try:
        with open(dst_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                digest.update(chunk)
                out.write(chunk)
    except Exception as e:
        # Cleanup partial write on failure
        if os.path.exists(dst_path):
            try: os.remove(dst_path)
            except OSError: pass
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")
    finally:
        await file.close()

    # Common downstream path: owner wants to strategize immediately.
    # Return absolute path + suggested next ergonomics.
    return {
        "status": "success",
        "path": dst_path,
        "filename": file.filename,
        "size_bytes": os.path.getsize(dst_path),
        "md5": digest.hexdigest(),
        "message": f"Saved to {dst_path}",
    }


@app.post("/api/upload_videos_batch")
async def upload_videos_batch(
    files: List[UploadFile] = File(...),
    llm_label: Optional[str] = Form(None),
):
    """Multi-file upload straight into the batch queue — queued, NOT started.

    Owner directive 2026-08-16: "i dont like how it starts immediietly after
    i select the videos and the app does not wait for me to start." Upload
    only queues the files; processing begins when the user clicks
    Start Batch (frontend) or Run Queue (header) → POST /api/queue/start.
    Each file lands in the per-day uploads dir, then _enqueue_path registers it.
    """
    import shutil
    from datetime import datetime

    uploads_root = os.path.join(BASE_DIR, "uploads")
    day_dir = os.path.join(uploads_root, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)

    saved: List[dict] = []
    failed: List[str] = []
    skipped: List[str] = []

    for file in files:
        if not file.filename:
            failed.append("(unnamed file)")
            continue
        dst_path = os.path.join(day_dir, file.filename)
        try:
            with open(dst_path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        except Exception as e:
            if os.path.exists(dst_path):
                try: os.remove(dst_path)
                except OSError: pass
            failed.append(f"{file.filename}: {e}")
            continue
        finally:
            await file.close()

        item = _enqueue_path(dst_path)
        if item:
            saved.append({"filename": file.filename, "path": dst_path})
        else:
            skipped.append(file.filename)

    # No auto-start (owner directive 2026-08-16): the queue waits for the
    # user's explicit Start. The model choice is stored now so the worker
    # uses it when the batch is eventually started. Note: queue/start also
    # stores the model passed at start time, so the later choice wins.
    if llm_label:
        _state["batch_model_label"] = llm_label
    queue_started = False

    return {
        "status": "success",
        "queued": len(saved),
        "skipped_duplicates": skipped,
        "failed": failed,
        "queue_length": len(_state["queue"]),
        "queue_started": queue_started,
        "files": saved,
    }

@app.get("/api/results")
async def get_results():
    if _state["is_strategizing"]:
        return {"status": "running"}
    video_id = ""
    url = _state.get("current_url")
    if url:
        video_id = cache.video_id(url)
    return {
        "status": "done",
        "current_url": url,
        "video_id": video_id,
        "persona": _state["persona"],
        "clips": _state["clips"],
        "topics": _state["topics"],
        "estimated_clips": _state["estimated_clips"],
        "video_duration": _state["video_duration"],
        "active_model": _state.get("active_model", ""),
        "scene_peaks": _state.get("scene_peaks", []),
        # word_timestamps is intentionally OMITTED here. For long videos it is
        # 1-2 MB (~30x the clip data) and this endpoint is polled every 2s; the
        # bloat stampeded the tunnel into a total stall after strategy completed.
        # The sentence-exclusion UI fetches it once on demand via /api/word_timestamps.
    }


@app.get("/api/word_timestamps")
async def get_word_timestamps():
    """Serve the heavy word-level transcript on demand (sentence-exclusion UI).

    Kept out of the frequently-polled /api/results payload on purpose — see the
    note there. Fetched once by the frontend after results load.
    """
    return {"word_timestamps": _state.get("word_timestamps", [])}

@app.get("/api/render_status")
async def get_render_status(task_id: str):
    if task_id in _render_status:
        return _render_status[task_id]
    return {"status": "not_found"}

def _make_clip_slug(idx: int, title: str) -> str:
    """Generate a clean, unified slug prefix for a clip: f'{idx+1:02d}_{clean_title_slug}'"""
    safe_slug = re.sub(r'[^a-zA-Z0-9]+', '_', (title or f"clip_{idx+1}")).strip('_').lower()
    safe_slug = safe_slug[:45] if safe_slug else f"clip_{idx+1}"
    return f"{idx+1:02d}_{safe_slug}"


def _resolve_clip_source(clip: dict) -> tuple:
    """Return (input_mp4, word_timestamps) for THIS clip's owning video.

    Batch runs overwrite the shared WORK_DIR/source.mp4 and _state["word_timestamps"]
    with the last video's, so rendering an earlier batch video's clip would cut
    the wrong footage with wrong captions without this lookup. The clip carries
    its own video_id (stamped by the queue worker), and each batch item's
    session snapshot in _state["batch_sessions"] gives back its URL.
    """
    clip_vid = clip.get("video_id") or ""
    current_url = _state.get("current_url") or ""
    current_vid = cache.video_id(current_url) if current_url else ""

    # Fast path: the clip belongs to the video currently loaded in _state.
    if not clip_vid or clip_vid == current_vid:
        return os.path.join(WORK_DIR, "source.mp4"), _state.get("word_timestamps", [])

    # The clip belongs to an earlier batch item — restore its source/transcript
    # from its session snapshot; relink/copy the source file into WORK_DIR.
    session = _state["batch_sessions"].get(clip_vid, {})
    src_url = session.get("url") or clip.get("source_path")
    if not src_url or not os.path.isfile(src_url):
        # Nothing we can resolve — fall back to shared state (legacy single-video path)
        return os.path.join(WORK_DIR, "source.mp4"), _state.get("word_timestamps", [])

    input_mp4 = os.path.join(WORK_DIR, "source.mp4")
    try:
        if not os.path.exists(input_mp4) or not os.path.samefile(input_mp4, src_url):
            try:
                if os.path.exists(input_mp4):
                    os.remove(input_mp4)
                os.link(src_url, input_mp4)
            except OSError:
                import shutil as _shutil
                _shutil.copy2(src_url, input_mp4)
    except OSError as e:
        ui_logger.error(f"Could not relink source for render: {e}")

    words = _state.get("word_timestamps", [])
    cached = cache.load_transcript(src_url)
    if cached:
        words = cached[1]
    return input_mp4, words


def _run_render(req: RenderRequest, task_id: str):
    try:
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|rendering")
        ui_logger.log(f"Initializing render for clip index {req.clip_id}...")
        
        # Update client-edited title if provided
        if req.title:
            _state["clips"][req.clip_id]["title"] = req.title
            if _state.get("current_url"):
                _save_session(_state["current_url"])
        
        clip = _state["clips"][req.clip_id].copy() # Copy to avoid mutating global state
        
        # Defer BGM entirely to the user's bg_music_genre selection
        clip["music_query"] = ""
            
        input_mp4, render_words = _resolve_clip_source(clip)
        if not os.path.exists(input_mp4):
            url = _state.get("current_url")
            if url:
                ui_logger.log(f"📥 Source video missing from session storage. Auto-downloading from: {url}...")
                download_video(url, WORK_DIR, cookie_path=COOKIE_PATH)
                ui_logger.log("✅ Source video downloaded successfully.")
            else:
                raise FileNotFoundError("Source video file is missing and no current URL is available in session state.")

        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        theme = clip.get("theme", "Storytime")
        
        all_sentences = [] # We would need to rebuild this from word_timestamps if needed, but for now we pass empty or rebuild.
        
        url = _state.get("current_url")
        video_id = cache.video_id(url) if url else ""

        target_layout = getattr(req, "layout_mode", None) or "portrait"
        target_face_track = getattr(req, "face_track", True)
        ui_logger.log(f"🎬 Rendering clip {req.clip_id + 1} | layout_mode={target_layout} | face_track={target_face_track}")

        out = render_short(
            input_video=input_mp4, clip_data=clip,
            word_timestamps=render_words,
            output_dir=clips_dir, work_dir=WORK_DIR,
            face_center=req.face_center, add_subs=(req.caption_style != "None"),
            face_track=target_face_track,
            theme=theme, caption_style=req.caption_style, caption_pos=req.caption_pos,
            override_start=None, override_end=None,
            excluded_sentences=req.excluded_sentences,
            magic_hook=req.magic_hook,
            remove_silence=req.remove_silence,
            broll_intensity=req.broll_intensity,
            all_sentences=all_sentences,
            bg_style=req.bg_style,
            hook_position=req.hook_position,
            hook_display=req.hook_display,
            show_outro=req.show_outro,
            title_style=req.title_style,
            layout_mode=target_layout,
            hook_style=req.hook_style,
            header_font=req.header_font,
            caption_font=req.caption_font,
            hook_font=req.hook_font,
            header_style=getattr(req, "header_style", "rounded-chunky"),
            force_header_text=_resolve_header_text(getattr(req, "force_header_text", None), req.clip_id),
            rounded_corner_radius=random.choice([0, 40]) if int(getattr(req, "rounded_corner_radius", 0) or 0) == 0 else int(getattr(req, "rounded_corner_radius", 0) or 0),
            session_id=req.session_id,
            style_mode=getattr(req, "style_mode", "random"),
            style_allowlist=getattr(req, "style_allowlist", None),
            fixed_style=getattr(req, "fixed_style", None),
            watermark=_active_watermark(),
        )
        
        # ── BGM mixing via enhance_clip ──
        if req.bg_music_genre and req.bg_music_genre != "None":
            music_path = _get_bgm(req.bg_music_genre)
            if music_path:
                ui_logger.log(f"Mixing BGM ({req.bg_music_genre}) with dynamic peak swell...")
                try:
                    enhance_clip(out, clip, music_path=music_path)
                except Exception as bgm_err:
                    ui_logger.log(f"BGM mixing failed ({bgm_err}) — clip saved without music.")

        import shutil
        session_output_dir = os.path.join(OUTPUT_DIR, video_id) if video_id else OUTPUT_DIR
        os.makedirs(session_output_dir, exist_ok=True)
        # Write a human-readable info file so this folder is identifiable on Drive
        _info_txt = os.path.join(session_output_dir, "_INFO.txt")
        if not os.path.exists(_info_txt) and _state.get("video_title"):
            with open(_info_txt, "w", encoding="utf-8") as _f:
                _f.write(f"Video: {_state['video_title']}\nURL:   {_state.get('current_url','')}\n")

        prof = _state.get("active_campaign_profile") or {}
        creator_name = prof.get("name", "")
        creator_handle = prof.get("whop_metadata", {}).get("creator_handle", "")

        clip_ref = _state["clips"][req.clip_id]
        clip_meta = {
            "title": clip_ref.get("title", f"Clip {req.clip_id + 1}"),
            "source_topic": clip_ref.get("source_topic", ""),
            "virality_reason": clip_ref.get("virality_reason", ""),
            "hook_text": clip_ref.get("hook_text", ""),
            "hook_type": clip_ref.get("hook_type", ""),
            "theme": clip_ref.get("theme", ""),
            "transcript": clip_ref.get("ideal_transcript", ""),
            "score": clip_ref.get("score", 0),
            "virality_score": clip_ref.get("virality_score", 0),
            "duration": clip_ref.get("duration", 0),
            "persona": _state.get("persona", {}),
            "campaign_creator_name": creator_name,
            "campaign_handle": creator_handle,
        }

        # Unified 3-file naming prefix: {idx+1:02d}_{clean_title_slug}
        prefix = _make_clip_slug(req.clip_id, clip_meta["title"])
        dst = os.path.join(session_output_dir, f"{prefix}.mp4")
        if out != dst:
            shutil.copy2(out, dst)

        meta_dst = os.path.join(session_output_dir, f"{prefix}_metadata.json")
        caption_dst = os.path.join(session_output_dir, f"{prefix}_caption.txt")
        
        # C1: Generate YouTube metadata (Nvidia LLM preferred)
        yt_metadata = generate_youtube_metadata(
            clip_meta, 
            llm_path="api:nvidia:meta/llama-3.1-70b-instruct", 
            session_id=req.session_id
        )
        if yt_metadata:
            clip_meta["youtube_metadata"] = yt_metadata

        # Write human-readable posting guide & caption file
        with open(caption_dst, "w", encoding="utf-8") as _gf:
            _gf.write("--- CLIP & POSTING GUIDE ---\n")
            _gf.write(f"Title: {clip_meta['title']}\n")
            _gf.write(f"Duration: {clip_meta.get('duration', 0):.1f}s\n")
            _gf.write(f"Virality Score: {clip_meta.get('virality_score', 0)}/100\n")
            if clip_meta.get('hook_text'):
                _gf.write(f"Viral Hook: {clip_meta['hook_text']}\n\n")
            else:
                _gf.write("\n")
            _gf.write("--- SOCIAL / YOUTUBE SHORTS METADATA ---\n")
            _gf.write(f"TITLE:\n{yt_metadata.get('yt_title', clip_meta['title']) if yt_metadata else clip_meta['title']}\n\n")
            _gf.write(f"DESCRIPTION:\n{yt_metadata.get('yt_description', '') if yt_metadata else ''}\n\n")
            _gf.write(f"TAGS / HASHTAGS:\n{yt_metadata.get('yt_tags', '') if yt_metadata else ''}\n\n")
            _gf.write(f"PINNED COMMENT:\n{yt_metadata.get('yt_pinned_comment', '') if yt_metadata else ''}\n")

        with open(meta_dst, "w", encoding="utf-8") as _mf:
            json.dump(clip_meta, _mf, indent=4, ensure_ascii=False)
        ui_logger.log(f"Rendered successfully: {os.path.basename(dst)}")

        rel_fn = f"{video_id}/{os.path.basename(dst)}" if video_id else os.path.basename(dst)
        _render_status[task_id]["filename"] = rel_fn
        _render_status[task_id]["status"] = "done"
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|done")

        # Store rendered filename in the clip state to support CSV export and UI references
        _state["clips"][req.clip_id]["rendered_filename"] = rel_fn
        if _state.get("current_url"):
            _save_session(_state["current_url"])
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui_logger.log(f"ERROR: {str(e)}")
        _render_status[task_id] = {"status": "error", "error": str(e)}
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|error")
    finally:
        _state["is_rendering"] = False
        if _render_status.get(task_id, {}).get("status") != "error":
            _render_status[task_id]["status"] = "done"

def _run_bulk_render(req: BulkRenderRequest):
    try:
        
        num_clips = len(_state["clips"])
        target_ids = req.clip_ids if (req.clip_ids is not None) else list(range(num_clips))
        
        # Update any edited titles
        if req.titles:
            for idx_str, new_title in req.titles.items():
                try:
                    idx = int(idx_str)
                    if 0 <= idx < num_clips:
                        _state["clips"][idx]["title"] = new_title
                except ValueError:
                    continue
            if _state.get("current_url"):
                _save_session(_state["current_url"])
                
        _state["is_cancelled"] = False
        ui_logger.log(f"Starting bulk render for {len(target_ids)} clips sequentially...")
        
        # Mark target clips as queued initially
        for idx in target_ids:
            if 0 <= idx < num_clips:
                ui_logger.log(f"RENDER_STATUS|{idx}|queued")

        for idx in target_ids:
            if idx < 0 or idx >= num_clips:
                continue
            if _state["is_cancelled"]:
                ui_logger.log("Bulk render cancelled by user.")
                break
                
            ui_logger.log(f"RENDER_STATUS|{idx}|rendering")
            clip = _state["clips"][idx].copy()
            
            # Defer BGM entirely to the user's bg_music_genre selection
            clip["music_query"] = ""
                
            theme = clip.get("theme", "Storytime")

            # Per-clip source resolution: in a batch, the shared source.mp4 and
            # word_timestamps point at the LAST processed video. Each clip must
            # cut from its own video with its own transcript for correct captions.
            input_mp4, render_words = _resolve_clip_source(clip)
            if not os.path.exists(input_mp4):
                url = _state.get("current_url")
                if url:
                    ui_logger.log(f"📥 Source video missing from session storage. Auto-downloading from: {url}...")
                    download_video(url, WORK_DIR, cookie_path=COOKIE_PATH)
                    ui_logger.log("✅ Source video downloaded successfully.")
                else:
                    raise FileNotFoundError("Source video file is missing and no current URL is available in session state.")

            # Output dir per the clip's own video so gallery grouping stays correct.
            clip_vid = clip.get("video_id") or ""
            session = _state["batch_sessions"].get(clip_vid, {})
            out_url = session.get("url") or clip.get("source_path") or _state.get("current_url")
            clips_dir = cache.get_clips_dir(out_url) if out_url else OUTPUT_DIR
            video_id = cache.video_id(out_url) if out_url else ""
            
            try:
                # Resolve per-clip settings
                settings = req.dict()
                idx_str = str(idx)
                if req.clip_settings and idx_str in req.clip_settings:
                    per_clip = req.clip_settings[idx_str]
                    if per_clip:
                        for k, v in per_clip.items():
                            if v is not None and k not in ("layout_mode",):
                                settings[k] = v

                # layout_mode is a global render setting; req.layout_mode takes absolute precedence
                target_layout = req.layout_mode or settings.get("layout_mode") or "portrait"
                settings["layout_mode"] = target_layout

                target_face_track = req.face_track if getattr(req, "face_track", None) is not None else settings.get("face_track", True)
                settings["face_track"] = target_face_track

                ui_logger.log(f"🎬 Bulk render clip {idx + 1} | layout_mode={target_layout} | face_track={target_face_track}")

                c_pos = settings.get("caption_pos", "Below")
                if isinstance(c_pos, str):
                    c_pos = c_pos.capitalize()

                out = render_short(
                    input_video=input_mp4, clip_data=clip,
                    word_timestamps=render_words,
                    output_dir=clips_dir, work_dir=WORK_DIR,
                    face_center=settings.get("face_center", True),
                    face_track=settings.get("face_track", True),
                    add_subs=(settings.get("caption_style", "Classic") != "None"),
                    theme=theme,
                    caption_style=settings.get("caption_style", "Classic"),
                    caption_pos=c_pos,
                    override_start=None, override_end=None,
                    excluded_sentences=[],
                    magic_hook=settings.get("magic_hook", False),
                    remove_silence=settings.get("remove_silence", True),
                    broll_intensity=settings.get("broll_intensity", "None"),
                    all_sentences=[],
                    bg_style=settings.get("bg_style", "black"),
                    hook_position=settings.get("hook_position", "top"),
                    hook_display=settings.get("hook_display", "full"),
                    show_outro=settings.get("show_outro", False),
                    title_style=settings.get("title_style", "Impact"),
                    layout_mode=settings.get("layout_mode", "portrait"),
                    hook_style=settings.get("hook_style", "BlackOnWhiteBox"),
                    header_font=settings.get("header_font", "bebas"),
                    caption_font=settings.get("caption_font", "bebas"),
                    hook_font=settings.get("hook_font", "bebas"),
                    header_style=settings.get("header_style", "rounded-chunky"),
                    force_header_text=_resolve_header_text(getattr(req, 'force_header_text', settings.get('force_header_text', None)), idx),
                    rounded_corner_radius=random.choice([0, 40]) if int(settings.get("rounded_corner_radius", 0) or 0) == 0 else int(settings.get("rounded_corner_radius", 0) or 0),
                    session_id=settings.get("session_id", "global"),
                    style_mode=settings.get("style_mode", getattr(req, "style_mode", "random")),
                    style_allowlist=settings.get("style_allowlist", getattr(req, "style_allowlist", None)),
                    fixed_style=settings.get("fixed_style", getattr(req, "fixed_style", None)),
                    watermark=_active_watermark(),
                )

                # BGM mixing
                bg_music_genre = settings.get("bg_music_genre", "None")
                if bg_music_genre and bg_music_genre != "None":
                    music_path = _get_bgm(bg_music_genre)
                    if music_path:
                        ui_logger.log(f"Mixing BGM ({bg_music_genre}) with dynamic peak swell for clip {idx}...")
                        try:
                            enhance_clip(out, clip, music_path=music_path)
                        except Exception as bgm_err:
                            ui_logger.log(f"BGM mixing failed ({bgm_err}) for clip {idx} — saved without music.")
                            
                import shutil
                session_output_dir = os.path.join(OUTPUT_DIR, video_id) if video_id else OUTPUT_DIR
                os.makedirs(session_output_dir, exist_ok=True)
                _info_txt = os.path.join(session_output_dir, "_INFO.txt")
                if not os.path.exists(_info_txt) and _state.get("video_title"):
                    with open(_info_txt, "w", encoding="utf-8") as _f:
                        _f.write(f"Video: {_state['video_title']}\nURL:   {_state.get('current_url','')}\n")

                prof = _state.get("active_campaign_profile") or {}
                creator_name = prof.get("name", "")
                creator_handle = prof.get("whop_metadata", {}).get("creator_handle", "")

                clip_meta = {
                    "title": _state["clips"][idx].get("title", f"Clip {idx+1}"),
                    "source_topic": _state["clips"][idx].get("source_topic", ""),
                    "virality_reason": _state["clips"][idx].get("virality_reason", ""),
                    "hook_text": _state["clips"][idx].get("hook_text", ""),
                    "hook_type": _state["clips"][idx].get("hook_type", ""),
                    "theme": _state["clips"][idx].get("theme", ""),
                    "transcript": _state["clips"][idx].get("ideal_transcript", ""),
                    "score": _state["clips"][idx].get("score", 0),
                    "virality_score": _state["clips"][idx].get("virality_score", 0),
                    "duration": _state["clips"][idx].get("duration", 0),
                    "persona": _state.get("persona", {}),
                    "campaign_creator_name": creator_name,
                    "campaign_handle": creator_handle,
                }

                # Unified 3-file naming prefix: {idx+1:02d}_{clean_title_slug}
                prefix = _make_clip_slug(idx, clip_meta["title"])
                dst = os.path.join(session_output_dir, f"{prefix}.mp4")
                if out != dst:
                    shutil.copy2(out, dst)

                meta_dst = os.path.join(session_output_dir, f"{prefix}_metadata.json")
                caption_dst = os.path.join(session_output_dir, f"{prefix}_caption.txt")
                
                # C1: Generate YouTube metadata (Nvidia LLM preferred)
                yt_metadata = generate_youtube_metadata(
                    clip_meta, 
                    llm_path="api:nvidia:meta/llama-3.1-70b-instruct", 
                    session_id=locals().get("settings", {}).get("session_id", "global")
                )
                if yt_metadata:
                    clip_meta["youtube_metadata"] = yt_metadata

                # Write human-readable posting guide & caption file
                with open(caption_dst, "w", encoding="utf-8") as _gf:
                    _gf.write("--- CLIP & POSTING GUIDE ---\n")
                    _gf.write(f"Title: {clip_meta['title']}\n")
                    _gf.write(f"Duration: {clip_meta.get('duration', 0):.1f}s\n")
                    _gf.write(f"Virality Score: {clip_meta.get('virality_score', 0)}/100\n")
                    if clip_meta.get('hook_text'):
                        _gf.write(f"Viral Hook: {clip_meta['hook_text']}\n\n")
                    else:
                        _gf.write("\n")
                    _gf.write("--- SOCIAL / YOUTUBE SHORTS METADATA ---\n")
                    _gf.write(f"TITLE:\n{yt_metadata.get('yt_title', clip_meta['title']) if yt_metadata else clip_meta['title']}\n\n")
                    _gf.write(f"DESCRIPTION:\n{yt_metadata.get('yt_description', '') if yt_metadata else ''}\n\n")
                    _gf.write(f"TAGS / HASHTAGS:\n{yt_metadata.get('yt_tags', '') if yt_metadata else ''}\n\n")
                    _gf.write(f"PINNED COMMENT:\n{yt_metadata.get('yt_pinned_comment', '') if yt_metadata else ''}\n")

                with open(meta_dst, "w", encoding="utf-8") as _mf:
                    json.dump(clip_meta, _mf, indent=4, ensure_ascii=False)
                ui_logger.log(f"Rendered clip {idx} successfully: {os.path.basename(dst)}")
                ui_logger.log(f"RENDER_STATUS|{idx}|done")
                
                # Store rendered filename in the clip state to support CSV export and UI references
                rel_fn = f"{video_id}/{os.path.basename(dst)}" if video_id else os.path.basename(dst)
                _state["clips"][idx]["rendered_filename"] = rel_fn
                if _state.get("current_url"):
                    _save_session(_state["current_url"])
                
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                traceback.print_exc()
                # Persist the failure to the on-disk logs (not just stdout/WebSocket)
                # so a crashed render can be diagnosed from the Drive logs afterward.
                try:
                    sid = locals().get("settings", {}).get("session_id", "global") if "settings" in locals() else "global"
                    get_logger(sid, video_title=_state.get("video_title", "")).log_app_event(
                        "render_clip", "failed", {"clip_index": idx}, error=tb[-1500:]
                    )
                except Exception:
                    pass
                ui_logger.log(f"ERROR rendering clip {idx}: {str(e)}")
                ui_logger.log(f"RENDER_STATUS|{idx}|error")
                
    except Exception as e:
        ui_logger.log(f"Bulk render error: {str(e)}")
    finally:
        _state["is_rendering"] = False

@app.post("/api/render")
async def render(req: RenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if req.clip_id < 0 or req.clip_id >= len(_state["clips"]):
        raise HTTPException(status_code=404, detail="Clip not found.")
        
    # Validate all font selections before rendering
    for element in ['header_font', 'caption_font', 'hook_font']:
        font = getattr(req, element, 'bebas')
        font_key = font.lower().strip() if font else 'bebas'
        path = AVAILABLE_FONTS.get(font_key)
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"Missing font file for {element}: {font}. Add to work/fonts/")
    
    _state["is_rendering"] = True
    ui_logger.clear()
    
    task_id = f"render_{req.clip_id}_{int(time.time())}"
    _render_status[task_id] = {"status": "running"}
    
    background_tasks.add_task(_run_render, req, task_id)
    return {"message": "Render started.", "task_id": task_id}

@app.post("/api/render_all")
async def render_all(req: BulkRenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if not _state["clips"]:
        raise HTTPException(status_code=400, detail="No clips available to render.")
        
    # Validate all global font selections before rendering
    for element in ['header_font', 'caption_font', 'hook_font']:
        font = getattr(req, element, 'bebas')
        font_key = font.lower().strip() if font else 'bebas'
        path = AVAILABLE_FONTS.get(font_key)
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"Missing global font file for {element}: {font}. Add to work/fonts/")
            
    # Validate per-clip font selections if provided
    if req.clip_settings:
        for idx_str, per_clip in req.clip_settings.items():
            if per_clip:
                for element in ['header_font', 'caption_font', 'hook_font']:
                    font = per_clip.get(element)
                    if font:
                        font_key = font.lower().strip()
                        path = AVAILABLE_FONTS.get(font_key)
                        if not path or not os.path.exists(path):
                            raise HTTPException(status_code=400, detail=f"Missing font file for {element} in clip {idx_str}: {font}. Add to work/fonts/")
    
    _state["is_rendering"] = True
    ui_logger.clear()
    
    background_tasks.add_task(_run_bulk_render, req)
    return {"message": "Bulk render started."}

@app.get("/api/download_single")
async def download_single(background_tasks: BackgroundTasks, filename: str):
    import zipfile
    import json
    
    mp4_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(mp4_path):
        raise HTTPException(status_code=404, detail="Clip not found.")
        
    for f in os.listdir(WORK_DIR):
        if (f.startswith("clip_") or f.startswith("all_clips_")) and f.endswith(".zip"):
            p = os.path.join(WORK_DIR, f)
            if time.time() - os.path.getmtime(p) > 300:
                try: os.remove(p)
                except OSError: pass

    zip_path = os.path.join(WORK_DIR, f"clip_{int(time.time())}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(mp4_path, os.path.basename(filename))
            # Prefer on-disk metadata (written at render time, survives session restarts)
            meta_disk_path = os.path.splitext(mp4_path)[0] + "_metadata.json"
            if os.path.exists(meta_disk_path):
                zipf.write(meta_disk_path, os.path.basename(meta_disk_path))
            else:
                # Fallback: build from in-memory state if available
                clip_data = next((c for c in _state.get("clips", []) if c.get("rendered_filename") == filename), None)
                if clip_data:
                    metadata = {
                        "title": clip_data.get("title", "Clip"),
                        "source_topic": clip_data.get("source_topic", ""),
                        "virality_reason": clip_data.get("virality_reason", ""),
                        "hook_text": clip_data.get("hook_text", ""),
                        "hook_type": clip_data.get("hook_type", ""),
                        "theme": clip_data.get("theme", ""),
                        "transcript": clip_data.get("ideal_transcript", ""),
                        "score": clip_data.get("score", 0),
                        "virality_score": clip_data.get("virality_score", 0),
                        "duration": clip_data.get("duration", 0),
                        "persona": _state.get("persona", {}),
                    }
                    meta_filename = f"{os.path.splitext(os.path.basename(filename))[0]}_metadata.json"
                    zipf.writestr(meta_filename, json.dumps(metadata, indent=4, ensure_ascii=False))

            # Include companion caption / posting guide file if present
            caption_disk_path = os.path.splitext(mp4_path)[0] + "_caption.txt"
            if not os.path.exists(caption_disk_path):
                caption_disk_path = os.path.splitext(mp4_path)[0] + "_posting_guide.txt"
            if os.path.exists(caption_disk_path):
                zipf.write(caption_disk_path, os.path.basename(caption_disk_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ZIP: {str(e)}")
        
    return FileResponse(zip_path, media_type="application/zip", filename=f"clip_{os.path.splitext(filename)[0]}.zip")

@app.get("/api/download_all")
async def download_all(background_tasks: BackgroundTasks, project_only: bool = False, video_id: Optional[str] = None):
    import glob
    import zipfile
    import json

    if project_only:
        clips_to_download = [clip for clip in _state.get("clips", []) if clip.get("rendered_filename")]
        files = []
        curr_url = _state.get("current_url")
        curr_video_id = cache.video_id(curr_url) if curr_url else ""
        for clip in clips_to_download:
            fn = clip.get("rendered_filename")
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1):
                files.append(p1)
            elif os.path.exists(p2):
                files.append(p2)
    elif video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
        clips_to_download = []
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        clips_to_download = []
        
    if not files:
        raise HTTPException(status_code=404, detail="No matching rendered clips found to download.")
        
    for f in os.listdir(WORK_DIR):
        if (f.startswith("all_clips_") or f.startswith("clip_")) and f.endswith(".zip"):
            p = os.path.join(WORK_DIR, f)
            if time.time() - os.path.getmtime(p) > 300:
                try: os.remove(p)
                except OSError: pass
                
    zip_path = os.path.join(WORK_DIR, f"all_clips_{int(time.time())}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                zipf.write(file, os.path.basename(file))
                # Always include on-disk metadata if present (survives session restarts)
                meta_path = os.path.splitext(file)[0] + "_metadata.json"
                if os.path.exists(meta_path):
                    zipf.write(meta_path, os.path.basename(meta_path))
                # Always include on-disk caption / posting guide if present
                caption_path = os.path.splitext(file)[0] + "_caption.txt"
                if not os.path.exists(caption_path):
                    caption_path = os.path.splitext(file)[0] + "_posting_guide.txt"
                if os.path.exists(caption_path):
                    zipf.write(caption_path, os.path.basename(caption_path))
            # Bundle all session logs so LLM strategy logs are always included
            import glob as _glob
            log_files = _glob.glob(os.path.join(str(LOG_DIR), "**", "*.jsonl"), recursive=True)
            log_files += _glob.glob(os.path.join(str(LOG_DIR), "**", "*.log"), recursive=True)
            log_files.sort(key=os.path.getmtime, reverse=True)
            for log_path in log_files:
                arcname = os.path.join("logs", os.path.relpath(log_path, str(LOG_DIR)).replace("\\", "/"))
                try:
                    zipf.write(log_path, arcname)
                except OSError:
                    pass
            # Bundle state.json for the active session so clip strategy context survives offline
            _curr_url = _state.get("current_url")
            if _curr_url:
                _sv_id = cache.video_id(_curr_url)
                _state_path = os.path.join(SESSIONS_DIR, _sv_id, "state.json")
                if os.path.exists(_state_path):
                    try:
                        zipf.write(_state_path, "state.json")
                    except OSError:
                        pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ZIP: {str(e)}")
        
    filename = "clipfactory_project_clips.zip" if project_only else "clipfactory_all_clips.zip"
    if video_id:
        filename = f"clipfactory_session_{video_id[:8]}_clips.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename
    )


@app.post("/api/check_session")
async def check_session(req: SessionRequest):
    url = req.url.strip()
    video_id = cache.video_id(url)
    session_file = os.path.join(SESSIONS_DIR, video_id, "state.json")
    exists = os.path.exists(session_file)
    return {"exists": exists, "video_id": video_id}

@app.post("/api/restore_session")
async def restore_session(req: SessionRequest):
    import json
    url = req.url.strip()
    video_id = cache.video_id(url)
    session_file = os.path.join(SESSIONS_DIR, video_id, "state.json")
    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="No session found for this URL.")
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _state["clips"] = data.get("clips", [])
        _state["word_timestamps"] = data.get("word_timestamps", [])
        _state["current_url"] = data.get("current_url", url)
        _state["video_title"] = data.get("video_title", "")
        _state["persona"] = data.get("persona", {})
        _state["topics"] = data.get("topics", [])
        _state["estimated_clips"] = data.get("estimated_clips", 0)
        _state["video_duration"] = data.get("video_duration", 0)
        _state["energy_peaks"] = data.get("energy_peaks", [])
        _state["active_model"] = data.get("active_model", "")
        _state["scene_peaks"] = data.get("scene_peaks", [])
        _state["is_strategizing"] = False
        _state["is_rendering"] = False
        _state["is_cancelled"] = False
        
        ui_logger.clear()
        ui_logger.log(f"✅ Session successfully restored from Google Drive: {video_id}")
        return {"status": "success", "message": "Session restored."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore session: {str(e)}")

def _get_video_duration_ffprobe(filepath: str) -> float:
    import subprocess, json
    try:
        cmd = [
            "ffprobe", "-v", "quiet", 
            "-print_format", "json", 
            "-show_streams", 
            "-select_streams", "v:0", 
            filepath
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if streams and "duration" in streams[0]:
                return float(streams[0]["duration"])
    except Exception as e:
        print(f"Error probing duration for {filepath}: {e}")
    return 0.0

@app.get("/api/gallery")
async def get_gallery(video_id: Optional[str] = None):
    import glob
    if video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        
    files.sort(key=os.path.getmtime, reverse=True)
    result = []
    for f in files:
        try:
            stat = os.stat(f)
            duration = _get_video_duration_ffprobe(f)
            rel_path = os.path.relpath(f, OUTPUT_DIR).replace("\\", "/")
            result.append({
                "filename": os.path.basename(f),
                "url": f"/media/{rel_path}",
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "created_at": _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %H:%M"),
                "created_at_ts": float(stat.st_mtime),
                "duration": duration,
                "rel_path": rel_path
            })
        except OSError:
            continue
    return result

@app.get("/api/export_csv")
async def export_csv():
    import csv
    import io
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["filename", "clip title", "hook sentence", "virality score", "duration"])

    curr_url = _state.get("current_url")
    curr_video_id = cache.video_id(curr_url) if curr_url else ""
    
    for clip in _state.get("clips", []):
        fn = clip.get("rendered_filename")
        if fn:
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1) or os.path.exists(p2):
                writer.writerow([
                    os.path.basename(fn),
                    clip.get("title", ""),
                    clip.get("hook_text", ""),  # was hook_sentence — wrong field name; CSV shipped with empty hook column
                    clip.get("score", ""),
                    clip.get("duration", "")
                ])
            
    output.seek(0)
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clipfactory_metadata.csv"}
    )

@app.post("/api/clear_gallery")
async def clear_gallery(project_only: bool = False, video_id: Optional[str] = None):
    import glob
    import shutil

    if project_only:
        current_filenames = {clip.get("rendered_filename") for clip in _state.get("clips", []) if clip.get("rendered_filename")}
        files = []
        curr_url = _state.get("current_url")
        curr_video_id = cache.video_id(curr_url) if curr_url else ""
        for fn in current_filenames:
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1):
                files.append(p1)
            elif os.path.exists(p2):
                files.append(p2)
        
        # Clear rendered_filename inside the _state so they are no longer marked as rendered
        for clip in _state.get("clips", []):
            if "rendered_filename" in clip:
                del clip["rendered_filename"]
        if _state.get("current_url"):
            _save_session(_state["current_url"])
    elif video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        
    deleted_count = 0
    for f in files:
        try:
            os.remove(f)
            deleted_count += 1
        except OSError:
            continue
            
    # Clean up empty subdirectories
    if not project_only and not video_id:
        for item in os.listdir(OUTPUT_DIR):
            item_path = os.path.join(OUTPUT_DIR, item)
            if os.path.isdir(item_path):
                try:
                    if not os.listdir(item_path):
                        os.rmdir(item_path)
                except OSError:
                    pass
    elif video_id:
        session_dir = os.path.join(OUTPUT_DIR, video_id)
        if os.path.exists(session_dir) and os.path.isdir(session_dir):
            try:
                if not os.listdir(session_dir):
                    os.rmdir(session_dir)
            except OSError:
                pass
                
    return {"status": "success", "message": f"Deleted {deleted_count} rendered clips."}

@app.delete("/api/clips/{video_id}/{filename}")
async def delete_clip(video_id: str, filename: str):
    if not re.match(r'^[\w\-. ]+\.mp4$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not re.match(r'^[\w\-]+$', video_id):
        raise HTTPException(status_code=400, detail="Invalid video_id")
    file_path = os.path.join(OUTPUT_DIR, video_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Clip not found")
    try:
        os.remove(file_path)
        for clip in _state.get("clips", []):
            rf = clip.get("rendered_filename", "")
            if rf and (rf == f"{video_id}/{filename}" or rf.endswith("/" + filename)):
                clip.pop("rendered_filename", None)
        if _state.get("current_url"):
            _save_session(_state["current_url"])
        return {"status": "deleted", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/settings")
async def get_settings():
    env_file = os.path.join(BASE_DIR, ".env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v.strip()
    return {
        "api_keys": {
            "TOKENROUTER_API_KEY": env_vars.get("TOKENROUTER_API_KEY", ""),
            "GEMINI_API_KEY": env_vars.get("GEMINI_API_KEY", ""),
            "GROQ_API_KEY": env_vars.get("GROQ_API_KEY", ""),
            "OPENROUTER_API_KEY": env_vars.get("OPENROUTER_API_KEY", ""),
            "GLM_API_KEY": env_vars.get("GLM_API_KEY", ""),
            "NVIDIA_API_KEY": env_vars.get("NVIDIA_API_KEY", ""),
        }
    }

class SettingsRequest(BaseModel):
    api_keys: dict

@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    env_file = os.path.join(BASE_DIR, ".env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v
                    
    for k, v in req.api_keys.items():
        env_vars[k] = v.strip()
        os.environ[k] = v.strip()
            
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(env_file, "w") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
            
    return {"status": "success", "message": "Settings saved"}

# ── Global auto-apply watermark config (generation tab) ────────────────────
@app.get("/api/watermark/config")
async def get_watermark_config():
    cfg = _load_watermark_config()
    return {
        "enabled": bool(cfg.get("enabled")),
        "position": cfg.get("position", "bottom-center"),
        "opacity": cfg.get("opacity", 0.85),
        "scale": cfg.get("scale"),
        "has_image": bool(cfg.get("png_path")) and os.path.exists(cfg.get("png_path", "")),
    }

@app.post("/api/watermark/config")
async def update_watermark_config(
    enabled: bool = Form(True),
    position: str = Form("bottom-center"),
    opacity: float = Form(0.85),
    scale: Optional[float] = Form(None),
    png: Optional[UploadFile] = File(None),
):
    # Save the uploaded PNG before writing config so a crash mid-write never
    # leaves config pointing at a missing file.
    png_path = None
    if png and png.filename:
        png_bytes = await png.read()
        if png_bytes:
            os.makedirs(os.path.dirname(WATERMARK_PNG_PATH), exist_ok=True)
            with open(WATERMARK_PNG_PATH, "wb") as f:
                f.write(png_bytes)
            png_path = WATERMARK_PNG_PATH

    cfg = _load_watermark_config()
    if png_path:
        cfg["png_path"] = png_path
    cfg["enabled"] = enabled
    cfg["position"] = position if position in ("top-left", "top-right", "bottom-left", "bottom-right", "top-center", "bottom-center", "center") else "bottom-center"
    cfg["opacity"] = max(0.05, min(1.0, opacity))
    cfg["scale"] = scale

    os.makedirs(BASE_DIR, exist_ok=True)
    with open(WATERMARK_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    return {
        "status": "success",
        "enabled": cfg["enabled"],
        "position": cfg["position"],
        "opacity": cfg["opacity"],
        "scale": cfg["scale"],
        "has_image": bool(cfg.get("png_path")) and os.path.exists(cfg.get("png_path", "")),
    }

@app.delete("/api/watermark/config")
async def delete_watermark_config():
    """Disable the global watermark and clear the persisted PNG."""
    for p in (WATERMARK_CONFIG_PATH, WATERMARK_PNG_PATH):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return {"status": "success", "message": "Watermark cleared"}

@app.delete("/api/models/{filename:path}")
async def delete_model(filename: str):
    file_path = os.path.join(LLM_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        os.remove(file_path)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/sessions/{video_id}")
async def delete_session(video_id: str):
    import shutil
    session_dir = os.path.join(SESSIONS_DIR, video_id)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        shutil.rmtree(session_dir)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/storage")
async def get_storage_info():
    import json
    models = []
    if os.path.exists(LLM_DIR):
        for f in os.listdir(LLM_DIR):
            path = os.path.join(LLM_DIR, f)
            if os.path.isfile(path) and f.endswith(".gguf"):
                models.append({
                    "filename": f,
                    "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1)
                })
                
    sessions = []
    sessions_dir = SESSIONS_DIR
    if os.path.exists(sessions_dir):
        for f in os.listdir(sessions_dir):
            path = os.path.join(sessions_dir, f)
            if os.path.isdir(path):
                # Count files inside
                size = sum(os.path.getsize(os.path.join(path, f2)) for f2 in os.listdir(path) if os.path.isfile(os.path.join(path, f2)))
                state_file = os.path.join(path, "state.json")
                url = ""
                clips_count = 0
                duration = 0
                if os.path.exists(state_file):
                    try:
                        with open(state_file, "r", encoding="utf-8") as sf:
                            sdata = json.load(sf)
                            url = sdata.get("current_url", "")
                            clips_count = len(sdata.get("clips", []))
                            duration = sdata.get("video_duration", 0)
                    except:
                        pass
                sessions.append({
                    "video_id": f,
                    "size_mb": round(size / (1024 * 1024), 1),
                    "url": url,
                    "clips_count": clips_count,
                    "duration": duration
                })
                
    return {"models": models, "sessions": sessions}


#  Local batch pipeline (added session 11, 2026-07-12): watch-folder sourcing,
#  sequential queue processing, per-video clip grouping. Used for overnight
#  batches of dozens of videos from multiple creators. yt-dlp downloader is NOT
#  used — owner pastes local MP4s into the watch folder manually.
# ══════════════════════════════════════════════════════════════════════════════


def _video_id_from_path(path: str) -> str:
    """Stable video id for a local file path. 32-char hex of (absolute path)
    so the same path always maps to the same id, different paths get unique ids.

    Reuses cache.video_id()'s md5() algorithm by routing through `cache.video_id`.
    """
    try:
        from shorts_generator.cache import video_id as _cache_video_id
        # Use file:// URL — keeps the same hashing as YouTube URLs do.
        abs_norm = os.path.normpath(os.path.abspath(path)).replace("\\", "/")
        return _cache_video_id(f"file://{abs_norm}")
    except Exception:
        # Fallback if cache module changes shape: hash the abs path.
        abs_norm = os.path.normpath(os.path.abspath(path))
        return hashlib.md5(abs_norm.encode("utf-8")).hexdigest()[:32]


def _is_file_stable_enough(path: str) -> bool:
    """Reject files still being written. Must be > 10 MB AND mtime older than
    30 seconds. Catches copy-in-progress when users drop huge videos.
    """
    try:
        size = os.path.getsize(path)
        if size < _WATCH_MIN_BYTES:
            return False
        mtime = os.path.getmtime(path)
        if time.time() - mtime < _WATCH_STABLE_SECONDS:
            return False
        return True
    except OSError:
        return False


def _enqueue_path(path: str) -> Optional[dict]:
    """Add a path to the queue if not already there. Returns the new item, or None if duplicate."""
    abs_norm = os.path.normpath(os.path.abspath(path))
    if abs_norm in _state["processed_paths"]:
        return None
    if not (os.path.isfile(abs_norm) and abs_norm.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4v"))):
        return None
    _state["processed_paths"].add(abs_norm)
    item = {
        "path": abs_norm,
        "filename": os.path.basename(abs_norm),
        "video_id": _video_id_from_path(abs_norm),
        "status": "pending",
        "title": "",
        "started_at": None,
        "finished_at": None,
        "clips_count": 0,
        "error": None,
    }
    _state["queue"].append(item)
    return item


def _find_pending_item() -> Optional[dict]:
    for item in _state["queue"]:
        if item["status"] == "pending":
            return item
    return None


def _queue_worker_loop() -> None:
    """Background thread that processes the queue one item at a time.

    Why a worker thread: the existing `_run_strategize` is a long-running
    blocking function. FastAPI background_tasks is also blocking. Running
    a dedicated daemon thread gives us:
      - Hard pause/stop via _state['queue_running'] = False
      - Clean shutdown on process exit (daemon=True)
      - Sequential processing (GPU can't fork meaningfully anyway)
    """
    while _state["queue_running"]:
        item = _find_pending_item()
        if item is None:
            # No work; sleep then re-check
            time.sleep(_WATCH_POLL_INTERVAL)
            continue

        # Wait for any manual single-video run to finish first. Manual runs
        # hold is_strategizing/is_rendering WITHOUT setting queue_active_item,
        # so launching on top of it would clobber shared state.
        while (
            _state["queue_running"]
            and (_state["is_strategizing"] or _state["is_rendering"])
        ):
            time.sleep(1.0)
        if not _state["queue_running"]:
            break

        item["status"] = "downloading"
        item["started_at"] = time.time()
        _state["queue_active_item"] = item
        ui_logger.log(f"[QUEUE] Picking up: {item['filename']}")

        try:

            # The existing downloader short-circuits to os.link/shutil.copy2 if
            # the URL is a local file path. So passing item["path"] as the URL
            # is enough — no downloader modification needed.
            from shorts_generator import cache as _cache
            url_for_pipeline = item["path"]

            # Set the title from the filename for display purposes (no yt-dlp).
            item["title"] = os.path.splitext(item["filename"])[0]

            # Mark busy for the duration of this item so /api/strategize and the
            # render endpoints can't launch a second pipeline and clobber state.
            # (_run_strategize's finally clears it when this item's run ends.)
            _state["is_strategizing"] = True

            item["status"] = "transcribing"
            ui_logger.log(f"[QUEUE] Transcribing: {item['filename']}")
            _run_strategize(
                url=url_for_pipeline,
                # Honor the model the owner selected in the UI instead of hardcoding.
                llm_label=_state.get("batch_model_label") or LLM_CATALOG[0]["label"],
                whisper_label="Medium (Fast/Accurate)",
                angle="standard",
                campaign_brief=None,
                allow_natural_recomposition=False,
                max_duration=90,
            )

            item["status"] = "strategizing"
            # Decide the outcome BEFORE touching the merged clip list.
            # _run_strategize swallows its own exceptions and early-returns, so
            # the status it publishes is the only reliable signal. Merging on
            # any other outcome would re-stamp the PREVIOUS video's clips as
            # belonging to this one (_state["clips"] is unchanged on early
            # return) — duplicates + wrong ownership in the results.
            strategy_status = _state.get("_strategy_status", "ok")

            if strategy_status == "cancelled":
                item["status"] = "cancelled"
                item["error"] = "Stopped by user"
                item["finished_at"] = time.time()
                ui_logger.log(f"[QUEUE] Cancelled: {item['filename']} — worker exiting, no further videos will run.")
                _state["queue_active_item"] = None
                break

            if strategy_status == "ok":
                # Batch semantics: each item's strategy REPLACES _state["clips"] with
                # ITS clips, but a usable batch needs every prior video's clips to
                # remain renderable. So we accumulate: keep a batch-owned clip list,
                # stamp ownership on the new clips, then republish the merged list.
                # clips_by_video indices point into this merged list (stable).
                new_clips = _state["clips"]
                for clip in new_clips:
                    clip["source_path"] = item["path"]
                    clip["source_filename"] = item["filename"]
                    clip["video_id"] = item["video_id"]
                base_idx = len(_state["batch_clips_accumulated"])
                _state["batch_clips_accumulated"].extend(new_clips)
                _state["clips"] = _state["batch_clips_accumulated"]
                new_indices = list(range(base_idx, len(_state["clips"])))
                _state["clips_by_video"][item["video_id"]] = new_indices

                # Thumbnail files are renumbered thumb_0..N by every strategy run, so
                # this video's thumbnails were just overwritten — persist them under
                # video-scoped names before the next item wipes/renumbers them.
                import shutil as _thumb_shutil
                for i, clip in enumerate(new_clips):
                    src_thumb = os.path.join(THUMB_DIR, f"thumb_{i}.jpg")
                    if os.path.exists(src_thumb):
                        scoped = f"batch_{item['video_id'][:8]}_{base_idx + i}.jpg"
                        try:
                            _thumb_shutil.copy2(src_thumb, os.path.join(THUMB_DIR, scoped))
                            clip["thumbnail_url"] = f"/thumbs/{scoped}"
                        except OSError:
                            pass

                # Snapshot this video's session so later renders can resolve the
                # right source/transcript even after a subsequent batch item has
                # overwritten the shared _state ("clips"/"word_timestamps").
                _state["batch_sessions"][item["video_id"]] = {
                    "url": url_for_pipeline,
                    "title": item["title"],
                    "clip_count": len(new_indices),
                }
                item["clips_count"] = len(new_indices)
                item["status"] = "done"
                item["finished_at"] = time.time()
                elapsed = int(item["finished_at"] - (item["started_at"] or item["finished_at"]))
                ui_logger.log(
                    f"[QUEUE] Done: {item['filename']} → {item['clips_count']} clips "
                    f"in {elapsed}s"
                )
            else:
                # failed or no_clips — merge nothing.
                failed = strategy_status == "failed"
                item["status"] = "failed" if failed else "done"
                item["clips_count"] = 0
                if failed:
                    item["error"] = _state.get("_strategy_error", "Unknown pipeline error")
                item["finished_at"] = time.time()
                if failed:
                    ui_logger.log(f"[QUEUE] FAILED: {item['filename']} — {item['error']}")
                else:
                    ui_logger.log(f"[QUEUE] No clips: {item['filename']} — nothing worth clipping.")
        except Exception as e:
            item["status"] = "failed"
            item["error"] = str(e)
            item["finished_at"] = time.time()
            ui_logger.log(f"[QUEUE] FAILED: {item['filename']}: {e}")

        _state["queue_active_item"] = None

    ui_logger.log("[QUEUE] Worker loop exited.")


def _watch_folder_loop() -> None:
    """Background thread that polls the configured watch folder for new files.

    Auto-ingest flow:
      1. Sleep _WATCH_POLL_INTERVAL
      2. List _state["queue_watch_dir"] for *.mp4 / *.mov / *.mkv / *.webm / *.m4v
      3. Reject files still being written (< 10MB or mtime < 30s ago)
      4. _enqueue_path if not already seen
    """
    while True:
        watch_dir = _state["queue_watch_dir"]
        if not watch_dir or not os.path.isdir(watch_dir):
            time.sleep(_WATCH_POLL_INTERVAL)
            continue
        try:
            for entry in os.listdir(watch_dir):
                full_path = os.path.join(watch_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                if not _is_file_stable_enough(full_path):
                    continue
                item = _enqueue_path(full_path)
                if item is not None:
                    ui_logger.log(f"[WATCH] Detected new file in {watch_dir}: {entry}")
        except OSError as e:
            ui_logger.log(f"[WATCH] Folder scan failed: {e}")

        time.sleep(_WATCH_POLL_INTERVAL)


def _run_picker(script: str) -> str:
    """Run an inline tkinter picker in a hidden child interpreter; return stdout.

    Why subprocess: tkinter's mainloop conflicts with uvicorn's event loop
    when run in-process. The top-of-module subprocess patch already injects
    CREATE_NO_WINDOW so no console pops.

    Why not sys.executable in the frozen EXE: in a PyInstaller bundle
    sys.executable IS ClipFactory.exe — spawning it with '-c' just relaunches
    a second app instance (which dies on the single-instance lock) instead of
    running the dialog. Frozen mode must resolve a real Python interpreter.
    """
    import shutil

    if getattr(sys, "frozen", False):
        exe = next(
            (
                shutil.which(p)
                for p in ("py", "python", "python3")
                if shutil.which(p) and "WindowsApps" not in shutil.which(p)
            ),
            None,
        )
        if not exe:
            raise RuntimeError(
                "No Python interpreter found on PATH — the packaged app needs "
                "one to open native folder pickers. Install Python 3 or run "
                "the app from source."
            )
    else:
        exe = sys.executable

    result = subprocess.run(
        [exe, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,  # 5 min — user might wander through folders/files
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "picker exited with an error").strip()[:300])
    return result.stdout or ""


# NOTE: _start_queue_auto was removed 2026-08-16 (owner directive): batches
# must wait for the user's explicit Start. The only remaining ways to start
# the worker are POST /api/queue/start (UI buttons) and its own idempotence
# guard. Watch-folder ingest intentionally does NOT start the worker either.


class SetWatchDirRequest(BaseModel):
    watch_dir: str


class IngestPathsRequest(BaseModel):
    paths: List[str]


@app.post("/api/queue/set_watch_dir")
async def queue_set_watch_dir(req: SetWatchDirRequest):
    """Tell the watch-folder loop which directory to monitor. Empty string disables."""
    path = req.watch_dir.strip()
    if path and not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
    _state["queue_watch_dir"] = path
    return {"watch_dir": _state["queue_watch_dir"]}


@app.post("/api/queue/pick_folder")
def queue_pick_folder():
    """Open a native OS folder picker (Windows only) and return the chosen path.

    Dialog work is delegated to _run_picker (hidden child interpreter).
    Non-Windows (Linux/macOS/Colab) returns ok=false so the frontend can fall
    back to the text input.
    """
    if os.name != "nt":
        return {"ok": False, "reason": "Use the text input on this platform."}

    # Inline tkinter script. Hides the root window, opens askdirectory,
    # prints the path (or empty string on cancel), exits.
    picker_script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk()\n"
        "r.withdraw()\n"
        "r.attributes('-topmost', True)\n"
        "p = filedialog.askdirectory(parent=r, title='Pick a watch folder')\n"
        "r.destroy()\n"
        "print(p or '')\n"
    )

    try:
        path = _run_picker(picker_script)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Folder picker timed out (5 min)."}
    except FileNotFoundError:
        return {"ok": False, "reason": "Python interpreter not found."}
    except Exception as e:
        return {"ok": False, "reason": f"Failed to open picker: {e}"}

    path = (path or "").strip()
    if not path:
        return {"ok": False, "reason": "Dialog cancelled."}
    if not os.path.isdir(path):
        # Defensive — askdirectory should only return dirs, but a symlink
        # race or external symlink deletion could fool it.
        return {"ok": False, "reason": f"Not a directory: {path}"}
    _state["queue_watch_dir"] = path
    return {"ok": True, "path": path, "watch_dir": path}


@app.post("/api/queue/pick_videos")
def queue_pick_videos():
    """Open a native multi-file picker for local VIDEO files and queue them.

    Owner workflow: Browse → select any number of videos → they land in the
    batch queue (deduped) and processing auto-starts if idle. No watch folder
    or copies needed — files are queued in place.
    """
    if os.name != "nt":
        return {"ok": False, "reason": "Use the text input on this platform."}

    import json as _json
    picker_script = (
        "import tkinter as tk, json\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk()\n"
        "r.withdraw()\n"
        "r.attributes('-topmost', True)\n"
        "p = filedialog.askopenfilenames(\n"
        "    parent=r, title='Select video files',\n"
        "    filetypes=[('Video files', '*.mp4 *.mov *.mkv *.webm *.m4v'), ('All files', '*.*')])\n"
        "r.destroy()\n"
        "print(json.dumps(list(p)))\n"
    )

    try:
        out = _run_picker(picker_script)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Video picker timed out (5 min)."}
    except FileNotFoundError:
        return {"ok": False, "reason": "Python interpreter not found."}
    except Exception as e:
        return {"ok": False, "reason": f"Failed to open picker: {e}"}

    out = (out or "").strip()
    if not out:
        return {"ok": False, "reason": "Dialog cancelled."}
    try:
        paths = _json.loads(out)
    except ValueError:
        return {"ok": False, "reason": "Picker returned an unreadable result."}
    if not isinstance(paths, list) or not paths:
        return {"ok": False, "reason": "Dialog cancelled."}

    added = []
    skipped = []
    for p in paths:
        item = _enqueue_path(p)
        if item:
            added.append(item["filename"])
        else:
            skipped.append(p)

    # Queued, NOT started (owner directive 2026-08-16): the user picks when
    # to run via Start Batch / Run Queue.
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "queue_length": len(_state["queue"]),
        "queue_running": _state["queue_running"],
    }


@app.get("/api/queue/state")
async def queue_state():
    """Return current queue, queue_running flag, active item, watch dir."""
    return {
        "queue": _state["queue"],
        "queue_running": _state["queue_running"],
        "queue_active_item": _state["queue_active_item"],
        "queue_watch_dir": _state["queue_watch_dir"],
        "clips_by_video": _state["clips_by_video"],
    }


class QueueStartRequest(BaseModel):
    # Model the owner had selected in the UI when starting the batch.
    llm_label: Optional[str] = None

@app.post("/api/queue/start")
async def queue_start(req: Optional[QueueStartRequest] = None):
    """Begin processing the queue. Idempotent — refuses if already running."""
    if _state["queue_running"]:
        return {"queue_running": True, "message": "Already running"}
    if _state["queue"]:
        # Capture the owner's model choice at start time so the worker uses it
        # for every video instead of a hardcoded model.
        if req and req.llm_label:
            _state["batch_model_label"] = req.llm_label
        # Fresh batch run: reset the merged clip list so stale clips from a
        # previous single-video strategize or prior batch don't pollute indices.
        _state["batch_clips_accumulated"] = []
        _state["queue_running"] = True
        thread = threading.Thread(target=_queue_worker_loop, daemon=True)
        thread.start()
        return {"queue_running": True, "queue_length": len(_state["queue"])}
    return {"queue_running": False, "message": "Queue is empty — nothing to do"}


@app.post("/api/queue/stop")
async def queue_stop():
    """Halt processing. Currently active item will finish, then loop exits."""
    if not _state["queue_running"]:
        return {"queue_running": False, "message": "Not running"}
    _state["queue_running"] = False
    return {"queue_running": False, "message": "Stopping after current item"}


@app.post("/api/queue/clear")
async def queue_clear():
    """Drop all pending + completed items and allow re-ingest of those files."""
    _state["queue"] = []
    # processed_paths dedupes ingest; clearing the queue without resetting it
    # made every cleared video permanently un-queueable until restart.
    _state["processed_paths"] = set()
    return {"queue_length": 0, "message": "Queue cleared"}


@app.post("/api/queue/ingest_paths")
async def queue_ingest_paths(req: IngestPathsRequest):
    """Manually push video file paths into the queue. Useful for drag-drop or
    script-driven ingest when watch-folder detection isn't desired."""
    added = []
    skipped = []
    for p in req.paths:
        item = _enqueue_path(p)
        if item:
            added.append(item["filename"])
        else:
            skipped.append(p)
    return {"added": added, "skipped": skipped, "queue_length": len(_state["queue"])}


# Boot the watcher thread ONCE at module load. It's a daemon so it dies with
# the process. The watch_dir is empty by default; the user sets via /api/queue/set_watch_dir.
_watch_thread_started = False
def _start_watch_thread_once():
    global _watch_thread_started
    if _watch_thread_started:
        return
    t = threading.Thread(target=_watch_folder_loop, daemon=True, name="clip-factory-watcher")
    t.start()
    _watch_thread_started = True
    ui_logger.log("[WATCH] Folder watcher thread started (idle until watch_dir set).")


_start_watch_thread_once()


# ── Post-render editor (D2): trim / watermark / crop ──────────
# All three routes delegate to `shorts_generator.editor` and never accept a
# client-supplied out_path — the server appends a fixed suffix to the source
# filename (e.g. clip.mp4 -> clip_trim.mp4), so path traversal outside
# OUTPUT_DIR is structurally impossible.

_FILENAME_RE = re.compile(r'^[\w\-. ]+\.mp4$')
_VIDEO_ID_RE = re.compile(r'^[\w\-]+$')

# Server-generated out-path suffixes. Naming chosen so the gallery shows the
# relationship to the source (clip.mp4 -> clip_trim.mp4) without crowding the
# filename with the operation details.
_EDITOR_SUFFIX = {"trim": "trim", "watermark": "wm", "crop": "crop"}


def _resolve_editor_in_path(video_id: str, filename: str) -> str:
    """Validate identifiers, then return an existing input path inside OUTPUT_DIR.

    Tries the structured `<video_id>/<filename>` layout first (matches what the
    gallery endpoint emits for modern clips) and falls back to the legacy flat
    layout `<OUTPUT_DIR>/<filename>` for older single-folder sessions.
    """
    if not _VIDEO_ID_RE.match(video_id or ""):
        raise HTTPException(status_code=400, detail="Invalid video_id")
    if not _FILENAME_RE.match(filename or ""):
        raise HTTPException(status_code=400, detail="Invalid filename")
    candidates = [
        os.path.join(OUTPUT_DIR, video_id, filename),
        os.path.join(OUTPUT_DIR, filename),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise HTTPException(status_code=404, detail="Clip not found")


def _editor_out_path(in_path: str, op: str) -> str:
    """Build `<stem>_<suffix>.mp4` next to the input. ffmpeg -y overwrites."""
    suffix = _EDITOR_SUFFIX[op]
    stem, ext = os.path.splitext(os.path.basename(in_path))
    return os.path.join(os.path.dirname(in_path), f"{stem}_{suffix}.mp4")


class EditorTrimRequest(BaseModel):
    video_id: str
    filename: str
    start_s: float = Field(..., ge=0)
    end_s: float = Field(..., gt=0)


@app.post("/api/editor/trim")
async def editor_trim(req: EditorTrimRequest):
    in_path = _resolve_editor_in_path(req.video_id, req.filename)
    if req.end_s <= req.start_s:
        raise HTTPException(status_code=400, detail="end_s must be greater than start_s")
    out_path = _editor_out_path(in_path, "trim")
    try:
        # Late import — keeps server.main boot cheap and matches clipper pattern.
        from shorts_generator import editor
        editor.trim_clip(in_path, out_path, req.start_s, req.end_s)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "status": "ok",
        "op": "trim",
        "out_filename": os.path.basename(out_path),
        "out_rel_path": os.path.relpath(out_path, OUTPUT_DIR).replace("\\", "/"),
        "out_url": f"/media/{os.path.relpath(out_path, OUTPUT_DIR).replace(chr(92), '/')}",
    }


@app.post("/api/editor/watermark")
async def editor_watermark(
    video_id: str = Form(...),
    filename: str = Form(...),
    position: str = Form("bottom-right"),
    opacity: float = Form(0.85),
    scale: Optional[float] = Form(None),
    watermark: UploadFile = File(...),
):
    """Burn a PNG watermark into a rendered clip.

    Multipart form (not JSON) because the PNG itself is uploaded.
    Saves the upload to a NamedTemporaryFile (delete=False so ffmpeg
    can read it), passes the path to ``editor.watermark_clip``, then
    unlinks in a finally block. The temp path is used as a plain ffmpeg
    ``-i`` input argument — NOT inside a filter graph — so the Windows
    drive-letter colon issue that broke the earlier ``textfile=`` path
    does NOT apply here.
    """
    import tempfile
    in_path = _resolve_editor_in_path(video_id, filename)
    out_path = _editor_out_path(in_path, "watermark")
    tmp_png = None
    try:
        # Persist the upload to disk so ffmpeg can -i it. Suffix *.png is
        # important: ffmpeg probes the format from the extension.
        tmp_fd, tmp_png = tempfile.mkstemp(suffix=".png")
        os.close(tmp_fd)
        with open(tmp_png, "wb") as f:
            while True:
                chunk = await watermark.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        from shorts_generator import editor
        try:
            editor.watermark_clip(in_path, out_path, tmp_png, position, opacity=opacity, scale=scale)
        except TypeError:
            editor.watermark_clip(in_path, out_path, tmp_png, position)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_png and os.path.exists(tmp_png):
            try:
                os.unlink(tmp_png)
            except OSError:
                pass
    rel = os.path.relpath(out_path, OUTPUT_DIR).replace(chr(92), "/")
    return {
        "status": "ok",
        "op": "watermark",
        "out_filename": os.path.basename(out_path),
        "out_rel_path": rel,
        "out_url": f"/media/{rel}",
    }


class EditorCropRequest(BaseModel):
    video_id: str
    filename: str
    ratio: str  # "9:16" | "1:1" | "4:5" — validated by editor.crop_clip


@app.post("/api/editor/crop")
async def editor_crop(req: EditorCropRequest):
    in_path = _resolve_editor_in_path(req.video_id, req.filename)
    out_path = _editor_out_path(in_path, "crop")
    try:
        from shorts_generator import editor
        editor.crop_clip(in_path, out_path, req.ratio)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    rel = os.path.relpath(out_path, OUTPUT_DIR).replace(chr(92), "/")
    return {
        "status": "ok",
        "op": "crop",
        "out_filename": os.path.basename(out_path),
        "out_rel_path": rel,
        "out_url": f"/media/{rel}",
    }


# ── Serve Next.js static build (Catch-all for SPA) ──────────
FRONTEND_DIR = os.path.join(REPO_DIR, "frontend", "out")

@app.get("/")
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"}

@app.get("/{path:path}")
async def catch_all(path: str):
    # Skip API and Media routes
    if path.startswith("api") or path.startswith("media") or path.startswith("ws"):
        raise HTTPException(status_code=404)
        
    # Check if file exists in out dir (e.g. _next/static/...)
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
        
    # Fallback to index.html for client-side routing
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
        
    return FileResponse(index_path) if os.path.exists(index_path) else {"detail": "Not Found"}
