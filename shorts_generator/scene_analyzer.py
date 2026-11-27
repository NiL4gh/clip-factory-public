"""
CPU-only visual scene detection using PySceneDetect.
Gracefully degrades if scenedetect is not installed or times out.
Returns peaks in the same shape as audio_analyzer.analyze_audio_energy
for seamless fusion in the LLM prompt.
"""

import os
import time
import subprocess
from typing import List, Dict

from .logger import ui_logger
from .clipper import _get_best_encoder

# Lazy import so missing scenedetect doesn't break startup
_scenedetect_available = None  # tri-state: None=unchecked, True/False


def _check_scenedetect() -> bool:
    global _scenedetect_available
    if _scenedetect_available is not None:
        return _scenedetect_available
    try:
        import scenedetect  # noqa: F401
        _scenedetect_available = True
    except ImportError:
        _scenedetect_available = False
    return _scenedetect_available


_DOWNSCALED_WIDTH = 426   # 240p (426x240) - Extreme optimization for PySceneDetect
_DOWNSCALED_HEIGHT = 240
_TIMEOUT_SECONDS = 60      # Strict architectural constraint
_THRESHOLD = 27.0         # industry default for content detection

def _downscale_video(source_path: str, output_path: str) -> bool:
    """Downscale to 240p @ 5fps via ffmpeg for fast scene detection. Returns True on success."""
    try:
        import sys
        cflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(
            ["ffmpeg", "-y", "-i", source_path,
             "-vf", f"scale={_DOWNSCALED_WIDTH}:{_DOWNSCALED_HEIGHT},fps=5",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
             "-an",                    # drop audio
             output_path],
            capture_output=True, check=True, timeout=60, creationflags=cflags
        )
        return True
    except Exception as e:
        ui_logger.log(f"Scene analyzer: downscale failed ({e}). Attempting direct detection.")
        return False


def detect_scene_changes(video_path: str, session_id: str = "global") -> List[Dict]:
    """
    Detect scene/content changes in a video using PySceneDetect (CPU-only).

    Uses the high-level ``detect()`` API from scenedetect v1.x.
    Downscales to 480p before detection for speed.

    Returns a list of dicts::
        [{"time": <float seconds>, "score": <float 0-100>}, ...]
    Sorted by time ascending.

    Graceful degradation::
        - PySceneDetect not installed → log warning, return []
        - Detection exceeds 5 minutes → log warning, return []
        - No scenes found → return []
    """
    if not _check_scenedetect():
        ui_logger.log("Scene analyzer: scenedetect[opencv] not installed. Skipping visual scene detection.")
        return []
    if not os.path.isfile(video_path):
        ui_logger.log(f"Scene analyzer: video not found at {video_path}")
        return []

    ui_logger.log("Detecting scene changes (visual)…")

    # Downscale to 480p for speed
    temp_dir = os.path.dirname(video_path)
    downscaled = os.path.join(temp_dir, f"_scene_480p_{os.path.basename(video_path)}")
    downscaled_ok = _downscale_video(video_path, downscaled)
    target = downscaled if downscaled_ok else video_path

    try:
        from scenedetect.detectors import ContentDetector
        from scenedetect import detect  # high-level API (v1.x)
        start_ts = time.time()

        # Run detection with a timeout wrapper
        scene_list = _run_with_timeout(
            lambda: detect(target, ContentDetector(threshold=_THRESHOLD)),
            timeout=_TIMEOUT_SECONDS
        )

        elapsed = time.time() - start_ts
        if scene_list is None:
            ui_logger.log(f"Scene detection timed out after {_TIMEOUT_SECONDS}s — skipping visual signal.")
            return []

        # scene_list is a list of (start, end) FrameTimecode tuples.
        # Each start FrameTimecode has .get_seconds() for the cut point.
        peaks = []
        for start_cut, end_cut in scene_list:
            t = start_cut.get_seconds()
            # All detected cuts passed the threshold, so score is uniformly high.
            # We use 75 as a "confident scene change" signal for the LLM.
            peaks.append({"time": t, "score": 75.0})

        peaks.sort(key=lambda x: x["time"])

        ui_logger.log(f"Scene analyzer: {len(peaks)} visual transitions detected ({elapsed:.1f}s)")

        return peaks

    except ImportError:
        _scenedetect_available = False
        ui_logger.log("Scene analyzer: scenedetect import failed at runtime — skipping.")
        return []
    except Exception as e:
        ui_logger.log(f"Scene analyzer: error during detection ({e}). Skipping visual signal.")
        return []
    finally:
        # Ensure temp file cleanup
        try:
            if downscaled_ok:
                os.remove(downscaled)
        except (OSError, NameError):
            pass


def _run_with_timeout(func, timeout: int):
    """Run func() with a wall-clock timeout. Returns None if timed out."""
    import threading

    result = []
    exception = []

    def worker():
        try:
            r = func()
            result.append(r)
        except Exception as e:
            exception.append(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        return None  # timed out

    if exception:
        raise exception[0]

    return result[0] if result else None
