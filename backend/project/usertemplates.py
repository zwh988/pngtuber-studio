"""Channel templates saved from a project (M7 S6, decision 5).

"Save as template" writes the open project's bookends, voice profile (with its
reference clip), FX chain, game audio level, avatar settings and export settings to
``%APPDATA%\\PNGtuberStudio\\templates\\<folder>\\``:

- ``template.json``: a ``ChannelTemplate``; the reference clip path is relative to
  the template folder (``voice/<file>``), the avatar art folder and the bookends are
  absolute, so the template works for a project anywhere.
- ``voice/<file>``: a copy of the reference clip (a reference clip is not footage,
  rule 2 does not apply; projects copy it into ``media/voice/`` too).

"New project" picks a template: the built-in default (``templates/default_channel.json``,
id ``default``) or a saved one (id = its folder name). Applying a template to an
open project is not built (decision 5).

``template_from_project`` and ``template_info`` are pure; the rest is file I/O.
"""

import json
import os
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from pydantic import BaseModel, Field

from backend.avatar.scan import is_absolute_stored, resolve_art_folder
from backend.project.schema import BookendRef, ChannelTemplate, Project
from backend.project.template import (
    TemplateError,
    default_template_path,
    load_template_file,
)

BUILTIN_ID = "default"
TEMPLATE_FILE = "template.json"
VOICE_SUBDIR = "voice"
NAME_MAX = 60
_BAD_CHARS = set('<>:"/\\|?*')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class TemplateInfo(BaseModel):
    """One entry of ``GET /api/templates``."""

    id: str
    name: str
    builtin: bool
    intro: str | None = None  # file names of the bookends, for the picker
    outro: str | None = None
    voice_reference: str | None = None
    art_folder: str | None = None
    folder: str | None = None  # where a saved template lives


class TemplateList(BaseModel):
    templates: list[TemplateInfo] = Field(default_factory=list)  # built-in first, then by name
    problems: list[str] = Field(default_factory=list)  # saved templates that could not be read
    folder: str | None = None  # where saved templates go (None: saving is off)


# ---- pure ---------------------------------------------------------------------------


def template_folder_name(name: str) -> str:
    """The folder for a template name: the name itself, checked for Windows."""
    clean = " ".join(name.split())
    if not clean:
        raise TemplateError("the template needs a name")
    if len(clean) > NAME_MAX:
        raise TemplateError(f"the template name is longer than {NAME_MAX} characters")
    if any(c in _BAD_CHARS or ord(c) < 32 for c in clean):
        raise TemplateError('a template name cannot contain < > : " / \\ | ? *')
    if clean.endswith((".", " ")) or clean.split(".")[0].casefold() in _RESERVED:
        raise TemplateError(f"{clean!r} cannot be used as a name on Windows")
    if clean.casefold() == BUILTIN_ID:
        raise TemplateError(f"{clean!r} is the built-in template's name; pick another")
    return clean


def _bookends(project: Project) -> tuple[str | None, str | None]:
    """Paths of the external first and last clips (the template's bookends)."""
    track0 = [c for c in project.clips if c.track == 0]
    sources = {s.id: s for s in project.sources}

    def external_path(index: int) -> str | None:
        source = sources.get(track0[index].source_id)
        return source.path if source is not None and source.external else None

    if not track0:
        return None, None
    intro = external_path(0)
    outro = external_path(-1) if len(track0) > 1 else None
    return intro, outro


def template_from_project(
    project: Project, project_folder: Path, name: str
) -> tuple[ChannelTemplate, Path | None]:
    """The template for a project, plus the reference clip file to copy (or None).
    The template's reference clip path is ``voice/<file name>``."""
    clean = " ".join(name.split())
    intro, outro = _bookends(project)
    profile = None
    reference: Path | None = None
    if project.voice_profiles:
        first = project.voice_profiles[0]
        clips = []
        if first.reference_clips:
            rel = first.reference_clips[0]
            reference = project_folder / Path(*PurePosixPath(rel).parts)
            clips = [f"{VOICE_SUBDIR}/{PurePosixPath(rel).name}"]
        profile = first.model_copy(deep=True, update={"reference_clips": clips, "emotion_reference_clips": {}})
    avatar = project.avatar.model_copy(deep=True)
    if avatar.art_folder is not None and not is_absolute_stored(avatar.art_folder):
        avatar.art_folder = resolve_art_folder(avatar.art_folder, project_folder).resolve().as_posix()
    template = ChannelTemplate(
        name=clean,
        intro=BookendRef(path=intro) if intro is not None else None,
        outro=BookendRef(path=outro) if outro is not None else None,
        voice_profile=profile,
        fx_chain=project.fx_chain.model_copy(deep=True),
        avatar=avatar,
        export=project.export.model_copy(deep=True),
        game_audio_db=project.game_audio_db,
    )
    return template, reference


