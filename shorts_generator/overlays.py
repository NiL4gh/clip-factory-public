"""Pillow-rendered header / magic-hook overlays (transparent PNGs).

Replaces the old ASS-drawn header so we get real design (cards, bars, scrims)
and never hit libass font-name fallback (Pillow loads the .ttf file directly).
"""
from PIL import Image, ImageDraw, ImageFont
import random
import zlib

ZONE_W = 1080          # top-zone width  (clipper LAYOUT_VIDEO_SIZE)
ZONE_H = 320           # top-zone height (clipper LAYOUT_TOP_ZONE_H)
SAFE_W = 960           # horizontal safe width (keeps text off the edges / UI)
MAX_FONT = 110
MIN_FONT = 44

# ── Multi-word accent palette ─────────────────────────────────────────────────
# Headers highlight up to a few trigger/number words, each tinted from this
# palette. The same word always gets the same color within a header
# (deterministic per-word hash), and the seed rotates colors across clips.
ACCENT_PALETTE = [
    (255, 209, 0),     # yellow (the classic)
    (255, 0, 200),     # magenta
    (0, 229, 255),     # cyan
    (154, 255, 0),     # lime
    (255, 122, 26),    # orange
]
# Minimum RGB distance an accent color must keep from the preset's base text
# color, so accents never blend into the text (e.g. yellow accent on the
# all-yellow "bold-caps-yellow" preset).
_ACCENT_MIN_DIST = 120


def _apply_casing(text, casing):
    """Collapse whitespace and apply the requested casing.
    'upper' -> ALL CAPS (default; the top header uses this).
    'title' -> Title Case, first letter of each word capitalised, rest lower.
               Implemented per-word so "don't" stays "Don't".
    'none'  -> leave text as-is (only whitespace collapsed)."""
    text = " ".join(text.split())
    if casing == "upper":
        return text.upper()
    if casing == "title":
        return " ".join(w[:1].upper() + w[1:].lower() if w else w
                        for w in text.split(" "))
    return text


