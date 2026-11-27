"""Regenerate header-style thumbnails into frontend/public/headers/.

Idempotent. Run from clip-factory repo root:

    python -m shorts_generator.scripts.render_header_thumbnails

Why this script exists: page.tsx advertises header presets in the picker
but thumbnails can drift out of sync. Dead image refs produce broken
thumbnails in the UI. The script renders one PNG per preset via
overlays.render_overlay_png so the picker always matches what the backend
can actually draw.

Uses a fixed accent_seed so regenerated thumbnails are deterministic
(idempotent output across runs).
"""
from __future__ import annotations

import sys
from pathlib import Path

from shorts_generator import overlays

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "frontend" / "public" / "headers"
FONT_FALLBACK = REPO_ROOT / "shorts_generator" / "assets" / "BebasNeue-Regular.ttf"
SAMPLE_TEXT = "PARENTS ARE CRAZY"
SAMPLE_KEYWORD_TEXT = "THE SECRET NOBODY TELLS YOU"


def _emit(preset: str, text: str) -> tuple[Path, int]:
    out_path = OUT_DIR / f"{preset}.png"
    overlays.render_overlay_png(
        text,
        preset=preset,
        font_path=str(FONT_FALLBACK),
        out_path=str(out_path),
        accent_seed=0,
    )
    return out_path, out_path.stat().st_size


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for preset in overlays.HEADER_PRESETS:
        try:
            path, size = _emit(preset, SAMPLE_KEYWORD_TEXT)
        except Exception as exc:  # pragma: no cover - defensive log path
            print(f"  ! {preset:>18}  FAILED  {exc}", file=sys.stderr)
            rc = 1
            continue
        flag = "ok" if size > 200 else "EMPTY?"
        print(f"  - {preset:>18}  {path.name:<24} {size:>6}B  {flag}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
