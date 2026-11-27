"""Unit tests for shorts_generator.editor (Chunk D1).

Stub subprocess so tests never invoke ffmpeg. Focus is on pure arg
construction (the builders) plus the defensive branches in the entry
fns (missing file, empty text, probe failure, trim re-encode fallback).
"""
import os
import sys
import json
from unittest import mock

import pytest

from shorts_generator import editor


# ── _build_trim_args ───────────────────────────────────────────────────────

def test_build_trim_args_lossless():
    cmd = editor._build_trim_args("in.mp4", "out.mp4", 1.5, 3.0, lossless=True)
    assert cmd[0] == "ffmpeg" and "-y" in cmd
    assert "-ss" in cmd and "1.5" == cmd[cmd.index("-ss") + 1]
    assert "-to" in cmd and "3.0" == cmd[cmd.index("-to") + 1]
    assert "-c" in cmd and "copy" == cmd[cmd.index("-c") + 1]
    assert cmd[-1] == "out.mp4"


def test_build_trim_args_reencode():
    cmd = editor._build_trim_args("in.mp4", "out.mp4", 0.0, 10.0, lossless=False)
    assert "-c:v" in cmd and "libx264" == cmd[cmd.index("-c:v") + 1]
    assert "-c:a" in cmd and "aac" == cmd[cmd.index("-c:a") + 1]
    assert "copy" not in cmd  # not the lossless branch


@pytest.mark.parametrize("start,end", [(-1, 5), (0, 0), (5, 1), (3, 3)])
def test_build_trim_args_rejects_invalid_range(start, end):
    with pytest.raises(ValueError):
        editor._build_trim_args("in.mp4", "out.mp4", start, end)


# ── _build_watermark_overlay_args ──────────────────────────────────────────

@pytest.mark.parametrize("position, expected_x, expected_y", [
    ("top-left",     20,                       20),
    ("top-right",    1920 - 100 - 20,          20),
    ("bottom-left",  20,                       1080 - 50 - 20),
    ("bottom-right", 1920 - 100 - 20,          1080 - 50 - 20),
])
def test_build_watermark_overlay_args_position_corners(position, expected_x, expected_y):
    """Each corner places the watermark at the right X:Y with the 20px margin."""
    cmd = editor._build_watermark_overlay_args(
        "in.mp4", "out.mp4", "wm.png",
        src_w=1920, src_h=1080, wm_w=100, wm_h=50,
        position=position,
    )
    assert cmd[0] == "ffmpeg"
    # filter_complex is one arg after -filter_complex.
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.startswith("[0:v][1:v]overlay=")
    # overlay=X:Y[out] -- parse the X:Y from inside the overlay=...[out] wrapper.
    coords = fc.split("overlay=", 1)[1].split("[out]")[0]
    x_str, y_str = coords.split(":")
    assert int(x_str) == expected_x
    assert int(y_str) == expected_y
    # both inputs must be present
    assert "-i" in cmd
    assert "in.mp4" in cmd and "wm.png" in cmd
    # audio mapped through unchanged
    assert "0:a?" in cmd
    assert "copy" in cmd


def test_build_watermark_overlay_args_unknown_position_rejected():
    with pytest.raises(ValueError, match="Unknown watermark position"):
        editor._build_watermark_overlay_args(
            "in.mp4", "out.mp4", "wm.png",
            src_w=1920, src_h=1080, wm_w=100, wm_h=50,
            position="middle-left",
        )


def test_build_watermark_overlay_args_rejects_invalid_src_dims():
    with pytest.raises(ValueError, match="Invalid source dimensions"):
        editor._build_watermark_overlay_args(
            "in.mp4", "out.mp4", "wm.png",
            src_w=0, src_h=0, wm_w=10, wm_h=10,
            position="top-left",
        )