def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=0, max_font_size=MAX_FONT, min_font_size=MIN_FONT,
              casing="upper"):
    """Return (lines, font) that fit text into max_w x max_h in <= max_lines,
    shrinking the font until it fits. Greedy word wrap.
    min_font_size floors the shrink so long text stays legible."""
    text = _apply_casing(text, casing)
    words = text.split(" ")
    effective_min = max(min_font_size, MIN_FONT)
    for size in range(min(max_font_size, MAX_FONT), effective_min - 1, -2):
        font = ImageFont.truetype(font_path, size)
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            tw = draw.textlength(trial, font=font)
            if tw <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            widest = max(draw.textlength(ln, font=font) for ln in lines)
            line_h = font.size + 14
            if widest <= max_w and line_h * len(lines) <= max_h:
                return lines, font
    font = ImageFont.truetype(font_path, effective_min)
    return ([text] if len(words) == 1 else [" ".join(words[:len(words)//2]),
            " ".join(words[len(words)//2:])]), font


# ── Header style presets ─────────────────────────────────────────
# Randomized header styles. The clipper picks one per-clip via render_settings
# so we get visual variety without manual picking.
#
# Accent words (triggers / digits — see _TRIGGERS) are tinted from
# ACCENT_PALETTE with per-word deterministic colors that rotate across
# clips (accent_seed). Pill presets get the same multi-color treatment.
#
# "italic-serif":    italic serif stack with a soft drop shadow, no box.
#                    Looks like a Netflix/YT "now playing" card. Title-cased.
# "rounded-chunky":  Montserrat-bold rounded sans, no box, no shadow.
#                    Looks like MrBeast/MKBHD static caption. ALL CAPS.
HEADER_PRESETS = {
    # Italic serif, white text with soft black drop shadow. Transparent.
    "italic-serif": {
        "container": "none",
        "text": (255, 255, 255),
        "keyword": (255, 209, 0),     # yellow accent
        "stroke": 0,
        "shadow": (0, 0, 0),
        "shadow_offset": (4, 4),
        "shadow_alpha": 160,
        "font_family": "serif_italic",
        "casing": "title",
    },
    # Rounded bold sans, white text, transparent. ALL CAPS for impact.
    "rounded-chunky": {
        "container": "none",
        "text": (255, 255, 255),
        "keyword": (255, 209, 0),
        "stroke": 0,
        "shadow": (0, 0, 0),
        "shadow_offset": (4, 4),
        "shadow_alpha": 180,
        "font_family": "rounded_sans",
        "casing": "upper",
    },
    # Bold Montserrat Black, ALL CAPS, yellow text, subtle drop shadow.
    "bold-caps-yellow": {
        "container": "none",
        "text": (255, 209, 0),       # bold yellow primary
        "keyword": (255, 255, 255),  # white highlight
        "stroke": 0,
        "shadow": (0, 0, 0),
        "shadow_offset": (3, 3),
        "shadow_alpha": 180,
        "font_family": "rounded_sans",
        "casing": "upper",
    },
    # Clean editorial: white text, transparent bg, light shadow.
    "minimal-clean": {
        "container": "none",
        "text": (255, 255, 255),
        "keyword": (255, 209, 0),
        "stroke": 0,
        "shadow": (0, 0, 0),
        "shadow_offset": (2, 2),
        "shadow_alpha": 100,
        "font_family": "inter_sans",
        "casing": "title",
    },
    # Dark-pill: sleek dark frosted pill container for viral hook isolation
    "dark-pill": {
        "container": "pill",
        "text": (255, 255, 255),
        "keyword": (255, 209, 0),   # yellow highlight
        "stroke": 0,
        "shadow": None,
        "shadow_offset": (0, 0),
        "shadow_alpha": 0,
        "pill_color": (15, 23, 42, 230),  # slate-900 / 90% opacity
        "pill_padding_x": 36,
        "pill_padding_y": 14,
        "pill_radius": 24,
        "font_family": "rounded_sans",
        "casing": "upper",
    },
    # Cyber-pill: futuristic dark container with neon cyan accent
    "cyber-pill": {
        "container": "pill",
        "text": (255, 255, 255),
        "keyword": (0, 255, 240),   # cyan neon highlight
        "stroke": 0,
        "shadow": None,
        "shadow_offset": (0, 0),
        "shadow_alpha": 0,
        "pill_color": (8, 12, 24, 240),
        "pill_padding_x": 32,
        "pill_padding_y": 14,
        "pill_radius": 16,
        "font_family": "rounded_sans",
        "casing": "upper",
    },
    # Luxury-gold: elegant high-end gold accent header
    "luxury-gold": {
        "container": "none",
        "text": (245, 245, 245),
        "keyword": (245, 195, 65),   # gold highlight
        "stroke": 0,
        "shadow": (0, 0, 0),
        "shadow_offset": (3, 3),
        "shadow_alpha": 180,
        "font_family": "rounded_sans",
        "casing": "title",
    },
}


# Font fallback chain for "italic-serif". Tries project fonts first, then OS fallbacks.
_ITALIC_SERIF_FONT_CANDIDATES = [
    # Project-bundled italic fonts (none yet — kept for future drop-in)
    # OS-fallback candidates
    "C:/Windows/Fonts/georgiaz.ttf",  # Georgia Bold Italic
    "C:/Windows/Fonts/timesbi.ttf",   # Times New Roman Bold Italic
    "C:/Windows/Fonts/cambriaz.ttf",  # Cambria Bold Italic
    "C:/Windows/Fonts/DejaVuSerif-BoldItalic.ttf",
    "C:/Windows/Fonts/NotoSerif-BoldItalic.ttf",
    "C:/Windows/Fonts/LiberationSerif-BoldItalic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold Italic.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf",
]


# Font fallback chain for "minimal-clean" (Inter). Project-bundled, then OS options.
_INTER_FONT_CANDIDATES = [
    "Inter-Bold",
    "Inter",
    "C:/Windows/Fonts/Inter.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/inter/Inter.ttf",
    "/System/Library/Fonts/Inter.ttf",
]

# Font fallback chain for "rounded-chunky". Project-bundled, then OS options.
_CHUNKY_FONT_CANDIDATES = [
    # Project-bundled candidates (filled in from config.AVAILABLE_FONTS at runtime)
    "Montserrat-Black",   # boldest choice
    "Montserrat Bold",    # backup if Black missing (key)
    "Poppins-Bold",
    "Inter-Bold",
    # OS fallback
    "C:/Windows/Fonts/calibrib.ttf",
]


def _resolve_font_path(spec, fallback_path=None):
    """Pick the best font path for the requested style preset.
    spec: HEADER_PRESETS["italic-serif"|"rounded-chunky"]["font_family"].
    Returns a path string that ImageFont.truetype accepts."""
    from pathlib import Path

    family = spec.get("font_family", "")
    if "italic-serif" in family or family == "serif_italic":
        for cand in _ITALIC_SERIF_FONT_CANDIDATES:
            if Path(cand).exists():
                return cand
        # Final fallback: bundled serif-sans (Montserrat) at half-impact — better than crashing
        if fallback_path and Path(fallback_path).exists():
            return fallback_path
        # Last resort: Pillow default
        return None

    if family == "inter_sans":
        for cand in _INTER_FONT_CANDIDATES:
            if Path(cand).exists():
                return cand
        # Fallback: bundled font from clipper
        if fallback_path and Path(fallback_path).exists():
            return fallback_path
        return None

    # Default / "rounded-chunky" / "bold-caps-yellow":
    # use the passed-in fallback path from clipper
    if fallback_path and Path(fallback_path).exists():
        return fallback_path
    return None


# trigger words worth accenting (mirrors clipper._is_header_highlight_target intent)
_TRIGGERS = {"SECRET", "SECRETS", "MISTAKE", "MISTAKES", "FAILED", "FAIL", "FAILS",
             "SHOCKING", "SHOCKED", "RULE", "RULES", "REVENUE", "TRUTH", "VIRAL",
             "MONEY", "EARN", "RICHEST", "RICH", "POOR", "WHOP", "REWARDS",
             "SUCCESS", "SUCCESSFUL", "ONLY", "PRO", "TINY", "HUGE", "FAST", "SLOW",
             "NEVER", "ALWAYS", "FIRE", "DANGER", "DEAD", "DEADLY", "CRAZY", "INSANE",
             "LIE", "LIES", "FREE"}


def pick_keyword(words):
    """Index of the word to accent: first trigger word, else the last word."""
    clean = ["".join(c for c in w if c.isalnum()).upper() for w in words]
    for i, c in enumerate(clean):
        if c in _TRIGGERS or any(ch.isdigit() for ch in c):
            return i
    return len(words) - 1 if words else None


def _rgb_distance(a, b):
    """Simple per-channel distance between two RGB tuples."""
    return sum(abs(x - y) for x, y in zip(a, b))


def pick_accent_indices(words, max_accented=3):
    """Global word indices to accent.

    Same rule as pick_keyword (trigger words / digits qualify), extended to
    multiple words so headers get 2-3 colored words instead of one. Falls
    back to the last word when nothing qualifies, and never accents more
    than max_accented words (roughly half on dense headers)."""
    clean = ["".join(c for c in w if c.isalnum()).upper() for w in words]
    hits = [i for i, c in enumerate(clean)
            if c in _TRIGGERS or any(ch.isdigit() for ch in c)]
    if not hits:
        hits = [len(words) - 1] if words else []
    cap = max(1, min(len(words), max_accented))
    return hits[:cap]


def accent_color(word, base_rgb, seed=0):
    """Deterministic accent color for a word.

    Hashes the (cased) word so the same word always gets the same color
    within a header, then offsets by `seed` so successive clips in a batch
    rotate through the palette. Colors too close to the preset's base text
    color are skipped, with a guaranteed fallback to the first palette entry."""
    palette = [c for c in ACCENT_PALETTE if _rgb_distance(c, base_rgb) >= _ACCENT_MIN_DIST]
    if not palette:
        palette = ACCENT_PALETTE[:1]
    digest = zlib.crc32(word.strip().lower().encode("utf-8")) & 0xFFFFFFFF
    return palette[(digest + int(seed)) % len(palette)]


def random_accent_seed():
    """Per-render seed so clip-to-clip accent colors rotate visibly."""
    return random.randrange(len(ACCENT_PALETTE))


def _draw_centered_shadowed(draw, lines, font, cx, top_y, fill, accented_map,
                            shadow_color, shadow_offset, shadow_alpha):
    """Render multi-line text centered, with each word drawn with optional drop shadow.

    accented_map: dict mapping global word index -> RGB accent color. Words
    not in the map use `fill`. Each line re-splits on spaces, so the global
    index advances word by word across lines."""
    line_h = font.size + 14
    idx = 0
    y = top_y
    sx, sy = shadow_offset
    do_shadow = shadow_color is not None and shadow_alpha > 0
    for ln in lines:
        words = ln.split(" ")
        widths = [draw.textlength(w, font=font) for w in words]
        space = draw.textlength(" ", font=font)
        total = sum(widths) + space * (len(words) - 1)
        x = cx - total / 2
        for w, wdt in zip(words, widths):
            col = accented_map.get(idx, fill) if accented_map else fill
            if do_shadow:
                sr, sg, sb = shadow_color
                draw.text((x + sx, y + sy), w, font=font,
                          fill=(sr, sg, sb, shadow_alpha))
            draw.text((x, y), w, font=font, fill=col)
            x += wdt + space
            idx += 1
        y += line_h


def render_overlay_png(text, preset="italic-serif", font_path=None, width=ZONE_W,
                       height=ZONE_H, out_path="overlay.png",
                       max_font_size=MAX_FONT, min_font_size=MIN_FONT, opacity=1.0,
                       casing=None, accent_seed=None):
    """Render a transparent PNG of the header/hook in the given preset.

    Presets:
      - "italic-serif":      bold italic serif, soft black shadow, accented keyword (title case)
      - "rounded-chunky":    Montserrat-bold sans, accented keyword (upper case)
      - "bold-caps-yellow":  Montserrat Black, all caps, yellow text, subtle shadow
      - "minimal-clean":     Inter, mixed case, white text, light shadow

    `font_path` is used as the default for Montserrat-based styles; italic-serif
    and minimal-clean resolve their own font paths via OS fallbacks.

    accent_seed: palette rotation offset for multi-color keyword accents.
    None (default) picks a random seed per call; pass a fixed int for
    deterministic output (tests, thumbnail generation).

    opacity: 0.0-1.0 — kept for backward compat; presets have transparent
    backgrounds so opacity is informational only."""
    if preset not in HEADER_PRESETS:
        # Backward-compat: map old/retired presets to a live one
        #   card (white box)        -> rounded-chunky (cleaner)
        #   stroke (heavy chunky)   -> italic-serif (similar weight)
        #   news-bar (red banner)   -> rounded-chunky (preset deleted 2026-08-18;
        #     old saved settings/state still referencing it must keep rendering)
        if preset == "stroke":
            preset = "italic-serif"
        else:
            preset = "rounded-chunky"

    spec = HEADER_PRESETS[preset]
    # Resolve font path based on the preset's font family
    actual_font_path = _resolve_font_path(spec, fallback_path=font_path)
    if actual_font_path is None:
        # Pillow's default font (very generic but works)
        font_obj = ImageFont.load_default()
        # fit_lines needs a real path; skip shrink by passing font directly via early exit
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        text_clean = _apply_casing(text, spec["casing"])
        cx = width // 2
        bbox = d.textbbox((0, 0), text_clean, font=font_obj)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = cx - tw / 2
        y = (height - th) / 2
        # Simple single-line render in keyword color (no shadows; default font path)
        col = spec["keyword"]
        d.text((x, y), text_clean, font=font_obj, fill=col)
        img.save(out_path)
        return out_path

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    effective_casing = casing if casing else spec["casing"]
    lines, font = fit_lines(d, text, actual_font_path, max_w=SAFE_W,
                            max_h=height - 80, stroke=spec.get("stroke", 0),
                            max_font_size=max_font_size,
                            min_font_size=min_font_size, casing=effective_casing)
    block_h = (font.size + 14) * len(lines)
    cx = width // 2
    text_top = (height - block_h) / 2

    # Multi-color keyword accents: pick accent words across the full line
    # set, then assign each a deterministic palette color (rotated by seed).
    _seed = random.randrange(len(ACCENT_PALETTE)) if accent_seed is None else accent_seed
    flat_words = " ".join(lines).split(" ")
    accented_map = {}
    for gi in pick_accent_indices(flat_words):
        accented_map[gi] = accent_color(flat_words[gi], spec["text"], seed=_seed)

    # Draw dark rounded pill container behind text for "pill" style
    if spec.get("container") == "pill" and spec.get("pill_color"):
        pill_color = spec["pill_color"]
        pill_pad_x = spec.get("pill_padding_x", 36)
        pill_pad_y = spec.get("pill_padding_y", 14)
        pill_radius = spec.get("pill_radius", 24)
        widest_w = max(d.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        pill_left = max(20, cx - (widest_w / 2) - pill_pad_x)
        pill_right = min(width - 20, cx + (widest_w / 2) + pill_pad_x)
        pill_top = max(10, text_top - pill_pad_y)
        pill_bot = min(height - 10, text_top + block_h + pill_pad_y)
        d.rounded_rectangle([pill_left, pill_top, pill_right, pill_bot], radius=pill_radius, fill=pill_color)

    _draw_centered_shadowed(
        d, lines, font, cx, text_top,
        fill=spec["text"],
        accented_map=accented_map,
        shadow_color=spec.get("shadow"),
        shadow_offset=spec.get("shadow_offset", (0, 0)),
        shadow_alpha=spec.get("shadow_alpha", 0),
    )

    img.save(out_path)
    return out_path


def render_rounded_mask(out_path, width, height, radius):
    """Render a 1080x1080 transparent PNG with rounded corners.
    Used as an alpha mask to clip the video into a rounded rectangle frame.
    Returns the path to the mask PNG, or None if radius == 0.

    The PNG is white where the video should show, transparent at the rounded corners.
    ffmpeg consumes this as a mask via `[mask]alphamerge`.
    Pure black if rectangle is normal box (for full opacity) and we are using eggplant-style logic; here we go full white inside, transparent outside.
    """
    if radius <= 0:
        return None
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded rectangle: opaque white inside, transparent outside
    d.rounded_rectangle(
        [0, 0, width - 1, height - 1],
        radius=radius,
        fill=(255, 255, 255, 255),
    )
    img.save(out_path)
    return out_path
