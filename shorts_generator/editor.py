"""Lightweight post-render clip editor.

Chunk D1 of Session 13 handoff plan (Engram #273).
Mutating operations on already-rendered clips: trim, watermark, crop.
All operations are non-destructive -- they write to ``out_path`` and
never touch ``in_path``.

Why pure arg builders split from entry fns:
  Tests assert ffmpeg arg construction without spawning a process.
  Entry fns then call the builder + ``subprocess.run`` + raise on failure.

Watermark: PNG overlay, not drawtext.
  Original D1 design used ffmpeg ``drawtext=`` with sanitized text. That
  approach is constrained to typographic watermarks and was replaced in
  this follow-up commit at the owner's request -- watermarks are now
  burned-in PNG images via the ffmpeg ``overlay`` filter. Two inputs go
  to ffmpeg (``-i in.mp4 -i watermark.png``), then ``-filter_complex
  [0:v][1:v]overlay=X:Y[out]`` composes them. ``X:Y`` is computed from
  the source + watermark dimensions per chosen corner with a 20px
  margin. The PNG path is passed as a plain ffmpeg input argument (not
  inside a filter graph), so the Windows drive-letter colon issue that
  broke the earlier ``textfile=`` attempt does not apply here.
"""
import json
import os
import subprocess
from typing import Literal

WatermarkPosition = Literal["top-left", "top-right", "bottom-left", "bottom-right", "top-center", "bottom-center", "center"]
CropRatio = Literal["9:16", "1:1", "4:5"]

# Margin (pixels) between the PNG and the chosen frame edge.
_WATERMARK_MARGIN = 20


