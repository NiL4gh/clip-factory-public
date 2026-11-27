"""Local batch pipeline tests — watch folder + sequential queue.

Owner decision 2026-07-12 (session 11): local-first batch engine. Watch
folder auto-detects new MP4s, queues them sequentially, processes one
video at a time via existing `_run_strategize` pipeline.
"""
import os
import sys
import time
import threading
import tempfile
import pytest


@pytest.fixture(scope="module", autouse=True)
def _reset_queue_state():
    """Reset queue state between test modules so test order doesn't matter."""
    # Late import so it happens after server.main has initialized.
    from server.main import _state
    saved = {
        "queue": list(_state["queue"]),
        "processed_paths": set(_state["processed_paths"]),
        "watch_dir": _state["queue_watch_dir"],
        "running": _state["queue_running"],
    }
    _state["queue"] = []
    _state["processed_paths"] = set()
    _state["queue_watch_dir"] = ""
    _state["queue_running"] = False
    yield
    _state["queue"] = saved["queue"]
    _state["processed_paths"] = saved["processed_paths"]
    _state["queue_watch_dir"] = saved["watch_dir"]
    _state["queue_running"] = saved["running"]


@pytest.fixture
def fake_mp4(tmp_path):
    """Create a fake .mp4 file > 10MB with mtime older than 30s.

    The watcher rejects files smaller than 10MB OR written within the last
    30 seconds (catches files still being copied).
    """
    p = tmp_path / "video_test.mp4"
    p.write_bytes(b"x" * (15 * 1024 * 1024))  # 15 MB
    old_time = time.time() - 60
    os.utime(str(p), (old_time, old_time))
    return str(p)


@pytest.fixture
def partial_mp4(tmp_path):
    """Create a too-new .mp4 file (mtime < 30s ago). Watcher should reject."""
    p = tmp_path / "video_test.mp4"
    p.write_bytes(b"x" * (15 * 1024 * 1024))
    return str(p)


# Stability check ──────────────────────────────────────────────────────────────

def test_is_file_stable_enough_accepts_old_large_file(fake_mp4):
    from server.main import _is_file_stable_enough
    assert _is_file_stable_enough(fake_mp4) is True


def test_is_file_stable_enough_rejects_recent_file(partial_mp4):
    """Files written < 30s ago must be rejected. Catches in-progress copies."""
    from server.main import _is_file_stable_enough
    assert _is_file_stable_enough(partial_mp4) is False


def test_is_file_stable_enough_rejects_tiny_file(tmp_path):
    """Files < 10MB rejected — looks like a stray thumbnail or partial copy."""
    p = tmp_path / "tiny.mp4"
    p.write_bytes(b"x" * 100)
    old_time = time.time() - 60
    os.utime(str(p), (old_time, old_time))
    from server.main import _is_file_stable_enough
    assert _is_file_stable_enough(str(p)) is False


# Path hashing ─────────────────────────────────────────────────────────────────

def test_video_id_from_path_is_stable(tmp_path):
    from server.main import _video_id_from_path
    p = str(tmp_path / "video.mp4")
    v1 = _video_id_from_path(p)
    v2 = _video_id_from_path(p)
    assert v1 == v2, "video_id must be deterministic across calls"


def test_video_id_from_path_differentiates_paths(tmp_path):
    from server.main import _video_id_from_path
    p1 = str(tmp_path / "video.mp4")
    p2 = str(tmp_path / "video_other.mp4")
    assert _video_id_from_path(p1) != _video_id_from_path(p2)


# Enqueue idempotency ──────────────────────────────────────────────────────────

def test_enqueue_path_accepts_mp4(fake_mp4, _reset_queue_state):
    from server.main import _enqueue_path
    item = _enqueue_path(fake_mp4)
    assert item is not None
    assert item["filename"] == "video_test.mp4"
    assert item["status"] == "pending"
    assert item["video_id"]  # non-empty


