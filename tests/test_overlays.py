import os
import pytest
from PIL import Image, ImageDraw
from shorts_generator import overlays

FONT = os.path.join(os.path.dirname(__file__), "..", "shorts_generator", "assets", "BebasNeue-Regular.ttf")

def test_fit_lines_short_text_one_line():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, font = overlays.fit_lines(draw, "RCMP CALL", FONT, max_w=960, max_h=240)
    assert lines == ["RCMP CALL"]
    assert font.size <= overlays.MAX_FONT

def test_fit_lines_long_text_wraps_to_two_and_fits():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    text = "YOUR FRIEND'S FIRE IS OUT OF CONTROL"
    lines, font = overlays.fit_lines(draw, text, FONT, max_w=960, max_h=240)
    assert 1 <= len(lines) <= 2
    for ln in lines:
        w = draw.textbbox((0, 0), ln, font=font, stroke_width=12)[2]
        assert w <= 960            # never overflows the safe width
    assert font.size >= overlays.MIN_FONT

def test_fit_lines_respects_min_font_floor():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    # Very long header — would normally shrink small; floor at 52.
    text = "THE ONE MONEY RULE NOBODY EVER TELLS YOU ABOUT"
    lines, font = overlays.fit_lines(draw, text, FONT, max_w=960, max_h=240,
                                     min_font_size=52)
    assert font.size >= 52

# ── preset registry + keyword picker ──────────────────────────────────────────

def test_pick_keyword_prefers_trigger_word():
    # "SECRET" is a trigger word -> it should be the accent index
    words = ["DAD'S", "FIRECRACKER", "SECRET"]
    assert overlays.pick_keyword(words) == 2

def test_pick_keyword_falls_back_to_last_word():
    words = ["PARENTS", "ARE", "WEIRD"]
    assert overlays.pick_keyword(words) == 2

# ── multi-color accent picker ────────────────────────────────────────────────

def test_pick_accent_indices_selects_multiple_triggers():
    words = ["MONEY", "RULES", "AND", "THE", "SECRET"]
    idx = overlays.pick_accent_indices(words)
    assert idx == [0, 1, 4]  # MONEY, RULES, SECRET (AND/THE don't qualify)

def test_pick_accent_indices_caps_at_max():
    words = ["MONEY", "SECRET", "TRUTH", "CRAZY", "HUGE"]
    idx = overlays.pick_accent_indices(words, max_accented=3)
    assert len(idx) == 3
    assert idx == [0, 1, 2]  # first qualifying, cap applied

def test_pick_accent_indices_digits_qualify():
    words = ["THE", "1000", "DOLLAR", "GAME"]
    idx = overlays.pick_accent_indices(words)
    assert 1 in idx

def test_pick_accent_indices_falls_back_to_last_word():
    words = ["PARENTS", "ARE", "WEIRD"]
    assert overlays.pick_accent_indices(words) == [2]

def test_accent_color_is_deterministic_per_word():
    a = overlays.accent_color("money", (255, 255, 255), seed=0)
    b = overlays.accent_color("money", (255, 255, 255), seed=0)
    assert a == b

def test_accent_color_seed_rotates_palette():
    # Same word, different seeds -> colors shift along the palette (they may
    # collide modulo palette size, so check a spread over all seeds instead).
    cols = {overlays.accent_color("money", (255, 255, 255), seed=s)
            for s in range(len(overlays.ACCENT_PALETTE))}
    assert len(cols) == len(overlays.ACCENT_PALETTE)

def test_accent_color_keeps_distance_from_base_text():
    # On the all-yellow bold-caps-yellow preset (base text near yellow),
    # the yellow palette entry must be excluded so accents stay visible.
    base = (255, 209, 0)
    for _ in range(20):
        col = overlays.accent_color("secret", base, seed=_)
        assert overlays._rgb_distance(col, base) >= overlays._ACCENT_MIN_DIST

# ── rendered headers contain multi-color accents ─────────────────────────────

def test_rendered_header_contains_palette_accent_pixels(tmp_path):
    out = str(tmp_path / "multi.png")
    # Four trigger words present -> up to 3 get accented.
    overlays.render_overlay_png("MONEY RULES THE SECRET", "rounded-chunky", FONT,
                                out_path=out, accent_seed=0)
    im = Image.open(out)
    opaque = {(r, g, b) for r, g, b, a in im.getdata() if a >= 200}
    palette_hits = [c for c in opaque
                    if c in overlays.ACCENT_PALETTE
                    and overlays._rgb_distance(c, (255, 255, 255)) >= overlays._ACCENT_MIN_DIST]
    assert palette_hits, f"no palette accent pixels found; got {len(opaque)} distinct colors"