def _probe_dimensions(in_path: str) -> tuple[int, int]:
    """Return (width, height) via ffprobe, or (0, 0) if probe fails.

    Reuses the same ffprobe pattern as ``clipper.validate_input_quality``
    so behaviour is consistent across the codebase.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        in_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stream = json.loads(proc.stdout).get("streams", [{}])[0]
        return int(stream.get("width", 0)), int(stream.get("height", 0))
    except Exception:
        return 0, 0


# ── Pure arg builders ──────────────────────────────────────────────────────

def _build_trim_args(in_path: str, out_path: str, start_s: float, end_s: float,
                     lossless: bool = True) -> list:
    """Construct ffmpeg args for a trim.

    ``lossless=True``  -> ``-ss S -to E -c copy`` (instant, but fails on
                          non-seekable sources or codec-mismatched output
                          containers; caller catches and retries with
                          lossless=False).
    ``lossless=False`` -> re-encode with libx264 + aac, universally safe.
    """
    if start_s < 0 or end_s < 0 or end_s <= start_s:
        raise ValueError(f"Invalid trim range start={start_s} end={end_s} (need 0 <= start < end)")
    args = ["ffmpeg", "-y", "-ss", str(start_s), "-to", str(end_s), "-i", in_path]
    if lossless:
        args += ["-c", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
    args.append(out_path)
    return args


def _build_watermark_overlay_args(in_path: str, out_path: str,
                                   watermark_png: str,
                                   src_w: int, src_h: int,
                                   wm_w: int, wm_h: int,
                                   position: WatermarkPosition = "bottom-right",
                                   margin: int = _WATERMARK_MARGIN,
                                   opacity: float = 1.0,
                                   scale: float = None) -> list:
    """Construct ffmpeg args overlaying a PNG watermark onto a video with opacity and positioning.

    Positions the PNG at one of corners or center with ``margin`` pixels of
    inset. Uses ffmpeg ``-filter_complex`` with the ``overlay`` filter
    and an explicit ``[out]`` label so we can also map the source audio
    through unchanged.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"Invalid source dimensions: {src_w}x{src_h}")
    if wm_w <= 0 or wm_h <= 0:
        raise ValueError(f"Invalid watermark dimensions: {wm_w}x{wm_h}")
    if wm_w > src_w or wm_h > src_h:
        raise ValueError(
            f"Watermark {wm_w}x{wm_h} is larger than source {src_w}x{src_h}; "
            f"scale the PNG down before uploading."
        )

    # Determine scale factor if explicitly requested or needed
    scale_factor = scale if (scale is not None and scale > 0) else 1.0

    eff_wm_w = int(wm_w * scale_factor)
    eff_wm_h = int(wm_h * scale_factor)

    positions = {
        "top-left":      (margin, margin),
        "top-right":     (src_w - eff_wm_w - margin, margin),
        "bottom-left":   (margin, src_h - eff_wm_h - margin),
        "bottom-right":  (src_w - eff_wm_w - margin, src_h - eff_wm_h - margin),
        "top-center":    ((src_w - eff_wm_w) // 2, margin),
        "bottom-center": ((src_w - eff_wm_w) // 2, src_h - eff_wm_h - margin),
        "center":        ((src_w - eff_wm_w) // 2, (src_h - eff_wm_h) // 2),
    }
    if position not in positions:
        raise ValueError(f"Unknown watermark position: {position}")
    x, y = positions[position]

    clamped_opacity = max(0.05, min(1.0, float(opacity)))

    # If opacity is 1.0 and no scaling requested, use the clean simple overlay filter
    if clamped_opacity >= 0.99 and abs(scale_factor - 1.0) < 0.01:
        filter_complex = f"[0:v][1:v]overlay={x}:{y}[out]"
    else:
        wm_filters = ["format=rgba"]
        if abs(scale_factor - 1.0) >= 0.01:
            wm_filters.append(f"scale={eff_wm_w}:{eff_wm_h}")
        if clamped_opacity < 0.99:
            wm_filters.append(f"colorchannelmixer=aa={clamped_opacity:.2f}")
        wm_chain = ",".join(wm_filters)
        filter_complex = f"[1:v]{wm_chain}[wm];[0:v][wm]overlay={x}:{y}[out]"

    return [
        "ffmpeg", "-y",
        "-i", in_path,
        "-i", watermark_png,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]


def _build_crop_args(src_w: int, src_h: int, out_path: str, ratio: CropRatio,
                     in_path: str) -> list:
    """Construct ffmpeg args for a centered crop to ``ratio``.

    Computes W:H:X:Y with W,H centered on the source and reduced to even
    pixel counts (ffmpeg wants yuv420p-friendly even dims). Never upscales
    -- if source smaller than target, clamps to source.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"Invalid source dimensions: {src_w}x{src_h}")
    target_w, target_h = {
        "9:16": (9, 16),
        "1:1":  (1, 1),
        "4:5":  (4, 5),
    }.get(ratio, (0, 0))
    if target_w == 0:
        raise ValueError(f"Unknown crop ratio: {ratio}")

    h = src_h
    w = int(h * target_w / target_h)
    if w > src_w:
        w = src_w
        h = int(w * target_h / target_w)
    w -= w % 2
    h -= h % 2
    if w <= 0 or h <= 0:
        raise ValueError(f"crop collapsed to {w}x{h} for {src_w}x{src_h} @ {ratio}")

    x = (src_w - w) // 2
    y = (src_h - h) // 2
    crop_filter = f"crop={w}:{h}:{x}:{y}"
    return ["ffmpeg", "-y", "-i", in_path, "-vf", crop_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", out_path]


# ── Entry fns (call subprocess) ─────────────────────────────────────────────

def trim_clip(in_path: str, out_path: str, start_s: float, end_s: float) -> str:
    """Lossless trim first; fall back to re-encode if -c copy fails."""
    if not os.path.exists(in_path):
        raise FileNotFoundError(in_path)
    for lossless in (True, False):
        cmd = _build_trim_args(in_path, out_path, start_s, end_s, lossless=lossless)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    raise RuntimeError(f"trim_clip failed for {in_path} ({start_s}-{end_s}s)")


def watermark_clip(in_path: str, out_path: str, watermark_png: str,
                   position: WatermarkPosition = "bottom-right",
                   opacity: float = 1.0,
                   scale: float = None) -> str:
    """Overlay ``watermark_png`` onto ``in_path`` at ``position`` corner with ``opacity``.

    Probes both the source video and the PNG via ffprobe to compute the
    X:Y placement for the chosen corner, then calls ffmpeg ``overlay``.
    """
    if not os.path.exists(in_path):
        raise FileNotFoundError(in_path)
    if not os.path.exists(watermark_png):
        raise FileNotFoundError(watermark_png)
    src_w, src_h = _probe_dimensions(in_path)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"watermark_clip: could not probe dimensions of {in_path}")
    wm_w, wm_h = _probe_dimensions(watermark_png)
    if wm_w == 0 or wm_h == 0:
        raise RuntimeError(f"watermark_clip: could not probe dimensions of {watermark_png}")
    cmd = _build_watermark_overlay_args(
        in_path, out_path, watermark_png,
        src_w, src_h, wm_w, wm_h, position,
        opacity=opacity, scale=scale
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"watermark_clip failed: {proc.stderr[-300:]}")
    return out_path


def crop_clip(in_path: str, out_path: str, ratio: CropRatio) -> str:
    """Center-crop ``in_path`` to ``ratio`` and re-encode to ``out_path``."""
    if not os.path.exists(in_path):
        raise FileNotFoundError(in_path)
    src_w, src_h = _probe_dimensions(in_path)
    if src_w == 0 or src_h == 0:
        raise RuntimeError(f"crop_clip: could not probe dimensions of {in_path}")
    cmd = _build_crop_args(src_w, src_h, out_path, ratio, in_path)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"crop_clip failed: {proc.stderr[-300:]}")
    return out_path
