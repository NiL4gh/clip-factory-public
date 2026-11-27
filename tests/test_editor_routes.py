"""HTTP-level tests for the post-render editor routes (server/main.py D2).

Mirrors the security pattern from `delete_clip`: regex-checked video_id +
filename, server-generated out_path (no client-supplied output path means
no path traversal can escape OUTPUT_DIR structurally).

Late-import discovery: routes do `from shorts_generator import editor`
INSIDE each route body. Because Python caches `shorts_generator.editor`
in `sys.modules` at module-load time and routes re-resolve the attribute
on every call, `monkeypatch.setattr("shorts_generator.editor.trim_clip", fn)`
takes effect immediately. This is the same pattern Chunk B relied on for
`tests/test_queue.py` patching `"subprocess.run"`.
"""
import os
import pytest
from fastapi.testclient import TestClient


VIDEO_ID = "abc123"
FILENAME = "clip001.mp4"


def _completed(stdout: str = "", returncode: int = 0):
    """Duck-typed CompletedProcess stub — only `stdout` and `returncode`
    are read by the editor code paths we exercise."""
    class _CP:
        pass
    cp = _CP()
    cp.stdout = stdout
    cp.returncode = returncode
    return cp


@pytest.fixture
def fake_editor_output(tmp_path, monkeypatch):
    """Redirect OUTPUT_DIR to a tmp dir + lay down a fake source mp4.

    CRITICAL: patches `server.main.OUTPUT_DIR` so route output never lands
    in the real `output/` directory. The fake_run side effects (writing
    a sibling `_trim.mp4` / `_wm.mp4` / `_crop.mp4`) also land in tmp.
    """
    from server import main as server_main

    subdir = tmp_path / VIDEO_ID
    subdir.mkdir(parents=True, exist_ok=True)
    in_path = subdir / FILENAME
    in_path.write_bytes(b"FAKE_SOURCE_MP4")

    # Legacy-flat-layout fallback: also create the file under tmp_path
    # so video_id-based tests that don't use the subdir can target both.
    flat = tmp_path / FILENAME
    flat.write_bytes(b"FAKE_FLAT_SOURCE_MP4")

    monkeypatch.setattr(server_main, "OUTPUT_DIR", str(tmp_path))
    return {
        "tmp": str(tmp_path),
        "subdir": str(subdir),
        "in_path": str(in_path),
        "flat_in": str(flat),
    }


@pytest.fixture
def client():
    """Per-test client with isolated _state (clips + current_url reset)."""
    from server.main import app, _state
    _state["clips"] = []
    _state["current_url"] = None
    return TestClient(app)


# ── trim ──────────────────────────────────────────────────────────────


def test_trim_success_returns_out_path(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor

    written = {}

    def fake_trim(in_path, out_path, start_s, end_s):
        # Confirm arguments are forwarded verbatim.
        written["in_path"] = in_path
        written["out_path"] = out_path
        written["start_s"] = start_s
        written["end_s"] = end_s
        # Side effect: create the out file so the gallery scan would see it.
        open(out_path, "wb").write(b"TRIMMED_OUTPUT")
        return out_path

    monkeypatch.setattr(editor, "trim_clip", fake_trim)

    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 1.5,
        "end_s": 8.0,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["op"] == "trim"
    assert body["out_filename"] == "clip001_trim.mp4"
    assert body["out_rel_path"] == "abc123/clip001_trim.mp4"
    assert body["out_url"] == "/media/abc123/clip001_trim.mp4"
    assert written["start_s"] == 1.5
    assert written["end_s"] == 8.0
    # Verify out file really exists on disk.
    assert os.path.exists(os.path.join(fake_editor_output["subdir"], "clip001_trim.mp4"))


def test_trim_legacy_flat_layout_fallback(fake_editor_output, monkeypatch, client):
    """Legacy clips live directly under OUTPUT_DIR/<file> with no video_id
    subdirectory. The route must find them."""
    from shorts_generator import editor
    monkeypatch.setattr(editor, "trim_clip", lambda i, o, s, e: open(o, "wb").write(b"X") or o)
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 1.0,
    })
    # flat layout exists (fake_editor_output sets it up), so route succeeds.
    assert r.status_code == 200


def test_trim_missing_source_returns_404(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "trim_clip", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    r = client.post("/api/editor/trim", json={
        "video_id": "nope_no_such_video",
        "filename": "nope.mp4",
        "start_s": 0.0,
        "end_s": 1.0,
    })
    assert r.status_code == 404


def test_trim_bad_video_id_returns_400(client):
    r = client.post("/api/editor/trim", json={
        "video_id": "../foo",
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 1.0,
    })
    assert r.status_code == 400
    assert "video_id" in r.json()["detail"].lower()


def test_trim_bad_filename_returns_400(client):
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": "../clip.mp4",
        "start_s": 0.0,
        "end_s": 1.0,
    })
    assert r.status_code == 400
    assert "filename" in r.json()["detail"].lower()


