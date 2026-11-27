"""HTTP-level tests for the global auto-apply watermark config
(server/main.py — GET/POST/DELETE /api/watermark/config).

The routes persist config + PNG under module-level constants
(WATERMARK_CONFIG_PATH / WATERMARK_PNG_PATH); both are patched to tmp_path
so nothing touches the real repo root.
"""
import os
import pytest
from fastapi.testclient import TestClient

PNG_BYTES = b"\x89PNG\r\n\x1a\nFAKE_PNG_DATA"


@pytest.fixture
def wm_paths(tmp_path, monkeypatch):
    """Redirect watermark persistence to tmp; return the two paths."""
    from server import main as server_main

    cfg_path = tmp_path / "watermark_config.json"
    png_path = tmp_path / "watermark.png"
    monkeypatch.setattr(server_main, "WATERMARK_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(server_main, "WATERMARK_PNG_PATH", str(png_path))
    return {"cfg": str(cfg_path), "png": str(png_path)}


@pytest.fixture
def client():
    """Per-test client with isolated _state."""
    from server.main import app, _state

    _state["clips"] = []
    _state["current_url"] = None
    return TestClient(app)


def test_watermark_config_defaults_disabled(wm_paths, client):
    res = client.get("/api/watermark/config")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["has_image"] is False
    assert body["position"] == "bottom-center"
    assert body["opacity"] == 0.85


def test_watermark_config_post_saves_png_and_enables(wm_paths, client):
    res = client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "bottom-left", "opacity": "0.5"},
        files={"png": ("logo.png", PNG_BYTES, "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["position"] == "bottom-left"
    assert body["opacity"] == 0.5
    assert body["has_image"] is True

    # PNG actually written to the patched path
    assert os.path.exists(wm_paths["png"])
    with open(wm_paths["png"], "rb") as f:
        assert f.read() == PNG_BYTES

    # GET reflects persisted state
    res = client.get("/api/watermark/config")
    body = res.json()
    assert body["enabled"] is True
    assert body["has_image"] is True


def test_watermark_config_post_without_png_keeps_existing(wm_paths, client):
    client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "center", "opacity": "0.9"},
        files={"png": ("logo.png", PNG_BYTES, "image/png")},
    )
    # Second POST changes position only — no file uploaded
    res = client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "top-right", "opacity": "0.3"},
    )
    assert res.status_code == 200
    assert res.json()["position"] == "top-right"
    assert res.json()["has_image"] is True
    assert os.path.exists(wm_paths["png"])


def test_watermark_config_opacity_clamped(wm_paths, client):
    res = client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "center", "opacity": "2.0"},
    )
    assert res.status_code == 200
    assert res.json()["opacity"] == 1.0


def test_watermark_config_invalid_position_falls_back(wm_paths, client):
    res = client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "not-a-position", "opacity": "0.5"},
    )
    assert res.status_code == 200
    assert res.json()["position"] == "bottom-center"


def test_watermark_config_delete_clears_state(wm_paths, client):
    client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "center", "opacity": "0.5"},
        files={"png": ("logo.png", PNG_BYTES, "image/png")},
    )
    res = client.delete("/api/watermark/config")
    assert res.status_code == 200
    assert not os.path.exists(wm_paths["cfg"])
    assert not os.path.exists(wm_paths["png"])

    body = client.get("/api/watermark/config").json()
    assert body["enabled"] is False
    assert body["has_image"] is False


def test_active_watermark_none_when_disabled(wm_paths, client):
    from server.main import _active_watermark

    assert _active_watermark() is None


def test_active_watermark_dict_when_enabled(wm_paths, client):
    from server.main import _active_watermark

    client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "bottom-center", "opacity": "0.7"},
        files={"png": ("logo.png", PNG_BYTES, "image/png")},
    )
    wm = _active_watermark()
    assert wm is not None
    assert wm["png_path"] == wm_paths["png"]
    assert wm["position"] == "bottom-center"
    assert wm["opacity"] == 0.7


def test_active_watermark_none_when_png_missing(wm_paths, client):
    """Config enabled but PNG file deleted → no watermark passed to render."""
    from server.main import _active_watermark

    client.post(
        "/api/watermark/config",
        data={"enabled": "true", "position": "center", "opacity": "0.5"},
        files={"png": ("logo.png", PNG_BYTES, "image/png")},
    )
    os.remove(wm_paths["png"])
    assert _active_watermark() is None
