"""Caption placement: "below" lands captions in the zone under the 1:1 video
box so they never cover clip content (owner decision 2026-08-18).

Layout constants under test (clipper.py):
  box top zone     y=0..320    (header overlays)
  video square     y=320..1400 (1080x1080)
  caption zone     y=1400..1920 (reserved, now used by "below")
"""
import os

from shorts_generator import clipper

FONT = os.path.join(os.path.dirname(__file__), "..", "shorts_generator", "assets", "BebasNeue-Regular.ttf")

WORDS = [
    {"word": "this", "start": 0.0, "end": 0.2},
    {"word": "is", "start": 0.2, "end": 0.35},
    {"word": "the", "start": 0.35, "end": 0.5},
    {"word": "secret", "start": 0.5, "end": 0.9},
]


def _ass_style(tmp_path, position, layout_mode="box"):
    out = str(tmp_path / "subs.ass")
    clipper._generate_ass(WORDS, out, 1080, 1920, time_offset=0.0,
                          position=position, layout_mode=layout_mode,
                          caption_font="bebas", header_font="bebas",
                          hook_font="bebas")
    with open(out, encoding="utf-8") as f:
        content = f.read()
    for line in content.splitlines():
        if line.startswith("Style: Main,"):
            fields = line.split(",")
            # ASS V4+ Style: ...,Alignment(idx 18),MarginL(19),MarginR(20),MarginV(21)
            return int(fields[18]), int(fields[21])
    raise AssertionError("Style: Main line missing from generated ASS")


def test_below_places_captions_under_video_box(tmp_path):
    align, margin_v = _ass_style(tmp_path, "Below")
    assert align == 8  # top-center anchor so MarginV is a top offset
    # 1430 = box bottom (1400) + 30px gap — inside the 1400..1920 caption zone
    assert margin_v == clipper.LAYOUT_VIDEO_Y + clipper.LAYOUT_VIDEO_SIZE + 30
    assert margin_v > 1400


def test_below_falls_back_to_on_video_in_portrait_layout(tmp_path):
    # Portrait fills the whole 1080x1920 canvas; there is no zone below the
    # video, so "below" must behave like the classic bottom-on-video position.
    align, margin_v = _ass_style(tmp_path, "Below", layout_mode="portrait")
    assert align == 2
    assert margin_v == 560


def test_bottom_keeps_legacy_on_video_position(tmp_path):
    align, margin_v = _ass_style(tmp_path, "Bottom")
    assert align == 2
    assert margin_v == 560


def test_top_unchanged(tmp_path):
    align, margin_v = _ass_style(tmp_path, "Top")
    assert align == 8
    assert margin_v == 360


def test_default_position_is_below(tmp_path):
    # No position passed -> default must be the new below-box placement.
    out = str(tmp_path / "subs_default.ass")
    clipper._generate_ass(WORDS, out, 1080, 1920, time_offset=0.0,
                          layout_mode="box",
                          caption_font="bebas", header_font="bebas",
                          hook_font="bebas")
    with open(out, encoding="utf-8") as f:
        content = f.read()
    # align 8 with MarginV 1430 in the Main style line
    main_line = next(l for l in content.splitlines() if l.startswith("Style: Main,"))
    assert ",8,40,40,1430,1" in main_line, main_line


def test_server_defaults_request_below():
    from server.main import RenderRequest, BulkRenderRequest
    assert RenderRequest(clip_id=0).caption_pos == "Below"
    assert BulkRenderRequest().caption_pos == "Below"
