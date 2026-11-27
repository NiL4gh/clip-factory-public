"""Face tracking unit tests (Cinematic Deadband Smooth Glide).

Covers scale geometry, deadband smoothing, FFmpeg continuous crop
expression serialization, and per-video detection caching.
"""
import pytest

from shorts_generator import face_tracker as ft


# ── scale geometry ────────────────────────────────────────────────────────────

def test_scaled_width_landscape_grows_beyond_square():
    # 16:9 landscape scaled into a 1080x1080 cover box becomes full-width.
    assert ft.scaled_width(1080, 1920, 1080) == 1920


def test_scaled_width_portrait_stays_square_width():
    assert ft.scaled_width(1080, 1080, 1920) == 1080


def test_scaled_width_unknown_dims_uses_target():
    assert ft.scaled_width(1080, 0, 0) == 1080


def test_scaled_width_even_rounding():
    # Non-even result rounds up so yuv420p stays valid downstream.
    w = ft.scaled_width(1134, 1600, 900)  # a 16:9-ish source
    assert w % 2 == 0


def test_default_crop_x_centers():
    # For a wide landscape source the centered crop is pulled right to middle.
    assert ft.default_crop_x(1080, 1920, 1080) == 420


def test_scaled_width_portrait_layout_mode():
    # In portrait mode (1080x1920 target), a 1920x1080 landscape source scales
    # to cover height 1920: scale factor = 1920/1080 = 1.7778.
    # Scaled width = 1920 * (1920/1080) = 3414 px (even-rounded).
    w = ft.scaled_width(1080, 1920, 1080, scale_target_h=1920)
    assert w == 3414
    # Centered crop in portrait mode centers 1080 inside 3414:
    assert (w - 1080) // 2 == 1167



# ── crop expression serialization ─────────────────────────────────────────────

def test_landscape_scaled_frame_uses_real_width_not_target():
    """REGRESSION (C50): box layout uses force_original_aspect_ratio=increase,
    so scale=1124:1124 on a 1920x1080 source produces a 1998x1124 frame
    (probed against the real ffmpeg binary), NOT 1124 wide. A centered face
    (x=960 in source px) must map to the real frame center, and the no-track
    fallback must agree."""
    frame_w = ft.scaled_width(1124, 1920, 1080)
    assert frame_w == 1998  # ffmpeg-verified actual post-scale width
    centered_x = (frame_w - 1080) // 2  # 459
    assert ft.default_crop_x(1124, 1920, 1080) == centered_x
    # Centered face in source px -> centered crop in the real frame:
    track = [(0.0, 960.0), (1.0, 960.0)]
    assert ft.crop_expression(track, 0.0, frame_w, 1920, 1080) == str(centered_x)
    # No-track fallback must land on the same center (not a literal 0/edge):
    assert ft.crop_expression([], 0.0, frame_w, 1920, 1080) == str(centered_x)


def test_portrait_scaled_frame_keeps_square_width():
    # Portrait sources scale to exactly the target width -> math unchanged.
    frame_w = ft.scaled_width(1124, 1080, 1920)
    assert frame_w == 1124
    centered_x = (1124 - 1080) // 2  # 22 — here the target IS the frame width
    assert ft.crop_expression([], 0.0, frame_w, 1080, 1920) == str(centered_x)
    # Centered face -> centered crop:
    assert ft.crop_expression([(0.0, 540.0), (1.0, 540.0)], 0.0, frame_w, 1080, 1920) == str(centered_x)


def test_crop_expression_term_count_is_capped_for_noisy_tracks():
    """Noisy real footage produces deadband-stabilized continuous glides.
    Verifies that terms are compact and within budget."""
    import random as _r
    _r.seed(7)
    # 45s clip: detections of speaker moving across stage
    samples = [(t * 0.5, 800.0 + (500.0 / 90.0) * t * 0.5 + _r.uniform(-15, 15))
               for t in range(0, 180)]
    track = ft.smooth_track(samples, 0.0, 45.0, 30.0)
    frame_w = ft.scaled_width(1126, 1920, 1080)  # 1998 — real post-scale width
    expr = ft.crop_expression(track, 0.0, frame_w, 1920, 1080)
    # Continuous clip() terms are compact
    assert expr.count("clip(") <= ft.MAX_EXPR_STEPS


def test_crop_expression_empty_returns_centered_default():
    assert ft.crop_expression([], 0.0, 1920, 1920, 1080) == "420"


def test_crop_expression_flat_track_returns_single_offset():
    # Face pinned to the frame's center -> static centered crop offset.
    track = [(0.0, 960.0), (2.0, 960.0)]
    assert ft.crop_expression(track, 0.0, 1920, 1920, 1080) == "420"


def test_crop_expression_emits_smooth_glides_for_motion():
    # Face travels left->right; expect continuous smooth clip glide.
    track = ft.smooth_track([(0.0, 600.0), (1.0, 1400.0), (2.0, 1400.0)], 0.0, 2.0, 30.0)
    expr = ft.crop_expression(track, 0.0, 1920, 1920, 1080)
    assert "clip(" in expr


def test_crop_expression_clamps_to_crop_range():
    # Face far off-frame must not move the crop beyond [0, scale_w-1080].
    track = [(0.0, 50.0), (1.0, 4000.0)]  # huge rightward swing
    expr = ft.crop_expression(track, 0.0, 1920, 1920, 1080)
    assert "clip(" in expr
    assert ",0,840)" in expr.replace("\\", "")


# ── smoothing + deadband ──────────────────────────────────────────────────────

def test_smooth_track_empty_input():
    assert ft.smooth_track([], 0.0, 5.0, 30.0) == []


def test_smooth_track_respects_time_bounds():
    track = ft.smooth_track([(0.0, 500.0), (1.0, 1200.0)], 0.0, 1.0, 30.0)
    times = [t for t, _ in track]
    assert min(times) >= 0.0
    assert max(times) <= 1.0


def test_smooth_track_glides_smoothly():
    # A hard left->right transition generates a smooth continuous glide
    track = ft.smooth_track([(0.0, 100.0), (2.0, 1200.0)], 0.0, 2.0, 30.0)
    xs = [x for _, x in track]
    assert xs[0] == pytest.approx(100.0, abs=10)
    assert xs[-1] > 100.0


def test_smooth_track_single_sample_is_constant():
    track = ft.smooth_track([(0.5, 900.0)], 0.0, 1.0, 30.0)
    assert track and all(x == pytest.approx(900.0, abs=1.0) for _, x in track)


# ── per-video detection cache ─────────────────────────────────────────────────

def test_detect_center_x_cache_slices_full_video(monkeypatch, tmp_path):
    video = str(tmp_path / "vid.mp4")
    with open(video, "wb") as f:
        f.write(b"fake")

    fake_full = [(0.0, 100.0), (0.5, 110.0), (1.0, 120.0), (1.5, 130.0)]
    calls = {"n": 0}

    def fake_scan(path, start, end):
        calls["n"] += 1
        return fake_full

    monkeypatch.setattr(ft, "_scan_range", fake_scan)
    monkeypatch.setattr(ft, "_video_duration", lambda p: 2.0)
    ft.clear_cache()

    f1 = ft.detect_center_x(video, 0.0, 1.0)
    assert [t for t, _ in f1] == [0.0, 0.5]

    f2 = ft.detect_center_x(video, 0.5, 1.5)
    assert [t for t, _ in f2] == [0.5, 1.0]

    assert calls["n"] == 1  # only one full scan was performed