def test_build_watermark_overlay_args_rejects_invalid_wm_dims():
    with pytest.raises(ValueError, match="Invalid watermark dimensions"):
        editor._build_watermark_overlay_args(
            "in.mp4", "out.mp4", "wm.png",
            src_w=1920, src_h=1080, wm_w=0, wm_h=0,
            position="top-left",
        )


def test_build_watermark_overlay_args_rejects_watermark_larger_than_source():
    """A PNG bigger than the source frame is nonsensical -- raise."""
    with pytest.raises(ValueError, match="larger than source"):
        editor._build_watermark_overlay_args(
            "in.mp4", "out.mp4", "wm.png",
            src_w=100, src_h=100, wm_w=200, wm_h=50,
            position="top-left",
        )


def test_build_watermark_overlay_args_uses_custom_margin():
    """Callers can override the default 20px margin."""
    cmd = editor._build_watermark_overlay_args(
        "in.mp4", "out.mp4", "wm.png",
        src_w=1920, src_h=1080, wm_w=100, wm_h=50,
        position="top-left", margin=5,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    coords = fc.split("overlay=", 1)[1].split("[out]")[0]
    x_str, y_str = coords.split(":")
    assert int(x_str) == 5 and int(y_str) == 5



# ── _build_crop_args ───────────────────────────────────────────────────────

def test_build_crop_args_9_16_on_landscape_centered():
    # 1920x1080 source, target 9:16 -> keep height 1080, width = 607.5 -> 606
    cmd = editor._build_crop_args(1920, 1080, "out.mp4", "9:16", "in.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    # crop=W:H:X:Y -- W,H even (yuv420p), x,y just need to be valid offsets
    assert vf.startswith("crop=")
    w, h, x, y = (int(p) for p in vf.split("=", 1)[1].split(":"))
    assert w % 2 == 0 and h % 2 == 0          # yuv420p needs even dims
    assert x >= 0 and y >= 0
    assert x + w <= 1920 and y + h <= 1080    # crop fits inside source
    # width reduction for 9:16 from 1920 width: w <= 1920, h = 1080
    assert h == 1080
    assert abs(w - 607) <= 1  # 1080 * 9/16 = 607.5 -> floored to 606
    # centered on x: (1920 - w) // 2 -- y is 0 since h == src_h
    assert x == (1920 - w) // 2
    assert y == 0


def test_build_crop_args_1_1_square_from_portrait():
    # 720x1280 source portrait, target 1:1 -> keep width 720, h = 720
    cmd = editor._build_crop_args(720, 1280, "out.mp4", "1:1", "in.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    parts = vf.split("=", 1)[1].split(":")
    w, h, x, y = (int(p) for p in parts)
    assert w == 720 and h == 720
    assert x == 0
    assert y == (1280 - 720) // 2


def test_build_crop_args_4_5_narrower_than_9_16():
    # 1080x1920 portrait. 4:5 target. limiter = width 1080, h = 1080 * 5/4 = 1350
    cmd = editor._build_crop_args(1080, 1920, "out.mp4", "4:5", "in.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    w, h, x, y = (int(p) for p in vf.split("=", 1)[1].split(":"))
    assert w == 1080 and h == 1350
    assert x == 0
    assert y == (1920 - 1350) // 2


def test_build_crop_args_never_upscales_small_source():
    # source smaller than 'natural' target -- must clamp to source.
    # 360x360 @ 9:16 would naturally want w=202 h=360 -> already fits.
    # but 100x100 @ 9:16 -> w=56 h=100, fits. Smoke the clamp path.
    cmd = editor._build_crop_args(100, 100, "out.mp4", "1:1", "in.mp4")
    parts = cmd[cmd.index("-vf") + 1].split("=", 1)[1].split(":")
    w, h = int(parts[0]), int(parts[1])
    assert w <= 100 and h <= 100


def test_build_crop_args_unknown_ratio_rejected():
    with pytest.raises(ValueError):
        editor._build_crop_args(1920, 1080, "out.mp4", "16:9", "in.mp4")


def test_build_crop_args_invalid_dims_rejected():
    with pytest.raises(ValueError):
        editor._build_crop_args(0, 0, "out.mp4", "9:16", "in.mp4")


# ── Entry fns (mocked subprocess) ───────────────────────────────────────────

def test_trim_clip_raises_on_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        editor.trim_clip(str(tmp_path / "nope.mp4"), str(tmp_path / "o.mp4"), 0, 1)


def test_trim_clip_lossless_succeeds_first_try(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"
    in_p.write_bytes(b"x" * 100)
    out_p = tmp_path / "out.mp4"

    calls = []
    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        # Pretend the first invocation (lossless=True) succeeded: write out_p.
        if "-c" in cmd and "copy" in cmd:
            out_p.write_bytes(b"trimmed")
        class _P:
            returncode = 0
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)

    # No mock on os.path — the fake_run above actually wrote the file, so
    # os.path.exists(out_p) and os.path.getsize(out_p) return real values.
    result = editor.trim_clip(str(in_p), str(out_p), 1.0, 2.0)
    assert result == str(out_p)
    assert len(calls) == 1   # fallback NOT triggered


def test_trim_clip_falls_back_to_reencode(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"
    in_p.write_bytes(b"x" * 100)
    out_p = tmp_path / "out.mp4"

    call_count = {"lossless": 0, "reencode": 0}
    def fake_run(cmd, *args, **kwargs):
        is_lossless = "-c" in cmd and "copy" == cmd[cmd.index("-c") + 1]
        if is_lossless:
            call_count["lossless"] += 1
            # Pretend lossless failed -- no output written, returncode!=0.
            class _P:
                returncode = 1
                stderr = "fake codec mismatch"
            return _P()
        call_count["reencode"] += 1
        out_p.write_bytes(b"reencoded")
        class _P:
            returncode = 0
            stderr = ""
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)

    # os.path.exists needs to return True for in_p, True for out_p only after
    # the reencode call. Use a wrapper that just falls back to the real fn.
    result = editor.trim_clip(str(in_p), str(out_p), 1.0, 2.0)
    assert result == str(out_p)
    assert call_count["lossless"] == 1
    assert call_count["reencode"] == 1


def test_watermark_clip_raises_on_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        editor.watermark_clip(
            str(tmp_path / "nope.mp4"),
            str(tmp_path / "o.mp4"),
            str(tmp_path / "wm.png"),
        )


def test_watermark_clip_raises_on_missing_png(tmp_path):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    with pytest.raises(FileNotFoundError):
        editor.watermark_clip(
            str(in_p),
            str(tmp_path / "o.mp4"),
            str(tmp_path / "nope.png"),
        )


def test_watermark_clip_probe_failure_on_video_raises(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    wm_p = tmp_path / "wm.png"; wm_p.write_bytes(b"PNG" * 10)
    monkeypatch.setattr(
        "shorts_generator.editor._probe_dimensions",
        lambda p: (1280, 720) if p == str(wm_p) else (0, 0),
    )
    with pytest.raises(RuntimeError, match="probe"):
        editor.watermark_clip(str(in_p), str(tmp_path / "o.mp4"), str(wm_p))


def test_watermark_clip_probe_failure_on_png_raises(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    wm_p = tmp_path / "wm.png"; wm_p.write_bytes(b"PNG" * 10)
    monkeypatch.setattr(
        "shorts_generator.editor._probe_dimensions",
        lambda p: (1280, 720) if p == str(in_p) else (0, 0),
    )
    with pytest.raises(RuntimeError, match="probe"):
        editor.watermark_clip(str(in_p), str(tmp_path / "o.mp4"), str(wm_p))


def test_watermark_clip_passes_png_path_to_ffmpeg(tmp_path, monkeypatch):
    """Entry fn invokes ffmpeg with -i in -i wm.png -filter_complex overlay."""
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    wm_p = tmp_path / "wm.png"; wm_p.write_bytes(b"PNG" * 10)
    out_p = tmp_path / "out.mp4"
    captured_cmd = []

    monkeypatch.setattr(
        "shorts_generator.editor._probe_dimensions",
        lambda p: (1920, 1080) if p == str(in_p) else (200, 60),
    )
    def fake_run(cmd, *args, **kwargs):
        captured_cmd.append(cmd)
        out_p.write_bytes(b"watermarked")
        class _P:
            returncode = 0
            stderr = ""
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)

    result = editor.watermark_clip(
        str(in_p), str(out_p), str(wm_p),
        position="bottom-right",
    )
    assert result == str(out_p)
    cmd = captured_cmd[0]
    # The video and the PNG are both passed as -i inputs.
    assert cmd.count("-i") == 2
    assert str(in_p) in cmd and str(wm_p) in cmd
    # The filter_complex overlay maps to [out] and we map "[out]" + "0:a?".
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc.startswith("[0:v][1:v]overlay=")
    assert fc.endswith("[out]")
    assert "[out]" in cmd[cmd.index("-map") + 1:]
    # No drawtext path -- the codepath going forward is overlay-only.
    assert "drawtext" not in " ".join(cmd)


def test_watermark_clip_failure_raises(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    wm_p = tmp_path / "wm.png"; wm_p.write_bytes(b"PNG" * 10)
    out_p = tmp_path / "out.mp4"

    monkeypatch.setattr(
        "shorts_generator.editor._probe_dimensions",
        lambda p: (1920, 1080) if p == str(in_p) else (200, 60),
    )
    def fake_run(cmd, *args, **kwargs):
        class _P:
            returncode = 1
            stderr = "ffmpeg overlay died"
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="watermark_clip failed"):
        editor.watermark_clip(str(in_p), str(out_p), str(wm_p))



def test_crop_clip_raises_on_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        editor.crop_clip(str(tmp_path / "nope.mp4"), "o.mp4", "1:1")


def test_crop_clip_probe_failure_raises(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    # probe returns (0,0) -> entry fn raises RuntimeError
    monkeypatch.setattr("shorts_generator.editor._probe_dimensions", lambda p: (0, 0))
    with pytest.raises(RuntimeError, match="probe"):
        editor.crop_clip(str(in_p), str(tmp_path / "o.mp4"), "1:1")


def test_crop_clip_success_invokes_ffmpeg_with_built_filter(tmp_path, monkeypatch):
    in_p = tmp_path / "in.mp4"; in_p.write_bytes(b"x" * 100)
    out_p = tmp_path / "out.mp4"
    captured_cmd = []

    monkeypatch.setattr("shorts_generator.editor._probe_dimensions", lambda p: (1080, 1080))
    def fake_run(cmd, *args, **kwargs):
        captured_cmd.append(cmd)
        out_p.write_bytes(b"cropped")
        class _P:
            returncode = 0
            stderr = ""
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)

    result = editor.crop_clip(str(in_p), str(out_p), "1:1")
    assert result == str(out_p)
    # The crop filter for 1080x1080 @ 1:1 should keep full source (since it's already square).
    vf = captured_cmd[0][captured_cmd[0].index("-vf") + 1]
    assert vf == "crop=1080:1080:0:0"


def test_probe_dimensions_returns_zero_on_ffprobe_failure(monkeypatch):
    """If ffprobe exits non-zero or JSON parse fails, return (0,0) not a raise."""
    def fake_run(cmd, *args, **kwargs):
        class _P:
            returncode = 1
            stdout = "garbled"
            stderr = "no such file"
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)
    assert editor._probe_dimensions("nope.mp4") == (0, 0)


def test_probe_dimensions_returns_dims_on_success(monkeypatch):
    def fake_run(cmd, *args, **kwargs):
        class _P:
            returncode = 0
            stdout = json.dumps({"streams": [{"width": 1280, "height": 720}]})
            stderr = ""
        return _P()
    monkeypatch.setattr("subprocess.run", fake_run)
    assert editor._probe_dimensions("in.mp4") == (1280, 720)