def test_trim_start_greater_than_end_returns_400(fake_editor_output, client):
    """end > start validation happens after path validation but before
    editor call, so 400 not 404/500."""
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 5.0,
        "end_s": 1.0,
    })
    assert r.status_code == 400
    assert "start_s" in r.json()["detail"].lower() or "end_s" in r.json()["detail"].lower()


def test_trim_runtime_error_returns_500(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "trim_clip", lambda i, o, s, e: (_ for _ in ()).throw(RuntimeError("ffmpeg blew up")))
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 5.0,
    })
    assert r.status_code == 500
    assert "ffmpeg blew up" in r.json()["detail"]


def test_trim_missing_field_returns_422(fake_editor_output, client):
    """Pydantic validation: missing `end_s` is a 422 from FastAPI, not 400
    from the route. Frontend must send all four fields."""
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 0.0,
    })
    assert r.status_code == 422


def test_trim_overwrites_existing_out_file(fake_editor_output, monkeypatch, client):
    """Re-running with the same args must overwrite — matches ffmpeg -y and
    keeps the gallery from filling up with duplicates."""
    from shorts_generator import editor
    subdir = fake_editor_output["subdir"]
    first = os.path.join(subdir, "clip001_trim.mp4")
    with open(first, "wb") as f:
        f.write(b"OLD_TRIM")

    monkeypatch.setattr(editor, "trim_clip",
        lambda i, o, s, e: open(o, "wb").write(b"NEW_TRIM") or o)

    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 5.0,
    })
    assert r.status_code == 200
    with open(first, "rb") as f:
        assert f.read() == b"NEW_TRIM"


# ── watermark (multipart upload) ──────────────────────────────────


# Reusable small PNG bytes — FastAPI's UploadFile accepts any bytes; we
# don't need a real PNG because editor.watermark_clip is mocked in the
# success-shape tests. For the "no PNG attached" case, the route fails
# at the multipart boundary (422) before the editor is even called.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"x" * 1024


def _multipart_watermark(video_id=VIDEO_ID, filename=FILENAME, position="bottom-right",
                          png_bytes=_PNG_BYTES, png_name="wm.png"):
    """Build kwargs for TestClient.post that match a multipart upload."""
    files = {"watermark": (png_name, png_bytes, "image/png")}
    data = {"video_id": video_id, "filename": filename}
    if position is not None:
        data["position"] = position
    return {"files": files, "data": data}


def test_watermark_success_returns_out_path(fake_editor_output, monkeypatch, client):
    import os
    from shorts_generator import editor
    captured = {}
    monkeypatch.setattr(editor, "watermark_clip",
        lambda i, o, png, p="bottom-right": (
            captured.update({"png": png, "position": p})
            or open(o, "wb").write(b"WM_OUT") or o
        ))
    r = client.post("/api/editor/watermark", **_multipart_watermark())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["out_filename"] == "clip001_wm.mp4"
    assert body["out_rel_path"] == "abc123/clip001_wm.mp4"
    assert captured["position"] == "bottom-right"
    assert captured["png"]
    assert os.path.exists(captured["png"]) is False  # tmp PNG unlinked in finally


def test_watermark_passes_custom_position(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    captured = {}
    monkeypatch.setattr(editor, "watermark_clip",
        lambda i, o, png, p="bottom-right": (
            captured.update({"position": p}) or open(o, "wb").write(b"ok") or o))
    r = client.post("/api/editor/watermark",
                    **_multipart_watermark(position="top-left"))
    assert r.status_code == 200, r.text
    assert captured["position"] == "top-left"


def test_watermark_unknown_position_400(fake_editor_output, monkeypatch, client):
    """editor.watermark_clip raises ValueError on unknown position -> 400."""
    from shorts_generator import editor
    monkeypatch.setattr(editor, "watermark_clip",
        lambda i, o, png, p="bottom-right": (_ for _ in ()).throw(ValueError(
            "Unknown watermark position: center")))
    r = client.post("/api/editor/watermark",
                    **_multipart_watermark(position="center"))
    assert r.status_code == 400, r.text


def test_watermark_runtime_error_500(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "watermark_clip",
        lambda i, o, png, p="bottom-right": (_ for _ in ()).throw(RuntimeError(
            "ffmpeg overlay died")))
    r = client.post("/api/editor/watermark", **_multipart_watermark())
    assert r.status_code == 500, r.text


def test_watermark_missing_video_returns_404(fake_editor_output, monkeypatch, client):
    """Resolution fails before editor is called — _resolve_editor_in_path raises 404."""
    from shorts_generator import editor
    monkeypatch.setattr(editor, "watermark_clip",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("editor must not be called")))
    r = client.post("/api/editor/watermark",
                    **_multipart_watermark(video_id="ghost_video",
                                            filename="ghost.mp4"))
    assert r.status_code == 404, r.text