def test_enqueue_path_rejects_txt(tmp_path):
    p = tmp_path / "readme.txt"
    p.write_bytes(b"x" * (15 * 1024 * 1024))
    from server.main import _enqueue_path
    assert _enqueue_path(str(p)) is None


def test_enqueue_path_rejects_missing(tmp_path):
    from server.main import _enqueue_path
    assert _enqueue_path(str(tmp_path / "never_existed.mp4")) is None


def test_enqueue_path_is_idempotent(fake_mp4):
    from server.main import _enqueue_path, _state
    _state["queue"] = []
    _state["processed_paths"] = set()
    first = _enqueue_path(fake_mp4)
    second = _enqueue_path(fake_mp4)
    assert first is not None
    assert second is None, "second enqueue must return None (duplicate)"
    assert len(_state["queue"]) == 1, "queue must have exactly one entry"


# Routes via TestClient ────────────────────────────────────────────────────────

def test_set_watch_dir_endpoint_accepts_valid_dir(tmp_path):
    from server.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.post("/api/queue/set_watch_dir", json={"watch_dir": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["watch_dir"] == str(tmp_path)


def test_set_watch_dir_endpoint_rejects_nonexistent_dir():
    from server.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.post("/api/queue/set_watch_dir", json={"watch_dir": "Z:\\nope\\never"})
    assert r.status_code == 400


def test_set_watch_dir_clears_with_empty_string(tmp_path):
    from server.main import app, _state
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.post("/api/queue/set_watch_dir", json={"watch_dir": str(tmp_path)})
    r = c.post("/api/queue/set_watch_dir", json={"watch_dir": ""})
    assert r.status_code == 200
    assert r.json()["watch_dir"] == ""
    assert _state["queue_watch_dir"] == ""


def test_queue_state_endpoint_shape():
    from server.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/api/queue/state")
    assert r.status_code == 200
    body = r.json()
    assert "queue" in body
    assert "queue_running" in body
    assert "queue_active_item" in body
    assert "queue_watch_dir" in body
    assert "clips_by_video" in body


def test_ingest_paths_endpoint_accepts_valid(fake_mp4, _reset_queue_state):
    from server.main import app, _state
    from fastapi.testclient import TestClient
    _state["queue"] = []
    _state["processed_paths"] = set()
    c = TestClient(app)
    r = c.post("/api/queue/ingest_paths", json={"paths": [fake_mp4]})
    assert r.status_code == 200
    body = r.json()
    assert "video_test.mp4" in body["added"]
    assert len(_state["queue"]) == 1


def test_ingest_paths_endpoint_skips_bad(tmp_path):
    """Bad paths should land in 'skipped', not crash the request."""
    from server.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.post("/api/queue/ingest_paths", json={"paths": [str(tmp_path / "nope.mp4"), "C:\\evil"]})
    assert r.status_code == 200
    assert len(r.json()["skipped"]) == 2


def test_queue_clear_empties_pending():
    from server.main import app, _state
    from fastapi.testclient import TestClient
    _state["queue"] = [{"path": "a", "status": "pending"}]
    c = TestClient(app)
    r = c.post("/api/queue/clear")
    assert r.status_code == 200
    assert len(_state["queue"]) == 0


def test_queue_start_is_idempotent():
    """Calling start on an empty queue is a no-op, not a hang."""
    from server.main import app, _state
    from fastapi.testclient import TestClient
    _state["queue"] = []
    c = TestClient(app)
    r = c.post("/api/queue/start")
    assert r.status_code == 200
    body = r.json()
    assert body["queue_running"] is False
    assert "empty" in body["message"].lower() or "nothing" in body["message"].lower()


# ── Folder picker tests (POST /api/queue/pick_folder) ────────────────────
#
# The Windows branch spawns a `python -c` subprocess running a tkinter
# askdirectory dialog -- we cannot exercise the real dialog in CI. Each
# test monkeypatches os.name and subprocess.run to simulate the branches:
# success, cancel (empty stdout), non-dir fallback, timeout, and the
# non-Windows early-return.

def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    """Build a duck-typed CompletedProcess stub with just the attrs the
    route reads (stdout, returncode, stderr). Avoids importing subprocess
    for the fake -- the real subprocess module is patched per-test instead."""
    class _CP:
        pass
    cp = _CP()
    cp.stdout = stdout
    cp.returncode = returncode
    cp.stderr = stderr
    return cp


# ── _run_picker frozen-EXE guards ────────────────────────────────────────
#
# Root cause of the broken batch picker in the packaged app: sys.executable
# IS ClipFactory.exe inside a PyInstaller bundle, so `exe -c script`
# relaunches the app instead of running the dialog. _run_picker must
# resolve a real interpreter from PATH when frozen.

def test_run_picker_frozen_requires_real_python(monkeypatch):
    """Frozen + no python on PATH -> loud RuntimeError, not a silent relaunch
    of ClipFactory.exe (which is exactly the bug being fixed)."""
    from server import main as sm
    monkeypatch.setattr(sm.sys, "frozen", True, raising=False)
    monkeypatch.setattr("shutil.which", lambda p: None)
    with pytest.raises(RuntimeError, match="No Python interpreter"):
        sm._run_picker("print('hi')")


def test_run_picker_frozen_spawns_path_python_not_exe(monkeypatch):
    """Frozen + python found on PATH: the spawned command must be the real
    interpreter, never sys.executable."""
    from server import main as sm
    monkeypatch.setattr(sm.sys, "frozen", True, raising=False)
    fake_py = r"C:\Python311\python.exe"
    monkeypatch.setattr("shutil.which", lambda p: fake_py if p == "py" else None)

    captured = {}
    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return _completed('chosen-dir')
    monkeypatch.setattr("subprocess.run", fake_run)

    out = sm._run_picker("print('x')")
    assert out == "chosen-dir"
    assert captured["cmd"][0] == fake_py


def test_run_picker_raises_on_child_error(monkeypatch):
    """Non-zero child exit (tkinter crash, bad script) must surface as a
    RuntimeError with stderr, so the route reports a reason instead of
    treating garbage stdout as a folder path."""
    from server import main as sm
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _completed("", 1, "TkError: boom"))
    with pytest.raises(RuntimeError, match="boom"):
        sm._run_picker("print('x')")


def test_pick_folder_non_windows_returns_fallback_reason(monkeypatch):
    """Non-Windows hosts (Linux/Colab/macOS) must return ok:false with a
    reason that tells the user to use the text input. This is the
    graceful fallback branch -- no subprocess run on non-Windows."""
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "posix")
    c = TestClient(app)
    r = c.post("/api/queue/pick_folder")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "text input" in body["reason"].lower()


