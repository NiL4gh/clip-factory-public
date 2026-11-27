"""Horizontal face tracking for the 1:1 box layout (cinematic deadband glide).

Why this module exists: the 1080x1080 crop used to be static (centered), so a
speaker could drift out of the tight frame in wide or multi-person shots.

Cinematic Auto-Reframe Design:
- Deadband / Central Comfort Zone: Minor head turns, natural speech sways,
  and micro-gestures within ±80px are ignored completely. The camera remains
  rock-solid and locked in place.
- Intentional Movement Tracking: When the speaker walks across stage or
  sustains a new position, the camera performs a smooth, continuous linear
  pan over 1.2s–1.8s.
- Continuous FFmpeg Expression: Panning uses continuous sub-pixel linear
  interpolation via FFmpeg's native `clip((t-t0)/dur, 0, 1)` function.
  Zero instantaneous staircase jumps (gt()), zero fidgeting/jitter, and
  cleanly bounded term count.
- On-Demand Segment Detection: Detections are sampled for the requested clip
  range on demand with a persistent per-video cache, eliminating multi-minute
  full-video scan delays.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Dict

import cv2
import numpy as np

MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"

SAMPLE_SPACING = 0.5        # seconds between detection frames
DEADBAND_SRC_PX = 80.0      # px in source space — deadband window where camera stays locked
GLIDE_DURATION = 1.4        # seconds for smooth camera pan transition
MIN_CONFIDENCE = 0.60       # YuNet score threshold for a usable detection

Samples = List[Tuple[float, float]]  # (source_time_s, face_center_x_source_px)
Track = List[Tuple[float, float]]    # (source_time_s, smoothed_center_x_source_px)

MAX_EXPR_STEPS = 96


def model_path() -> Optional[str]:
    """Absolute path of the bundled YuNet ONNX model, or None if missing."""
    p = Path(__file__).resolve().parent / "assets" / MODEL_FILENAME
    return str(p) if p.exists() else None


# Per-video sample cache: stores scanned (time, center_x) tuples.
# Keyed by path+size+mtime.
_SAMPLE_CACHE: Dict[Tuple, Samples] = {}


def _cache_key(video_path: str):
    p = Path(video_path)
    try:
        st = p.stat()
        return (str(p.resolve()), st.st_size, st.st_mtime)
    except OSError:
        return None


def _scan_range(video_path: str, start: float, end: float,
                min_conf: float = MIN_CONFIDENCE) -> Samples:
    """Raw detection pass over [start, end). No caching. Returns one
    (time, face_center_x) sample per analyzed frame; [] on any failure."""
    mp = model_path()
    if not mp or start >= end:
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    detector = None
    samples: Samples = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        t = max(0.0, float(start))
        while t < end:
            frame_idx = int(t * fps)
            if total_frames > 0 and frame_idx >= total_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            h, w = frame.shape[:2]
            scale = 720.0 / h if h > 720 else 1.0
            sw, sh = int(w * scale), int(h * scale)
            proc_frame = cv2.resize(frame, (sw, sh)) if scale != 1.0 else frame

            if detector is None:
                detector = cv2.FaceDetectorYN.create(mp, "", (sw, sh), score_threshold=0.35)
            else:
                detector.setInputSize((sw, sh))
            _, faces = detector.detect(proc_frame)
            if faces is not None and len(faces) > 0:
                best_center_x = None
                best_score = -1.0
                for f in faces:
                    conf = float(f[14])
                    if conf < min_conf:
                        continue
                    bx = float(f[0]) / scale
                    bw = float(f[2]) / scale
                    bh = float(f[3]) / scale
                    cx = bx + bw / 2.0

                    # 1. Centrality: penalize background/edge faces at the extreme borders
                    dist_norm = abs(cx - w / 2.0) / (w / 2.0)
                    centrality = max(0.15, 1.0 - 0.75 * (dist_norm ** 2))

                    # 2. Prominence / Area: foreground speakers are larger than background heads
                    area_norm = (bw * bh) / (w * h)
                    size_weight = float(np.sqrt(max(0.001, area_norm)))

                    # 3. Temporal continuity bonus: prefer staying with the currently tracked subject
                    continuity = 1.0
                    if samples:
                        prev_x = samples[-1][1]
                        dist_prev = abs(cx - prev_x) / w
                        if dist_prev < 0.12:
                            continuity = 1.3
                        elif dist_prev > 0.35:
                            continuity = 0.7

                    score = conf * size_weight * centrality * continuity
                    if score > best_score:
                        best_score = score
                        best_center_x = cx

                if best_center_x is not None:
                    samples.append((t, best_center_x))
            t += SAMPLE_SPACING
        return samples
    except Exception:
        return []
    finally:
        cap.release()


def _video_duration(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        return float(frames / fps) if fps > 0 else 0.0
    finally:
        cap.release()


def detect_center_x(video_path: str, start: float, end: float) -> Samples:
    """Face center detections covering [start, end), cached per source video.

    Scans the requested segment on demand with small padding and caches
    samples so later renders or overlapping segments resolve instantly.
    """
    key = _cache_key(video_path)
    if key is None:
        return _scan_range(video_path, start, end)

    if key not in _SAMPLE_CACHE:
        if len(_SAMPLE_CACHE) >= 5:
            _SAMPLE_CACHE.clear()
        _SAMPLE_CACHE[key] = []

    cached = _SAMPLE_CACHE[key]
    lo, hi = float(start), float(end)

    # Check if we already have samples covering this range
    existing = [(t, x) for t, x in cached if lo <= t < hi]
    expected_count = int((hi - lo) / SAMPLE_SPACING) * 0.4  # reasonable coverage check
    if len(existing) >= max(1, expected_count):
        return existing

    # Scan requested range with 1.0s padding
    new_samples = _scan_range(video_path, max(0.0, lo - 1.0), hi + 1.0)
    if new_samples:
        # Merge and deduplicate by timestamp
        all_pts = {round(t, 3): x for t, x in cached}
        for t, x in new_samples:
            all_pts[round(t, 3)] = x
        _SAMPLE_CACHE[key] = sorted([(t, x) for t, x in all_pts.items()])

    return [(t, x) for t, x in _SAMPLE_CACHE[key] if lo <= t < hi]


def clear_cache() -> None:
    """Drop cached detections (call on purge/new-session)."""
    _SAMPLE_CACHE.clear()


def smooth_track(samples: Samples, start: float, end: float, fps: float,
                 deadband_src_px: float = DEADBAND_SRC_PX,
                 glide_dur: float = GLIDE_DURATION) -> Track:
    """Generate a smooth, deadband-stabilized camera track spanning [start, end].

    Returns [(source_time, smoothed_center_x), ...] across the clip duration.
    Within deadband_src_px (±80px in source frame), the camera stays locked.
    When an intentional movement occurs, it generates a smooth continuous
    pan from anchor to anchor over glide_dur seconds.
    """
    if not samples or fps <= 0 or start >= end:
        return []

    # Proportional deadband scaling for high-resolution sources (e.g. 4K)
    if deadband_src_px == DEADBAND_SRC_PX:
        max_coord = max(x for _, x in samples)
        if max_coord > 2000:
            deadband_src_px = 160.0

    pts = sorted((max(float(start), float(t)), float(x)) for t, x in samples if start <= t <= end)
    if not pts:
        pts = sorted((float(t), float(x)) for t, x in samples)
        if not pts:
            return []

    # Calculate initial anchor from early detections (first 0.5s)
    early = [x for t, x in pts if t <= start + 0.5]
    curr_anchor = float(np.median(early)) if early else pts[0][1]

    duration = max(0.0, float(end) - float(start))
    transitions: List[Tuple[float, float, float, float]] = []  # (g_start, g_end, x_from, x_to)

    t_cursor = start
    last_trans_end = start
    step_window = 0.5

    while t_cursor < end:
        # Check median of detections in [t_cursor, t_cursor + 1.2s]
        window = [x for t, x in pts if t_cursor <= t < t_cursor + 1.2]
        if window:
            med_x = float(np.median(window))
            dist = med_x - curr_anchor
            if abs(dist) >= deadband_src_px and t_cursor >= last_trans_end + 0.4:
                g_start = round(t_cursor, 3)
                g_end = round(min(end, t_cursor + glide_dur), 3)
                if g_end > g_start:
                    transitions.append((g_start, g_end, curr_anchor, med_x))
                    curr_anchor = med_x
                    last_trans_end = g_end
        t_cursor += step_window

    n = max(2, int(round(duration * fps)) + 1)
    ts = [start + min(i / fps, duration) for i in range(n)]

    track: Track = []
    base_val = curr_anchor if not transitions else transitions[0][2]
    for t in ts:
        val = base_val
        for g_start, g_end, x_from, x_to in transitions:
            dur = g_end - g_start
            if dur > 0:
                frac = max(0.0, min(1.0, (t - g_start) / dur))
                val += frac * (x_to - x_from)
        track.append((t, val))

    return track


def scaled_width(scale_target: float, src_w: float, src_h: float,
                 scale_target_h: Optional[float] = None) -> int:
    """Actual width (px) of the frame the crop filter sees after
    `scale={tw}:{th}:force_original_aspect_ratio=increase`.

    increase-mode scales so BOTH output dims reach the target while keeping
    aspect: landscape sources come out wider than the target. Even-rounded
    like ffmpeg's yuv420p output. Unknown dims -> square target width.
    """
    if scale_target_h is None:
        scale_target_h = scale_target
    if src_w <= 0 or src_h <= 0:
        w = int(scale_target)
        return w + (w % 2)
    f = max(float(scale_target) / src_w, float(scale_target_h) / src_h)
    w = int(src_w * f)
    return w + (w % 2)



def default_crop_x(scale_target: float, src_w: float, src_h: float,
                   crop_w: int = 1080) -> int:
    """Centered crop offset — what today's bare `crop=1080:1080` does
    (ffmpeg centers a crop when x/y are omitted). Fallback anchor so
    tracking-off renders stay pixel-identical to the current output."""
    w = scaled_width(scale_target, src_w, src_h)
    return max(0, (w - crop_w) // 2)


def crop_expression(track: Track, seg_start: float, frame_w: int,
                    src_w: float, src_h: float, crop_w: int = 1080,
                    deadband_px: float = DEADBAND_SRC_PX,
                    glide_dur: float = GLIDE_DURATION) -> str:
    """Serialize the smoothed track into an ffmpeg continuous crop x='' expression.

    frame_w is the ACTUAL width of the frame the crop filter sees (via scaled_width()).
    
    Generates a continuous, sub-pixel smooth pan formula using FFmpeg's native `clip()`:
      clip(base + delta1*clip((t-t1)/dur1\\,0\\,1) + ..., 0, max_crop_x)
    
    Stationary tracks return a single static integer string (e.g. '420').
    Empty / invalid tracks return the centered default.
    """
    fallback = str(max(0, (int(frame_w) - crop_w) // 2))
    if not track or int(frame_w) <= crop_w:
        return fallback

    k = float(frame_w) / float(src_w) if src_w > 0 else 1.0
    lo_limit, hi_limit = 0, int(frame_w) - crop_w
    deadband_frame = max(25.0, deadband_px * k)

    # Filter points belonging to this segment
    pts = [(float(t) - float(seg_start), float(x) * k - crop_w / 2.0)
           for t, x in track if float(t) >= float(seg_start) - 0.05]
    if not pts:
        return fallback

    early = [x for t, x in pts if t <= 0.5]
    raw_base = float(np.median(early)) if early else pts[0][1]
    curr_cam_x = max(float(lo_limit), min(float(hi_limit), raw_base))
    base_x = int(round(curr_cam_x))

    glides: List[Tuple[float, float, int]] = []  # (g_start_rel, g_dur, delta_px)
    last_end = 0.0

    # Identify smooth glides from track
    for t_rel, raw_x in pts:
        clamped_x = max(float(lo_limit), min(float(hi_limit), raw_x))
        dist = clamped_x - curr_cam_x
        if abs(dist) >= deadband_frame and t_rel >= last_end + 0.3:
            g_start = round(max(0.0, t_rel), 3)
            g_dur = round(glide_dur, 3)
            delta = int(round(dist))
            if delta != 0:
                glides.append((g_start, g_dur, delta))
                curr_cam_x = curr_cam_x + delta
                last_end = g_start + g_dur

    if not glides:
        return str(base_x)

    terms = [str(base_x)]
    for g_start, g_dur, delta in glides:
        sign = '+' if delta > 0 else ''
        terms.append(f'{sign}{delta}*clip((t-{g_start})/{g_dur}\\,0\\,1)')

    inner = ''.join(terms)
    return f'clip({inner}\\,{lo_limit}\\,{hi_limit})'