def test_watermark_empty_png_bytes_still_uploads(fake_editor_output, monkeypatch, client):
    """Endpoint accepts zero-byte PNG uploads (server doesn't validate fake-PNG headers).
    Editor is mocked to succeed; the route's job is just to persist+unlink the tmp file."""
    from shorts_generator import editor
    captured = {}
    monkeypatch.setattr(editor, "watermark_clip",
        lambda i, o, png, p="bottom-right": captured.update({"ok": True}) or open(o, "wb").write(b"out") or o)
    r = client.post("/api/editor/watermark",
                    **_multipart_watermark(png_bytes=b""))
    assert r.status_code == 200, r.text
    assert captured.get("ok") is True


def test_watermark_missing_file_field_422(fake_editor_output, client):
    """No `watermark` file field in the multipart form -> 422 from FastAPI."""
    r = client.post("/api/editor/watermark",
                    data={"video_id": VIDEO_ID, "filename": FILENAME})
    assert r.status_code == 422, r.text


def test_watermark_missing_video_id_field_422(fake_editor_output, client):
    """No video_id form field -> 422 from FastAPI."""
    r = client.post("/api/editor/watermark",
                    files={"watermark": ("wm.png", b"PNG", "image/png")},
                    data={"filename": FILENAME})
    assert r.status_code == 422, r.text


def test_watermark_bad_video_id_regex_400(fake_editor_output, monkeypatch, client):
    """video_id with `..` fails the regex in _resolve_editor_in_path -> 400."""
    from shorts_generator import editor
    monkeypatch.setattr(editor, "watermark_clip",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("editor must not be called")))
    r = client.post("/api/editor/watermark",
                    **_multipart_watermark(video_id="../escape", filename="x.mp4"))
    assert r.status_code == 400, r.text


# ── crop ─────────────────────────────────────────────────────────────


def test_crop_success_returns_out_path(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "crop_clip",
        lambda i, o, ratio: open(o, "wb").write(b"CROP_OUT") or o)
    r = client.post("/api/editor/crop", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "ratio": "9:16",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["out_filename"] == "clip001_crop.mp4"
    assert body["out_rel_path"] == "abc123/clip001_crop.mp4"
    assert body["out_url"] == "/media/abc123/clip001_crop.mp4"


def test_crop_unknown_ratio_returns_400(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "crop_clip",
        lambda i, o, ratio: (_ for _ in ()).throw(ValueError(f"unknown ratio: {ratio}")))
    r = client.post("/api/editor/crop", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "ratio": "16:9",
    })
    assert r.status_code == 400


def test_crop_runtime_error_500(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "crop_clip",
        lambda i, o, ratio: (_ for _ in ()).throw(RuntimeError("ffprobe returned no streams")))
    r = client.post("/api/editor/crop", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "ratio": "1:1",
    })
    assert r.status_code == 500


def test_crop_missing_input_404(fake_editor_output, monkeypatch, client):
    from shorts_generator import editor
    monkeypatch.setattr(editor, "crop_clip",
        lambda i, o, ratio: (_ for _ in ()).throw(AssertionError("not called")))
    r = client.post("/api/editor/crop", json={
        "video_id": "ghost",
        "filename": "ghost.mp4",
        "ratio": "9:16",
    })
    assert r.status_code == 404


def test_crop_missing_ratio_field_422(fake_editor_output, client):
    r = client.post("/api/editor/crop", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
    })
    assert r.status_code == 422


# ── security regression locks ────────────────────────────────────────


def test_path_traversal_in_filename_returns_400(client):
    r"""A filename like ../../etc/passwd must be rejected outright — the
    regex only allows word/dash/dot/space chars before .mp4 so the regex
    match fails closed."""
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": "..%2F..%2Fetc%2Fpasswd",
        "start_s": 0.0,
        "end_s": 1.0,
    })
    assert r.status_code == 400


def test_path_traversal_in_video_id_returns_400(client):
    r = client.post("/api/editor/trim", json={
        "video_id": "..\\evil",
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 1.0,
    })
    assert r.status_code == 400


def test_no_writes_to_real_output_dir(fake_editor_output, monkeypatch, client):
    """Safeguard: even on success, no file must land outside the patched
    OUTPUT_DIR. Effectively a meta-test that OUTPUT_DIR is actually being
    patched (catches accidental regression to the real output/)."""
    from shorts_generator import editor
    real_output = os.path.realpath("output")  # what we'd write to otherwise
    monkeypatch.setattr(editor, "trim_clip",
        lambda i, o, s, e: open(o, "wb").write(b"OK") or o)
    r = client.post("/api/editor/trim", json={
        "video_id": VIDEO_ID,
        "filename": FILENAME,
        "start_s": 0.0,
        "end_s": 5.0,
    })
    assert r.status_code == 200
    # No new files written next to this test_file in the cwd.
    # (The route writes only into the patched OUTPUT_DIR.)
