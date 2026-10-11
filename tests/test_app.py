from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import APP_NAME, create_app
from backend.project.schema import SCHEMA_VERSION
from backend.project.session import Session

NO_FRONTEND = Path("does-not-exist")


def _client(session: Session | None = None) -> TestClient:
    return TestClient(create_app(static_dir=NO_FRONTEND, session=session))


def test_hello_returns_status() -> None:
    response = _client().get("/api/hello")
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


def test_no_project_open_returns_null() -> None:
    response = _client().get("/api/project")
    assert response.status_code == 200
    assert response.json() is None


def test_new_then_get_project(tmp_path: Path) -> None:
    client = _client(Session())
    response = client.post(
        "/api/project/new", json={"name": "My Rack", "parent": str(tmp_path)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "My Rack"
    assert body["voice_status"] == "not configured"
    assert client.get("/api/project").json() == body


def test_new_project_error_is_400(tmp_path: Path) -> None:
    response = _client(Session()).post(
        "/api/project/new", json={"name": "a/b", "parent": str(tmp_path)}
    )
    assert response.status_code == 400
    assert "project name" in response.json()["detail"]


def test_open_project_via_api(tmp_path: Path) -> None:
    created = _client(Session()).post(
        "/api/project/new", json={"name": "Rack", "parent": str(tmp_path)}
    ).json()
    client = _client(Session())
    response = client.post("/api/project/open", json={"folder": created["folder"]})
    assert response.status_code == 200
    assert response.json() == created


def test_open_missing_project_is_400(tmp_path: Path) -> None:
    response = _client(Session()).post(
        "/api/project/open", json={"folder": str(tmp_path)}
    )
    assert response.status_code == 400
    assert "no project.json" in response.json()["detail"]
