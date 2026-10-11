"""Channel template: load, validate, apply to a new project (M1-5).

Pure logic except ``load_template_file``. Probing bookend files with ffprobe is
done by the caller (M1-6); this module receives the resulting Sources.
Template assets live outside the project, so their Sources are ``external``.
"""

import json
from pathlib import Path, PureWindowsPath

from pydantic import ValidationError

from backend.project.schema import (
    ChannelTemplate,
    Clip,
    Project,
    Source,
    new_id,
)


class TemplateError(Exception):
    """A template file or template application is invalid."""


def default_template_path() -> Path:
    """``<repo>/templates/default_channel.json``."""
    return Path(__file__).resolve().parents[2] / "templates" / "default_channel.json"


def normalize_bookend_path(raw: str) -> str:
    """Convert a user-written path (backslashes allowed) to forward slashes."""
    text = raw.strip()
    if not text:
        raise TemplateError("bookend path is empty")
    return PureWindowsPath(text).as_posix()


def parse_template(data: object) -> ChannelTemplate:
    try:
        return ChannelTemplate.model_validate(data)
    except ValidationError as exc:
        raise TemplateError(f"invalid channel template: {exc}") from exc


def load_template_file(path: Path | None = None) -> ChannelTemplate:
    target = path if path is not None else default_template_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"cannot read template {target}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"template {target} is not valid JSON: {exc}") from exc
    return parse_template(data)


def external_source(probed: Source, path: str) -> Source:
    """Turn a probed Source into an external one pointing at ``path``."""
    data = probed.model_dump()
    data["path"] = normalize_bookend_path(path)
    data["external"] = True
    try:
        return Source.model_validate(data)
    except ValidationError as exc:
        raise TemplateError(f"invalid bookend source: {exc}") from exc


def _bookend_clip(source: Source) -> Clip:
    if source.duration_ms <= 0:
        raise TemplateError(f"bookend {source.path} has zero duration")
    return Clip(
        id=new_id(),
        source_id=source.id,
        in_ms=0,
        out_ms=source.duration_ms,
        overlay=False,
    )


def _check_bookend(label: str, ref_path: str | None, source: Source | None) -> None:
    if ref_path is None and source is None:
        return
    if ref_path is None:
        raise TemplateError(f"{label} source given but the template has no {label}")
    if source is None:
        raise TemplateError(f"template has an {label} but no source was provided")
    if not source.external:
        raise TemplateError(f"{label} source must be external")
    if source.path != normalize_bookend_path(ref_path):
        raise TemplateError(f"{label} source path does not match the template")


def apply_template(
    template: ChannelTemplate,
    name: str,
    *,
    intro_source: Source | None = None,
    outro_source: Source | None = None,
    seed: int | None = None,
) -> Project:
    """Build a new Project from a template. The template is never mutated."""
    clean = name.strip()
    if not clean:
        raise TemplateError("project name must not be empty")

    _check_bookend("intro", template.intro.path if template.intro else None, intro_source)
    _check_bookend("outro", template.outro.path if template.outro else None, outro_source)

    sources: list[Source] = []
    clips: list[Clip] = []
    for src in (intro_source, outro_source):
        if src is None:
            continue
        for existing in sources:
            if existing.id != src.id and existing.path.casefold() == src.path.casefold():
                raise TemplateError("intro and outro share a path but not a source id")
        if all(existing.id != src.id for existing in sources):
            sources.append(src.model_copy(deep=True))

    # Intro first, outro last; M2 inserts the main footage between them.
    if intro_source is not None:
        clips.append(_bookend_clip(intro_source))
    if outro_source is not None:
        clips.append(_bookend_clip(outro_source))

    voice_profiles = []
    if template.voice_profile is not None:
        voice_profiles.append(
            template.voice_profile.model_copy(deep=True, update={"id": new_id()})
        )

    extra: dict[str, int] = {}
    if seed is not None:
        extra["seed"] = seed

    return Project(
        name=clean,
        sources=sources,
        clips=clips,
        voice_profiles=voice_profiles,
        fx_chain=template.fx_chain.model_copy(deep=True),
        game_audio_db=template.game_audio_db,
        avatar=template.avatar.model_copy(deep=True),
        export=template.export.model_copy(deep=True),
        **extra,
    )