def test_pick_folder_windows_success_returns_path(tmp_path, monkeypatch):
    """Windows branch: subprocess.run returns the chosen dir on stdout;
    route validates it's a real dir and returns ok:true with the path."""
    from server.main import app
    from fastapi.testclient import TestClient
    real_dir = str(tmp_path)
    monkeypatch.setattr("server.main.os.name", "nt")

    def fake_run(cmd, *args, **kwargs):
        # Confirm we're being asked to run our inline tkinter script via
        # the same interpreter, not something else.
        assert cmd[0].endswith("python") or cmd[0].endswith("python.exe") or "python" in cmd[0].lower()
        assert "-c" in cmd
        return _completed(real_dir)

    monkeypatch.setattr("subprocess.run", fake_run)
    c = TestClient(app)
    r = c.post("/api/queue/pick_folder")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["path"] == real_dir


def test_pick_folder_windows_cancel_returns_cancel_reason(monkeypatch):
    """Empty stdout from the dialog means the user hit Cancel."""
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "nt")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _completed(""))
    c = TestClient(app)
    r = c.post("/api/queue/pick_folder")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "cancel" in body["reason"].lower()


def test_pick_folder_windows_non_dir_stdout_rejected(monkeypatch):
    """Defensive: if askdirectory somehow yields a non-directory string
    (symlink race), the route must reject it instead of trusing stdout."""
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "nt")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _completed("Z:\\nope\\does_not_exist"))
    c = TestClient(app)
    r = c.post("/api/queue/pick_folder")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "not a directory" in body["reason"].lower()


