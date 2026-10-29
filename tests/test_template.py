import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.project.schema import (
    SCHEMA_VERSION,
    BookendRef,
    ChannelTemplate,
    Project,
    Source,
    VoiceProfile,
    new_id,
)
from backend.project.template import (
    TemplateError,
    apply_template,
    default_template_path,
    external_source,
    load_template_file,
    normalize_bookend_path,
    parse_template,
)


def _src(path: str, *, external: bool = True, duration_ms: int = 5000) -> Source:
    return Source(
        id=new_id(),
        path=path,
        external=external,
        duration_ms=duration_ms,
        fps_num=60,
        width=1920,
        height=1080,
    )


# ---- schema: Source.external -------------------------------------------


def test_source_defaults_to_not_external() -> None:
    assert _src("footage/a.mkv", external=False).external is False


def test_external_source_accepts_absolute_paths() -> None:
    assert _src("D:/Channel/intro.mp4").path == "D:/Channel/intro.mp4"
    assert _src("/mnt/x/intro.mp4").external is True


@pytest.mark.parametrize(
    "path", ["footage/a.mkv", "D:\\Channel\\a.mp4", "D:/Channel/../a.mp4", ""]
)
def test_external_source_rejects_bad_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        _src(path)


@pytest.mark.parametrize("path", ["D:/a.mkv", "/a.mkv", "../a.mkv", "a\\b.mkv"])
def test_non_external_source_still_requires_relative_posix(path: str) -> None:
    with pytest.raises(ValidationError):
        _src(path, external=False)


def test_project_with_external_source_round_trips() -> None:
    project = Project(name="P", sources=[_src("D:/Channel/intro.mp4")])
    again = Project.model_validate_json(project.model_dump_json())
    assert again == project


def test_old_json_without_external_field_still_loads() -> None:
    data = {
        "id": new_id(),
        "path": "footage/a.mkv",
        "duration_ms": 1000,
        "fps_num": 60,
        "width": 1920,
        "height": 1080,
    }
    assert Source.model_validate(data).external is False


# ---- helpers ------------------------------------------------------------


def test_normalize_bookend_path_converts_backslashes() -> None:
    assert normalize_bookend_path("D:\\Channel\\intro.mp4") == "D:/Channel/intro.mp4"
    assert normalize_bookend_path("  D:/x.mp4 ") == "D:/x.mp4"


def test_normalize_bookend_path_rejects_empty() -> None:
    with pytest.raises(TemplateError):
        normalize_bookend_path("   ")


def test_external_source_helper_marks_external_and_normalizes() -> None:
    probed = _src("probe.mp4", external=False)
    out = external_source(probed, "D:\\Channel\\intro.mp4")
    assert out.external is True
    assert out.path == "D:/Channel/intro.mp4"
    assert out.id == probed.id
    assert out.duration_ms == probed.duration_ms


def test_external_source_helper_rejects_relative() -> None:
    with pytest.raises(TemplateError):
        external_source(_src("probe.mp4", external=False), "intro.mp4")


# ---- loading ------------------------------------------------------------


def test_shipped_default_template_loads() -> None:
    assert default_template_path().is_file()
    template = load_template_file()
    assert template.name == "Default"
    assert template.intro is None and template.outro is None
    assert template.voice_profile is not None
    assert template.export.height == 1080


def test_parse_template_rejects_unknown_field() -> None:
    with pytest.raises(TemplateError):
        parse_template({"bogus": 1})


def test_load_template_file_reports_bad_json(tmp_path: Path) -> None:
    bad = tmp_path / "t.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(TemplateError):
        load_template_file(bad)


def test_load_template_file_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TemplateError):
        load_template_file(tmp_path / "nope.json")


def test_load_template_file_valid(tmp_path: Path) -> None:
    good = tmp_path / "t.json"
    good.write_text(json.dumps({"name": "Mine"}), encoding="utf-8")
    assert load_template_file(good).name == "Mine"


# ---- applying -----------------------------------------------------------


def test_apply_without_bookends() -> None:
    template = load_template_file()
    project = apply_template(template, "  My Rack ", seed=123)
    assert project.name == "My Rack"
    assert project.seed == 123
    assert project.schema_version == SCHEMA_VERSION
    assert project.sources == [] and project.clips == []
    assert len(project.voice_profiles) == 1
    assert project.voice_profiles[0].id != "000000000000"
    assert project.fx_chain == template.fx_chain
    assert project.export == template.export
    assert project.avatar == template.avatar


