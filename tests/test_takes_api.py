"""Take and storage endpoints (M3-4)."""

from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.line_ops import AddLineOp
from backend.project.session import Session
from backend.voice.presets import parse_presets
from backend.voice.takes import NewTake

PRESETS = parse_presets(
    {"presets": {"neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"}}}
)
L1 = "aaaaaaaaaaaa"
T1 = "111111111111"
T2 = "222222222222"
RATE = 24000


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def make_client(tmp_path: Path) -> tuple[TestClient, Session, Path]:
    session = Session(probe=fake_probe, presets=PRESETS)
    session.new_project(str(tmp_path), "Rack")
    session.edit_lines([AddLineOp(line_id=L1, text="hello")])
    app = create_app(static_dir=tmp_path / "no-frontend", session=session)
    return TestClient(app), session, tmp_path / "Rack"


def add_take(session: Session, take_id: str, key: str) -> None:
    new = NewTake(
        line_id=L1,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="666666666666",
        model_version="m",
        raw_key=key,
        take_id=take_id,
    )
    samples = (0.3 * np.sin(np.arange(2400) / 10)).astype(np.float32)
    session.add_take(new, samples, RATE)


def test_takes_endpoint_lists_a_lines_takes(tmp_path: Path) -> None:
    client, session, _ = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    add_take(session, T2, "b" * 64)
    response = client.get(f"/api/lines/{L1}/takes")
    assert response.status_code == 200
    body = response.json()
    assert [take["id"] for take in body] == [T1, T2]
    assert [take["active"] for take in body] == [False, True]
    assert body[0]["duration_ms"] == 100
    assert body[0]["file_exists"] is True


def test_takes_endpoint_unknown_line_is_400(tmp_path: Path) -> None:
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/lines/999999999999/takes").status_code == 400


def test_take_media_serves_the_wav(tmp_path: Path) -> None:
    client, session, folder = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    wav = (folder / "media" / "takes_raw" / f"{T1}.wav").read_bytes()
    response = client.get(f"/media/take/{T1}")
    assert response.status_code == 200
    assert response.content == wav
    ranged = client.get(f"/media/take/{T1}", headers={"Range": "bytes=0-9"})
    assert ranged.status_code == 206
    assert ranged.content == wav[:10]


def test_take_media_unknown_take_is_404(tmp_path: Path) -> None:
    client, _, _ = make_client(tmp_path)
    assert client.get(f"/media/take/{T1}").status_code == 404


def test_take_media_for_a_deleted_file_is_404(tmp_path: Path) -> None:
    client, session, folder = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    (folder / "media" / "takes_raw" / f"{T1}.wav").unlink()
    assert client.get(f"/media/take/{T1}").status_code == 404


def test_delete_take_endpoint(tmp_path: Path) -> None:
    client, session, folder = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    response = client.post("/api/takes/delete", json={"take_id": T1})
    assert response.status_code == 200
    body = response.json()
    assert body["removed_take_count"] == 1
    assert body["freed_bytes"] > 0
    assert body["cleared_active_line_ids"] == [L1]
    assert client.get(f"/api/lines/{L1}/takes").json() == []
    assert not (folder / "media" / "takes_raw" / f"{T1}.wav").exists()
    assert client.get("/api/lines").json()["lines"][0]["active_take_id"] is None


def test_delete_take_unknown_is_400(tmp_path: Path) -> None:
    client, _, _ = make_client(tmp_path)
    response = client.post("/api/takes/delete", json={"take_id": T1})
    assert response.status_code == 400
    assert "unknown take id" in response.json()["detail"]


def test_delete_line_endpoint(tmp_path: Path) -> None:
    client, session, _ = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    response = client.post("/api/lines/delete", json={"line_id": L1})
    assert response.status_code == 200
    body = response.json()
    assert body["removed_line"] is True
    assert body["removed_take_count"] == 1
    assert client.get("/api/lines").json()["lines"] == []


def test_delete_unknown_line_is_400(tmp_path: Path) -> None:
    client, _, _ = make_client(tmp_path)
    assert client.post("/api/lines/delete", json={"line_id": L1 + "x"}).status_code in (400, 422)
    assert client.post("/api/lines/delete", json={"line_id": "999999999999"}).status_code == 400


def test_storage_endpoint(tmp_path: Path) -> None:
    client, session, folder = make_client(tmp_path)
    add_take(session, T1, "a" * 64)
    (folder / "media" / "takes_raw" / "stray.wav").write_bytes(b"12345")
    body = client.get("/api/storage").json()
    assert body["take_count"] == 1
    assert body["lines"][0]["line_id"] == L1
    assert body["total_bytes"] == body["lines"][0]["takes"][0]["size_bytes"] > 0
    assert body["unreferenced"][0]["path"] == "media/takes_raw/stray.wav"


def test_endpoints_without_a_project_are_400(tmp_path: Path) -> None:
    session = Session(probe=fake_probe, presets=PRESETS)
    client = TestClient(create_app(static_dir=tmp_path / "x", session=session))
    assert client.get("/api/storage").status_code == 400
    assert client.get(f"/api/lines/{L1}/takes").status_code == 400
    assert client.post("/api/takes/delete", json={"take_id": T1}).status_code == 400
