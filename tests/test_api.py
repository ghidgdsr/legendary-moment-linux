from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _png_bytes() -> bytes:
    img = Image.new("RGB", (32, 24), (40, 90, 160))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_health_and_config_are_public() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        config = client.get("/api/config")
        assert config.status_code == 200
        assert {m["name"] for m in config.json()["modes"]} == {
            "COLOR_ONLY",
            "BLUR_ONLY",
            "COLOR_AND_BLUR",
        }


def test_token_file_is_stable_across_loads(tmp_path) -> None:
    from backend.app.main import load_or_create_token

    path = tmp_path / "token.txt"
    first, created = load_or_create_token(path)
    assert created and first
    assert path.read_text(encoding="utf-8").strip() == first

    second, created_again = load_or_create_token(path)
    assert not created_again
    assert second == first

    # An empty file is the only case that triggers a new token.
    path.write_text("", encoding="utf-8")
    third, replaced = load_or_create_token(path)
    assert replaced and third
    assert path.read_text(encoding="utf-8").strip() == third

    fourth, replaced_again = load_or_create_token(path)
    assert not replaced_again and fourth == third


def test_auth_is_required() -> None:
    with TestClient(app) as client:
        assert client.get("/api/jobs/__ping__").status_code == 401
        assert (
            client.get(
                "/api/jobs/__ping__", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert client.get("/api/jobs/__ping__", headers=AUTH).status_code == 404


def test_static_and_index() -> None:
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200


def test_invalid_upload_is_rejected() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/jobs",
            headers=AUTH,
            files={"file": ("bad.jpg", b"not an image", "image/jpeg")},
            data={"mode": "COLOR_ONLY", "aperture": "2.0"},
        )
        assert res.status_code == 400


def test_blur_requires_focus() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/jobs",
            headers=AUTH,
            files={"file": ("ok.png", _png_bytes(), "image/png")},
            data={"mode": "BLUR_ONLY", "aperture": "2.0"},
        )
        assert res.status_code == 422
        assert "焦点" in res.json()["detail"]


def test_unknown_mode_and_aperture() -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/jobs",
            headers=AUTH,
            files={"file": ("ok.png", _png_bytes(), "image/png")},
            data={"mode": "NOPE", "aperture": "2.0"},
        )
        assert res.status_code == 422
        res = client.post(
            "/api/jobs",
            headers=AUTH,
            files={"file": ("ok.png", _png_bytes(), "image/png")},
            data={"mode": "COLOR_ONLY", "aperture": "1.4"},
        )
        assert res.status_code == 422
