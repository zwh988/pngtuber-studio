from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import APP_NAME, create_app
from backend.project.schema import SCHEMA_VERSION


def test_hello_returns_status() -> None:
    client = TestClient(create_app(static_dir=Path("does-not-exist")))
    response = client.get("/api/hello")
    assert response.status_code == 200
    assert response.json() == {
        "app": APP_NAME,
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
    }


def test_root_explains_missing_frontend(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path))
    response = client.get("/")
    assert response.status_code == 200
    assert "Frontend not built" in response.text


def test_serves_built_frontend_and_keeps_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>built</h1>", encoding="utf-8")
    client = TestClient(create_app(static_dir=tmp_path))
    assert "built" in client.get("/").text
    assert client.get("/api/hello").json()["status"] == "ok"