def test_pick_folder_windows_timeout_returns_timeout_reason(monkeypatch):
    """subprocess.TimeoutExpired -> route returns ok:false with a timeout
    reason, not a 500."""
    import subprocess as _sp
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "nt")

    def _raise(*a, **k):
        raise _sp.TimeoutExpired(cmd="python", timeout=300)

    monkeypatch.setattr("subprocess.run", _raise)
    c = TestClient(app)
    r = c.post("/api/queue/pick_folder")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "timed out" in body["reason"].lower()


# ── Video picker tests (POST /api/queue/pick_videos) ─────────────────────
#
# Owner workflow: Browse -> native multi-select dialog -> files queue in
# place and WAIT for the user's explicit Start (owner directive 2026-08-16:
# auto-start removed). These tests stub the dialog via subprocess.run and
# verify queue state transitions.

def test_pick_videos_non_windows_returns_fallback_reason(monkeypatch):
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "posix")
    c = TestClient(app)
    r = c.post("/api/queue/pick_videos")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "text input" in body["reason"].lower()


def test_pick_videos_success_queues_without_autostart(fake_mp4, monkeypatch):
    """Dialog returns one valid path -> enqueued, but the worker does NOT
    start on its own anymore (owner directive 2026-08-16)."""
    import json as _json
    from server.main import app, _state
    from fastapi.testclient import TestClient
    _state["queue"] = []
    _state["processed_paths"] = set()
    _state["queue_running"] = False
    monkeypatch.setattr("server.main.os.name", "nt")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: _completed(_json.dumps([fake_mp4])),
    )
    c = TestClient(app)
    r = c.post("/api/queue/pick_videos")
    body = r.json()
    assert body["ok"] is True
    assert "video_test.mp4" in body["added"]
    assert body["queue_length"] == 1
    assert body["queue_running"] is False  # waits for Start Batch / Run Queue
    assert _state["queue_running"] is False
    _state["queue"] = []
    _state["processed_paths"] = set()


def test_upload_videos_batch_queues_without_autostart(fake_mp4, monkeypatch):
    """Multi-file upload must queue the videos and NOT start the worker —
    the user presses Start Batch themselves (owner directive 2026-08-16)."""
    from server.main import app, _state
    from fastapi.testclient import TestClient
    _state["queue"] = []
    _state["processed_paths"] = set()
    _state["queue_running"] = False
    c = TestClient(app)
    with open(fake_mp4, "rb") as fh:
        r = c.post(
            "/api/upload_videos_batch",
            files=[("files", ("video_test.mp4", fh, "video/mp4"))],
            data={"llm_label": "🧠 MiniMax M3 (API - High Availability)"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] == 1
    assert body["queue_started"] is False
    assert body["queue_length"] == 1
    assert _state["queue_running"] is False
    # The chosen model is remembered for when the user starts the batch.
    assert _state["batch_model_label"] == "🧠 MiniMax M3 (API - High Availability)"
    assert len(_state["queue"]) == 1
    assert _state["queue"][0]["status"] == "pending"
    _state["queue"] = []
    _state["processed_paths"] = set()


def test_pick_videos_cancel_returns_cancel_reason(monkeypatch):
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "nt")
    # Cancel -> picker prints "[]" (empty JSON list)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _completed("[]"))
    c = TestClient(app)
    r = c.post("/api/queue/pick_videos")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "cancel" in body["reason"].lower()


def test_pick_videos_garbage_json_returns_reason(monkeypatch):
    """Broken dialog output must not crash; surface a reason."""
    from server.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr("server.main.os.name", "nt")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _completed("{not-json"))
    c = TestClient(app)
    r = c.post("/api/queue/pick_videos")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "unreadable" in body["reason"].lower()