def test_rendered_header_deterministic_with_fixed_seed(tmp_path):
    a = str(tmp_path / "a.png")
    b = str(tmp_path / "b.png")
    for out in (a, b):
        overlays.render_overlay_png("THE MONEY SECRET", "rounded-chunky", FONT,
                                    out_path=out, accent_seed=2)
    assert list(Image.open(a).getdata()) == list(Image.open(b).getdata())

# ── render PNG per preset ─────────────────────────────────────────────────────


def test_presets_exist():
    assert set(overlays.HEADER_PRESETS) == {
        "italic-serif", "rounded-chunky", "bold-caps-yellow",
        "minimal-clean", "dark-pill", "cyber-pill", "luxury-gold",
    }
    for p in overlays.HEADER_PRESETS.values():
        assert {"container", "text", "keyword"} <= set(p)


@pytest.mark.parametrize("preset", list(overlays.HEADER_PRESETS))
def test_render_overlay_png(tmp_path, preset):
    out = str(tmp_path / f"{preset}.png")
    p = overlays.render_overlay_png("PARENTS ARE CRAZY", preset, FONT, out_path=out)
    assert p == out
    im = Image.open(out)
    assert im.mode == "RGBA"
    assert im.size == (overlays.ZONE_W, overlays.ZONE_H)
    # something was actually drawn (alpha not fully zero)
    assert im.getextrema()[3][1] > 0


def test_render_overlay_long_text_does_not_raise(tmp_path):
    out = str(tmp_path / "long.png")
    overlays.render_overlay_png("YOUR FRIEND'S FIRE IS OUT OF CONTROL", "rounded-chunky", FONT, out_path=out)
    assert Image.open(out).size == (overlays.ZONE_W, overlays.ZONE_H)


def test_card_text_stays_opaque_when_background_is_transparent(tmp_path):
    # Preset backgrounds are transparent; opacity is informational only.
    # Text must still reach full alpha (255). Before the fix the whole
    # layer was multiplied, so max alpha capped near 127.
    out = str(tmp_path / "hook.png")
    overlays.render_overlay_png("PARENTS ARE CRAZY", "rounded-chunky", FONT,
                                out_path=out, opacity=0.5)
    im = Image.open(out)
    max_alpha = im.getextrema()[3][1]
    assert max_alpha == 255


def test_legacy_card_stroke_aliases_route_to_real_presets(tmp_path):
    # "card" / "stroke" are not dict keys anymore (Session 9 reorg) but
    # render_overlay_png must still accept them via the backward-compat
    # branch so older settings.json / seed state keeps rendering.
    # "news-bar" was retired 2026-08-18 (owner decision) and must also
    # keep rendering via the same compat branch.
    for legacy, expected in (("card", "rounded-chunky"), ("stroke", "italic-serif"),
                             ("news-bar", "rounded-chunky")):
        out = str(tmp_path / f"{legacy}.png")
        overlays.render_overlay_png("PARENTS ARE CRAZY", legacy, FONT, out_path=out)
        assert Image.open(out).size == (overlays.ZONE_W, overlays.ZONE_H)


@pytest.mark.parametrize("preset", ["italic-serif", "rounded-chunky", "bold-caps-yellow", "minimal-clean", "dark-pill"])
def test_render_overlay_alpha_nonzero_for_each_shipped_preset(tmp_path, preset):
    # Regression guard: every preset advertised in the UI picker (page.tsx)
    # must produce a non-empty PNG. Prevents the "dead thumbnail"
    # recurrence that motivated render_header_thumbnails.py.
    out = str(tmp_path / f"{preset}.png")
    overlays.render_overlay_png("THE SECRET NOBODY TELLS YOU", preset, FONT, out_path=out)
    im = Image.open(out)
    assert im.getextrema()[3][1] > 0


# ── casing option ─────────────────────────────────────────────────────────────

def test_fit_lines_defaults_to_upper():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "stay hungry", FONT)
    assert " ".join(lines) == "STAY HUNGRY"


def test_fit_lines_title_case():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "when you surprise your girlfriend",
                                      FONT, casing="title")
    assert " ".join(lines) == "When You Surprise Your Girlfriend"


def test_fit_lines_title_case_keeps_apostrophes():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "don't quit your job", FONT,
                                      casing="title")
    assert " ".join(lines) == "Don't Quit Your Job"
