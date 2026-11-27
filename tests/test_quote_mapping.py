"""Unit tests for topic-bounded quote mapping and timestamp-guided extraction.
"""
import pytest
from shorts_generator.highlights import _map_quotes_to_segments, _snap_timestamps_to_sentence_boundaries


def test_quote_mapping_disambiguates_repetitive_words_using_start_time():
    # Video where "I really believe" appears at 10s and at 3600s (1 hour in)
    raw_words = [
        {"word": "Hello.", "start": 0.0, "end": 0.5},
        {"word": "I", "start": 10.0, "end": 10.2},
        {"word": "really", "start": 10.3, "end": 10.5},
        {"word": "believe", "start": 10.6, "end": 10.9},
        {"word": "this", "start": 11.0, "end": 11.2},
        {"word": "early.", "start": 11.3, "end": 11.6},
        # ... 1 hour later ...
        {"word": "I", "start": 3600.0, "end": 3600.2},
        {"word": "really", "start": 3600.3, "end": 3600.5},
        {"word": "believe", "start": 3600.6, "end": 3600.9},
        {"word": "the", "start": 3601.0, "end": 3601.2},
        {"word": "late", "start": 3601.3, "end": 3601.5},
        {"word": "secret.", "start": 3601.6, "end": 3602.0},
    ]

    llm_seg = [{"start_quote": "I really believe", "end_quote": "late secret"}]

    # Without hint, it matches early occurrence
    early_match = _map_quotes_to_segments(llm_seg, raw_words, search_start_time=0.0)
    assert early_match[0]["start_time"] < 20.0

    # With 3600s hint, it accurately matches the 1-hour occurrence
    late_match = _map_quotes_to_segments(llm_seg, raw_words, search_start_time=3600.0)
    assert late_match[0]["start_time"] >= 3590.0


def test_snap_timestamps_to_sentence_boundaries():
    raw_words = [
        {"word": "First", "start": 0.0, "end": 0.4},
        {"word": "sentence.", "start": 0.5, "end": 1.0},
        {"word": "Second", "start": 2.0, "end": 2.4},
        {"word": "cool", "start": 2.5, "end": 2.9},
        {"word": "sentence.", "start": 3.0, "end": 3.5},
    ]
    raw_seg = [{"start_time": 2.2, "end_time": 3.2, "incomplete_endpoint": False}]
    snapped = _snap_timestamps_to_sentence_boundaries(raw_seg, raw_words)
    assert len(snapped) == 1
    # Should snap start to 2.0 and end to 3.5
    assert snapped[0]["start_time"] == 2.0
    assert snapped[0]["end_time"] == 3.5