def test_apply_rejects_empty_name() -> None:
    with pytest.raises(TemplateError):
        apply_template(ChannelTemplate(), "   ")


def test_apply_without_voice_profile() -> None:
    assert apply_template(ChannelTemplate(), "P").voice_profiles == []


def test_apply_gives_each_project_its_own_voice_profile_id() -> None:
    template = load_template_file()
    a = apply_template(template, "A")
    b = apply_template(template, "B")
    assert a.voice_profiles[0].id != b.voice_profiles[0].id


def test_apply_does_not_mutate_template() -> None:
    template = ChannelTemplate(voice_profile=VoiceProfile(id=new_id(), name="V"))
    project = apply_template(template, "P")
    project.fx_chain.eq_bass_db = 3.0
    project.voice_profiles[0].name = "X"
    project.avatar.x = 0.1
    assert template.fx_chain.eq_bass_db == 0.0
    assert template.voice_profile is not None
    assert template.voice_profile.name == "V"
    assert template.avatar.x == 0.85


def test_apply_with_both_bookends() -> None:
    template = ChannelTemplate(
        intro=BookendRef(path="D:\\Channel\\intro.mp4"),
        outro=BookendRef(path="D:/Channel/outro.mp4"),
    )
    intro = _src("D:/Channel/intro.mp4", duration_ms=4000)
    outro = _src("D:/Channel/outro.mp4", duration_ms=6000)
    project = apply_template(template, "P", intro_source=intro, outro_source=outro)
    assert [s.id for s in project.sources] == [intro.id, outro.id]
    assert len(project.clips) == 2
    first, last = project.clips
    assert first.source_id == intro.id and last.source_id == outro.id
    assert (first.in_ms, first.out_ms) == (0, 4000)
    assert (last.in_ms, last.out_ms) == (0, 6000)
    assert first.overlay is False and last.overlay is False
    assert first.id != last.id


def test_apply_with_intro_only() -> None:
    template = ChannelTemplate(intro=BookendRef(path="D:/Channel/intro.mp4"))
    intro = _src("D:/Channel/intro.mp4")
    project = apply_template(template, "P", intro_source=intro)
    assert len(project.sources) == 1 and len(project.clips) == 1


def test_apply_same_file_for_intro_and_outro_uses_one_source() -> None:
    template = ChannelTemplate(
        intro=BookendRef(path="D:/Channel/b.mp4"),
        outro=BookendRef(path="D:/Channel/b.mp4"),
    )
    shared = _src("D:/Channel/b.mp4")
    project = apply_template(template, "P", intro_source=shared, outro_source=shared)
    assert len(project.sources) == 1
    assert len(project.clips) == 2


def test_apply_same_path_different_source_ids_is_rejected() -> None:
    template = ChannelTemplate(
        intro=BookendRef(path="D:/Channel/b.mp4"),
        outro=BookendRef(path="D:/Channel/b.mp4"),
    )
    with pytest.raises(TemplateError):
        apply_template(
            template,
            "P",
            intro_source=_src("D:/Channel/b.mp4"),
            outro_source=_src("D:/Channel/b.mp4"),
        )


def test_apply_template_with_intro_but_no_source_is_rejected() -> None:
    template = ChannelTemplate(intro=BookendRef(path="D:/Channel/intro.mp4"))
    with pytest.raises(TemplateError):
        apply_template(template, "P")


def test_apply_source_without_template_bookend_is_rejected() -> None:
    with pytest.raises(TemplateError):
        apply_template(ChannelTemplate(), "P", intro_source=_src("D:/x.mp4"))


def test_apply_rejects_non_external_or_mismatched_source() -> None:
    template = ChannelTemplate(intro=BookendRef(path="D:/Channel/intro.mp4"))
    with pytest.raises(TemplateError):
        apply_template(
            template, "P", intro_source=_src("footage/intro.mp4", external=False)
        )
    with pytest.raises(TemplateError):
        apply_template(template, "P", intro_source=_src("D:/Other/intro.mp4"))


def test_apply_rejects_zero_duration_bookend() -> None:
    template = ChannelTemplate(intro=BookendRef(path="D:/Channel/intro.mp4"))
    with pytest.raises(TemplateError):
        apply_template(
            template, "P", intro_source=_src("D:/Channel/intro.mp4", duration_ms=0)
        )