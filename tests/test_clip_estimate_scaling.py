"""Length-scaled clip estimate tests (owner decision 2026-08-17).

Budget: 1 clip per 2 minutes, floor 6, ceiling 60. Supersedes the
1-per-4-min rule from 2026-08-16 after a real 18-min run proved the old
formula capped output at 5 while 18 viable candidates existed on disk.
"""
import pytest
from shorts_generator.highlights import estimate_clip_potential, MAX_CLIP_CEILING


def _words_for_minutes(total_minutes: float) -> list:
    """Word-timestamp fixture spanning total_minutes; first word at 0s, last at end."""
    total_seconds = total_minutes * 60.0
    return [
        {"start": 0.0, "end": 0.4, "word": "hello"},
        {"start": total_seconds - 0.5, "end": total_seconds, "word": "bye"},
    ]


def test_empty_timestamps_falls_back_to_floor():
    assert estimate_clip_potential([]) == 6


def test_short_video_gets_floor_of_6():
    # 10 min -> 10/2 = 5 -> clamps to floor 6; 12+ min scales up
    assert estimate_clip_potential(_words_for_minutes(10)) == 6


def test_eighteen_minute_video_gets_nine():
    # Regression proof for the 2026-08-17 emergency: 18/2 = 9 (was 5 under the
    # old 1/4 formula, which discarded 13 viable candidates found that day)
    assert estimate_clip_potential(_words_for_minutes(18)) == 9


def test_one_hour_video_gets_30():
    assert estimate_clip_potential(_words_for_minutes(60)) == 30


def test_two_hour_video_hits_ceiling():
    # 120/2 = 60 hits the ceiling exactly — render queue stays bounded
    assert estimate_clip_potential(_words_for_minutes(120)) == 60


def test_very_long_video_is_capped_at_ceiling():
    # 10 hours -> 600/2 = 300, clipped by ceiling
    assert estimate_clip_potential(_words_for_minutes(600)) == MAX_CLIP_CEILING
    assert MAX_CLIP_CEILING == 60
