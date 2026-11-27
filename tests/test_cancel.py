"""Cooperative-cancellation tests (owner bug report 2026-08-16).

Stop Batch / Stop Process used to be powerless during transcription and
LLM extraction because those phases run in-process (no subprocess to
taskkill) and never checked the cancel flag. These tests guard the hooks
that make Stop actually interruptible:

  1. transcribe_audio polls is_cancelled before/between segments and raises
     (caller aborts without caching a partial transcript).
  2. _execute_with_fallback skips API calls entirely when cancelled.
  3. The server installs a cancel hook wired to _state["is_cancelled"].
"""
import pytest


# 1 ── transcriber cancel hook ──────────────────────────────────────────────

class _FakeSeg:
    def __init__(self, text):
        self.text = text
        self.words = []


class _FakeInfo:
    language = "en"


class _FakeModel:
    def __init__(self, texts):
        self._texts = texts

    def transcribe(self, path, **kw):
        def gen():
            for t in self._texts:
                yield _FakeSeg(t)
        return gen(), _FakeInfo()


def test_transcribe_audio_raises_when_cancelled_midway(monkeypatch):
    """Cancel flag flipped after the first segment → RuntimeError, abort."""
    from shorts_generator import transcriber

    consumed = {"n": 0}

    class _CancelAfterOne(_FakeModel):
        def transcribe(self, path, **kw):
            def gen():
                for t in self._texts:
                    yield _FakeSeg(t)
                    consumed["n"] += 1
            return gen(), _FakeInfo()

    monkeypatch.setattr(transcriber.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(transcriber, "_get_model", lambda size, d: _CancelAfterOne(["a ", "b", "c"]))

    with pytest.raises(RuntimeError, match="cancelled"):
        transcriber.transcribe_audio(
            "fake.mp4", model_size="tiny", whisper_dir=None,
            language="en", is_cancelled=lambda: consumed["n"] >= 1,
        )
    # Aborted after the first segment, before consuming the rest.
    assert consumed["n"] == 1


def test_transcribe_audio_completes_when_not_cancelled(monkeypatch):
    """No cancel → full transcript returned exactly as before the change."""
    from shorts_generator import transcriber

    monkeypatch.setattr(transcriber.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(transcriber, "_get_model", lambda size, d: _FakeModel(["hello ", "world"]))
    monkeypatch.setattr(transcriber.os, "remove", lambda p: None)

    full_text, wts = transcriber.transcribe_audio(
        "fake.mp4", model_size="tiny", whisper_dir=None,
        language="en", is_cancelled=lambda: False,
    )
    # Each segment's text gets a trailing space (existing behavior: '+ " "').
    assert full_text == "hello  world"
    assert wts == []


def test_transcribe_audio_default_has_no_hook(monkeypatch):
    """Back-compat: callers that pass no hook get unchanged behavior."""
    from shorts_generator import transcriber

    monkeypatch.setattr(transcriber.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(transcriber, "_get_model", lambda size, d: _FakeModel(["ok"]))
    monkeypatch.setattr(transcriber.os, "remove", lambda p: None)

    full_text, _ = transcriber.transcribe_audio("fake.mp4")
    assert full_text == "ok"


# 2 ── LLM layer cancel short-circuit ───────────────────────────────────────

def test_execute_with_fallback_returns_empty_when_cancelled():
    """Cancelled flag on → no HTTP call attempted, [] returned immediately."""
    import urllib.request
    from shorts_generator import highlights

    attempted = {"n": 0}
    real_urlopen = urllib.request.urlopen

    def _spy_urlopen(*a, **kw):
        attempted["n"] += 1
        return real_urlopen(*a, **kw)

    # _execute_with_fallback uses `urllib.request` via a function-local
    # import → patch the real module. Save/restore the installed cancel hook:
    # server.main installs one at import time; clobbering it with None here
    # would break later tests that assert the hook reflects _state.
    prev_hook = highlights._cancel_check
    urllib.request.urlopen = _spy_urlopen
    highlights.set_cancel_check(lambda: True)
    try:
        result = highlights._execute_with_fallback(
            "api:nvidia:meta/llama-3.1-70b-instruct", "sys", "prompt"
        )
        assert result == []
        assert attempted["n"] == 0  # never hit the network
    finally:
        highlights.set_cancel_check(prev_hook)
        urllib.request.urlopen = real_urlopen


def test_cancel_hook_installation_reflects_state_flag():
    """server.main wires _state['is_cancelled'] into the highlights hook."""
    from server.main import _state, _highlights_is_cancelled
    from shorts_generator import highlights

    prev = _state["is_cancelled"]
    try:
        _state["is_cancelled"] = True
        assert _highlights_is_cancelled() is True
        assert highlights.is_cancelled() is True  # via installed hook
        _state["is_cancelled"] = False
        assert highlights.is_cancelled() is False
    finally:
        _state["is_cancelled"] = prev