def _file_name(path: str | None) -> str | None:
    if path is None:
        return None
    return PureWindowsPath(path).name or path


def template_info(template_id: str, template: ChannelTemplate, *, builtin: bool, folder: Path | None) -> TemplateInfo:
    profile = template.voice_profile
    reference = profile.reference_clips[0] if profile is not None and profile.reference_clips else None
    return TemplateInfo(
        id=template_id,
        name=template.name,
        builtin=builtin,
        intro=_file_name(template.intro.path) if template.intro else None,
        outro=_file_name(template.outro.path) if template.outro else None,
        voice_reference=_file_name(reference),
        art_folder=template.avatar.art_folder,
        folder=str(folder) if folder is not None else None,
    )


# ---- I/O ----------------------------------------------------------------------------


def list_templates(store: Path | None, builtin_path: Path | None = None) -> TemplateList:
    builtin = load_template_file(builtin_path)
    result = TemplateList(
        templates=[template_info(BUILTIN_ID, builtin, builtin=True, folder=None)],
        folder=str(store) if store is not None else None,
    )
    if store is None or not store.is_dir():
        return result
    saved: list[TemplateInfo] = []
    for child in sorted(store.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir():
            continue
        try:
            saved.append(template_info(child.name, load_template_file(child / TEMPLATE_FILE), builtin=False, folder=child))
        except TemplateError as exc:
            result.problems.append(f"{child.name}: {exc}")
    result.templates.extend(sorted(saved, key=lambda t: t.name.casefold()))
    return result


def resolve_template(store: Path | None, template_id: str | None, builtin_path: Path | None = None) -> tuple[ChannelTemplate, Path | None]:
    """``(template, its folder)``; the built-in default has no folder."""
    if template_id is None or template_id == BUILTIN_ID:
        return load_template_file(builtin_path if builtin_path is not None else default_template_path()), None
    if store is None:
        raise TemplateError("saved templates are not available in this app instance")
    if template_id != template_folder_name(template_id):
        raise TemplateError(f"unknown template {template_id!r}")
    folder = store / template_id
    if not (folder / TEMPLATE_FILE).is_file():
        raise TemplateError(f"the template {template_id!r} was not found in {store}")
    return load_template_file(folder / TEMPLATE_FILE), folder


def template_reference(template: ChannelTemplate, folder: Path | None) -> Path | None:
    """The reference clip file a saved template carries, if any."""
    profile = template.voice_profile
    if folder is None or profile is None or not profile.reference_clips:
        return None
    rel = PurePosixPath(profile.reference_clips[0])
    if rel.is_absolute() or ".." in rel.parts:
        raise TemplateError("the template's reference clip must be inside its folder")
    return folder / Path(*rel.parts)


def save_template(store: Path, template: ChannelTemplate, reference: Path | None, *, replace: bool) -> TemplateInfo:
    """Write a template folder. An existing one with the same name is replaced only
    with ``replace``; its old reference clip copy goes too."""
    folder_name = template_folder_name(template.name)
    folder = store / folder_name
    if folder.exists() and not replace:
        raise TemplateError(f"a template named {folder_name!r} already exists")
    if reference is not None and not reference.is_file():
        raise TemplateError(f"the voice reference clip is missing: {reference}")
    store.mkdir(parents=True, exist_ok=True)
    staging = store / f".{folder_name}.{os.getpid()}.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        staging.mkdir()
        if reference is not None:
            (staging / VOICE_SUBDIR).mkdir()
            shutil.copy2(reference, staging / VOICE_SUBDIR / reference.name)
        data = template.model_dump(mode="json")
        (staging / TEMPLATE_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        old = None
        if folder.exists():
            old = store / f".{folder_name}.{os.getpid()}.old"
            os.replace(folder, old)
        os.replace(staging, folder)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return template_info(folder_name, template, builtin=False, folder=folder)
