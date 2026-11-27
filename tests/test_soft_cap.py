"""Soft-cap clip duration tests.

Owner-locked soft cap (session 2026-07-12): LLM prompts prefer 15-60s durations;
underlying absolute bound is parameterized (default 90s). Replaces the panic-driven
45s hard cap that produced worse clips by cutting narratives mid-sentence.
"""
import pytest
from shorts_generator.highlights import (
    DEFAULT_MAX_DURATION,
    _validate_clips,
    _VIRALITY_BASE,
)


def test_default_max_duration_is_ninety():
    """Owner-locked default: soft absolute bound is 90s (rejects 45s panic cap).

    15-60s is the LLM-preferred sweet spot. 90s is the safety net against
    a runaway LLM producing multi-minute clips.
    """
    assert DEFAULT_MAX_DURATION == 90


def test_validate_clips_default_keeps_22s_rejects_paneled_clips():
    """5 clips at varied lengths: 12s (too short), 22s (perfect), 60s (perfect),
    88s (OK under 90), 120s (over). Validate only keeps sweet-spot clips.
    """
    clips = [
        {"title": "12_short", "segments": [{"start_time": 0, "end_time": 12}]},
        {"title": "22_perfect", "segments": [{"start_time": 0, "end_time": 22}]},
        {"title": "60_perfect", "segments": [{"start_time": 0, "end_time": 60}]},
        {"title": "88_ok", "segments": [{"start_time": 0, "end_time": 88}]},
        {"title": "120_over", "segments": [{"start_time": 0, "end_time": 120}]},
    ]
    kept = _validate_clips(clips, raw_words=[], max_duration=90)
    titles = [c["title"] for c in kept]
    assert "12_short" not in titles, "under 15s must be discarded"
    assert "22_perfect" in titles, "22s is in sweet spot"
    assert "60_perfect" in titles, "60s upper edge of sweet spot"
    assert "88_ok" in titles, "88s under 90s default cap"
    assert "120_over" not in titles, "120s over default cap"


def test_validate_clips_accepts_parameterized_cap():
    """Override the cap to 60s should drop 88s and 120s clips."""
    clips = [
        {"title": "22_perfect", "segments": [{"start_time": 0, "end_time": 22}]},
        {"title": "60_perfect", "segments": [{"start_time": 0, "end_time": 60}]},
        {"title": "88_too_long", "segments": [{"start_time": 0, "end_time": 88}]},
    ]
    kept = _validate_clips(clips, raw_words=[], max_duration=60)
    titles = [c["title"] for c in kept]
    assert "22_perfect" in titles
    assert "60_perfect" in titles
    assert "88_too_long" not in titles, "88s exceeds parameterized 60s cap"


def test_validate_clips_default_no_arg_matches_explicit_90():
    """Passing no max_duration should default to DEFAULT_MAX_DURATION (90s)."""
    clips = [
        {"title": "85_ok", "segments": [{"start_time": 0, "end_time": 85}]},
        {"title": "91_over", "segments": [{"start_time": 0, "end_time": 91}]},
    ]
    kept_default = _validate_clips(clips, raw_words=[])
    kept_explicit = _validate_clips(clips, raw_words=[], max_duration=DEFAULT_MAX_DURATION)
    assert [c["title"] for c in kept_default] == [c["title"] for c in kept_explicit]


def test_virality_prompt_template_has_max_duration_placeholder():
    """The prompt template must contain {MAX_DURATION} so runtime substitution works.

    This is the contract the LLM uses to know the absolute bound. If someone
    removes it during prompt editing, the LLM won't know the cap.
    """
    assert "{MAX_DURATION}" in _VIRALITY_BASE, (
        "Prompt template missing {MAX_DURATION} placeholder — "
        "get_highlights() will silently pass {MAX_DURATION} to the LLM "
        "which is a breaking regression."
    )


def test_virality_prompt_uses_soft_language_not_panic_cap():
    """The prompt must encourage shortest-possible clips, not hard-cap them.

    Replaces the panic-driven "Do NOT exceed a hard cap of 45 seconds" line
    with soft guidance that the LLM can reason through.
    """
    assert "hard cap of 45" not in _VIRALITY_BASE, (
        "Old 45s cap text leaked into the prompt template. The owner rejected "
        "this cap as panic-driven. Soft cap language should replace it."
    )
    assert "Prefer clip durations" in _VIRALITY_BASE, "Soft cap language missing"
    assert "completion rate" in _VIRALITY_BASE, "Should explain WHY soft cap matters"


def test_virality_prompt_does_not_preclude_90s_clips():
    """Even though LLM prefers 15-60s, the prompt should allow longer if arc demands it.

    Owner confirmed 90s is the absolute ceiling. The prompt must support this.
    """
    # After runtime substitution, the {MAX_DURATION} placeholder becomes "90"
    # in the rendered prompt. The validator caps at max_duration. So a clip
    # between 60-90s is valid but discouraged.
    runtime_prompt = _VIRALITY_BASE.replace("{MAX_DURATION}", "90")
    assert "currently 90s" in runtime_prompt or "the configured absolute bound" in runtime_prompt
