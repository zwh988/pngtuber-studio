"""Channel templates saved from a project (M7 S6)."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.schema import (
    AvatarSettings,
    Clip,
    CompressorSettings,
    ExportSettings,
    FxChain,
    Project,
    Source,
    VoiceProfile,
)
from backend.project.session import Session, SessionError
from backend.project.template import TemplateError
from backend.project.usertemplates import (
    BUILTIN_ID,
    TEMPLATE_FILE,
    list_templates,
    resolve_template,
    save_template,
    template_folder_name,
    template_from_project,
    template_reference,
)


def _no_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("nothing should be probed")


def write_wav(path: Path, seconds: float = 6.0, rate: int = 24000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * rate)) / rate
    soundfile.write(str(path), (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate)
    return path


def source(sid: str, path: str, *, external: bool) -> Source:
    return Source(
        id=sid, path=path, duration_ms=5000, fps_num=60, fps_den=1,
        width=1920, height=1080, audio_tracks=1, external=external,
    )  # fmt: skip


def channel_project() -> Project:
    intro = source("aaaaaaaaaaaa", "D:/Channel/intro.mp4", external=True)
    main = source("bbbbbbbbbbbb", "footage/rack.mkv", external=False)
    outro = source("cccccccccccc", "D:/Channel/outro.mp4", external=True)
    return Project(
        name="Rack 1",
        sources=[intro, main, outro],
        clips=[
            Clip(id="111111111111", source_id=intro.id, in_ms=0, out_ms=5000),
            Clip(id="222222222222", source_id=main.id, in_ms=0, out_ms=5000),
            Clip(id="333333333333", source_id=outro.id, in_ms=0, out_ms=5000),
        ],
        voice_profiles=[VoiceProfile(id="dddddddddddd", name="Me", reference_clips=["media/voice/me-12345678.wav"])],
        fx_chain=FxChain(eq_bass_db=3.0, compressor=CompressorSettings(enabled=True)),
        avatar=AvatarSettings(art_folder="art/me", x=0.2, scale=1.3),
        export=ExportSettings(height=720, include_avatar_overlay=True),
        game_audio_db=-6.0,
    )


# ---- pure -------------------------------------------------------------------------


def test_template_names_follow_windows_folder_rules() -> None:
    assert template_folder_name("  My   Channel ") == "My Channel"
    for bad in ["", "   ", "a/b", "what?", "CON", "trailing.", "x" * 61, "Default"]:
        with pytest.raises(TemplateError):
            template_folder_name(bad)


def test_template_from_project_takes_the_channel_parts(tmp_path: Path) -> None:
    project = channel_project()
    template, reference = template_from_project(project, tmp_path, " Pool  Channel ")
    assert template.name == "Pool Channel"
    assert template.intro is not None and template.intro.path == "D:/Channel/intro.mp4"
    assert template.outro is not None and template.outro.path == "D:/Channel/outro.mp4"
    assert template.voice_profile is not None
    assert template.voice_profile.reference_clips == ["voice/me-12345678.wav"]
    assert reference == tmp_path / "media" / "voice" / "me-12345678.wav"
    assert template.fx_chain == project.fx_chain
    assert template.export == project.export
    assert template.game_audio_db == -6.0
    # a project-relative art folder becomes absolute, so the template works anywhere
    assert template.avatar.art_folder == (tmp_path / "art" / "me").resolve().as_posix()
    assert template.avatar.x == 0.2 and template.avatar.scale == 1.3
    assert project.avatar.art_folder == "art/me"  # the project is not changed


def test_no_bookends_when_the_ends_are_footage(tmp_path: Path) -> None:
    project = channel_project()
    project.clips = [c for c in project.clips if c.source_id == "bbbbbbbbbbbb"]
    template, _ = template_from_project(project, tmp_path, "Plain")
    assert template.intro is None and template.outro is None
    project.voice_profiles = []
    template, reference = template_from_project(project, tmp_path, "Plain")
    assert template.voice_profile is None and reference is None


# ---- files ------------------------------------------------------------------------


def test_save_list_resolve_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    clip = write_wav(tmp_path / "proj" / "media" / "voice" / "me-12345678.wav")
    template, reference = template_from_project(channel_project(), tmp_path / "proj", "Pool Channel")
    assert reference == clip
    info = save_template(store, template, reference, replace=False)
    assert info.id == "Pool Channel" and info.voice_reference == "me-12345678.wav"
    assert (store / "Pool Channel" / "voice" / "me-12345678.wav").is_file()
    assert json.loads((store / "Pool Channel" / TEMPLATE_FILE).read_text())["name"] == "Pool Channel"

    listed = list_templates(store)
    assert [t.id for t in listed.templates] == [BUILTIN_ID, "Pool Channel"]
    assert listed.templates[0].builtin and not listed.templates[1].builtin
    assert listed.templates[1].intro == "intro.mp4"

    loaded, folder = resolve_template(store, "Pool Channel")
    assert loaded == template
    assert template_reference(loaded, folder) == store / "Pool Channel" / "voice" / "me-12345678.wav"
    assert resolve_template(store, None)[1] is None
    assert resolve_template(store, BUILTIN_ID)[1] is None


def test_an_existing_name_needs_replace(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    template, _ = template_from_project(channel_project(), tmp_path, "Mine")
    template.voice_profile = None
    save_template(store, template, None, replace=False)
    with pytest.raises(TemplateError, match="already exists"):
        save_template(store, template, None, replace=False)
    changed = template.model_copy(update={"game_audio_db": -12.0})
    save_template(store, changed, None, replace=True)
    assert resolve_template(store, "Mine")[0].game_audio_db == -12.0
    assert [p.name for p in store.iterdir()] == ["Mine"]  # no staging leftovers


def test_broken_and_unknown_templates(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    (store / "Broken").mkdir(parents=True)
    (store / "Broken" / TEMPLATE_FILE).write_text("{nope", encoding="utf-8")
    listed = list_templates(store)
    assert [t.id for t in listed.templates] == [BUILTIN_ID]
    assert listed.problems and listed.problems[0].startswith("Broken:")
    with pytest.raises(TemplateError, match="was not found"):
        resolve_template(store, "Nope")
    with pytest.raises(TemplateError):
        resolve_template(store, "../escape")
    with pytest.raises(TemplateError, match="not available"):
        resolve_template(None, "Mine")


# ---- through the session and the routes ------------------------------------------


def test_a_new_project_from_a_saved_template(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    session = Session(probe=_no_probe, user_templates_dir=store)
    session.new_project(str(tmp_path), "Rack 1")
    session.set_voice_reference(str(write_wav(tmp_path / "me.wav")))
    stack = session._stack
    assert stack is not None
    stack.project.fx_chain = FxChain(eq_treble_db=2.0)
    stack.project.export = ExportSettings(height=720)
    stack.project.game_audio_db = -4.0

    info = session.save_as_template("Pool Channel")
    assert info.voice_reference is not None and info.voice_reference.startswith("me-")
    assert info.voice_reference.count("-") == 1  # one hash tag
    with pytest.raises(SessionError, match="already exists"):
        session.save_as_template("Pool Channel")
    session.save_as_template("Pool Channel", replace=True)

    summary = session.new_project(str(tmp_path), "Rack 2", "Pool Channel")
    new = session._stack
    assert new is not None and summary.name == "Rack 2"
    project = new.project
    assert project.fx_chain.eq_treble_db == 2.0
    assert project.export.height == 720
    assert project.game_audio_db == -4.0
    clip = project.voice_profiles[0].reference_clips[0]
    assert clip.startswith("media/voice/me-")
    assert clip == f"media/voice/{info.voice_reference}"  # the same name, not a second tag
    assert (tmp_path / "Rack 2" / Path(clip)).is_file()
    assert session.voice().ready


def test_a_missing_template_clip_leaves_the_profile_without_one(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    session = Session(probe=_no_probe, user_templates_dir=store)
    session.new_project(str(tmp_path), "Rack 1")
    session.set_voice_reference(str(write_wav(tmp_path / "me.wav")))
    session.save_as_template("T")
    for f in (store / "T" / "voice").iterdir():
        f.unlink()
    session.new_project(str(tmp_path), "Rack 2", "T")
    assert session._stack is not None
    assert session._stack.project.voice_profiles[0].reference_clips == []


def test_saving_needs_a_store_and_an_open_project(tmp_path: Path) -> None:
    with pytest.raises(SessionError, match="not available"):
        Session(probe=_no_probe).save_as_template("X")
    with pytest.raises(SessionError):
        Session(probe=_no_probe, user_templates_dir=tmp_path).save_as_template("X")


def test_template_routes(tmp_path: Path) -> None:
    store = tmp_path / "templates"
    session = Session(probe=_no_probe, user_templates_dir=store)
    client = TestClient(create_app(static_dir=tmp_path, session=session, export_tools=lambda: None))
    body = client.get("/api/templates").json()
    assert [t["id"] for t in body["templates"]] == ["default"]
    assert body["folder"] == str(store)
    assert client.post("/api/templates/save", json={"name": "X"}).status_code == 400  # no project
    made = client.post("/api/project/new", json={"name": "Rack", "parent": str(tmp_path)})
    assert made.status_code == 200
    saved = client.post("/api/templates/save", json={"name": "Mine"})
    assert saved.status_code == 200 and saved.json()["id"] == "Mine"
    assert client.post("/api/templates/save", json={"name": "Mine"}).status_code == 400
    assert client.post("/api/templates/save", json={"name": "Mine", "replace": True}).status_code == 200
    new = client.post(
        "/api/project/new", json={"name": "Rack 2", "parent": str(tmp_path), "template_id": "Mine"}
    )
    assert new.status_code == 200
    bad = client.post(
        "/api/project/new", json={"name": "Rack 3", "parent": str(tmp_path), "template_id": "Nope"}
    )
    assert bad.status_code == 400
