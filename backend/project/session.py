"""The one project the app currently has open (M1-6).

``clean_folder_name`` is pure. ``Session`` does file I/O through ``store`` and
runs ffprobe (injectable) for footage and template bookend clips. Every
change made through the command stack is saved straight away (``on_change``).
Pass ``recent_path`` to record opened projects; ``None`` records nothing.
"""

import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from backend.audio.chainspec import FxChainError, processing_spec
from backend.audio.cleanup import (
    ENVELOPE_FILE,
    PREVIEW_FILE,
    envelope_keep_names,
    run_cache_cleanup,
    run_cleanup,
)
from backend.audio.clipfx import clip_fx_key, clip_processing_spec
from backend.audio.clipfx_render import AUDIO_FX_DIR, render_clip_fx
from backend.audio.clipimport import (
    AudioImportError,
    AudioImportResult,
    Decode,
    ImportedAudio,
    ensure_decoded,
    import_audio_file,
    make_ffmpeg_decoder,
)
from backend.audio.fxpresets import load_fx_presets_file
from backend.audio.fxstate import FxProcessing, FxState, build_fx_state
from backend.audio.prefetch import Prefetcher, plan_jobs
from backend.audio.processed import (
    TrimCache,
    _lock_for,
    ensure_processed,
    measure_bounds,
    trim_bounds_for,
)
from backend.audio.render import ProcessError, render_aligned_raw
from backend.audio.trim import (
    ManualTrimError,
    TrimBounds,
    spec_with_manual_trim,
    validate_manual_trim,
)
from backend.avatar.art import AvatarArt
from backend.avatar.envelope import (
    ENVELOPE_DIR_NAME,
    Envelope,
    EnvelopeReport,
    envelope_for,
)
from backend.avatar.preview import (
    PREVIEW_DIR_NAME,
    PreviewError,
    ensure_preview,
    preview_name,
)
from backend.avatar.scan import (
    ArtFolderError,
    AvatarState,
    avatar_status_text,
    build_avatar_state,
    resolve_art_folder,
    scan_art_folder,
    to_stored_path,
)
from backend.avatar.solver import build_solver
from backend.avatar.track import (
    FrameTrack,
    build_frame_track,
    build_input,
    input_version,
    placement_ids_needing_envelopes,
    sprite_path_for_key,
)
from backend.edl.anchoring import check_references, check_voice_references
from backend.export.job import EXPORTS_DIR, ExportDefaults
from backend.export.pipeline import ExportInputs
from backend.export.preflight import PreflightReport, preflight
from backend.export.tools import default_ffmpeg_path
from backend.oserrors import describe_error
from backend.project.audio_commands import (
    AddAudioClip,
    AddAudioFile,
    AddAudioLane,
    find_lane,
    free_lane_from,
)
from backend.project.avatar_commands import SetAvatarArtFolder
from backend.project.clip_commands import AddClip
from backend.project.commands import (
    AddSource,
    Command,
    CommandError,
    CommandStack,
    RelinkSource,
)
from backend.project.edit_ops import EditOp, build_command
from backend.project.footage import (
    FootageError,
    parse_probe,
    run_ffprobe,
    scan_footage,
)
from backend.project.fx_ops import FxEditOp, build_fx_command
from backend.project.laneimport import (
    ImportedLaneMedia,
    LaneImportError,
    LaneImportResult,
    import_image,
    import_video,
    media_kind,
)
from backend.project.line_commands import NoChange
from backend.project.line_ops import LineEditOp, build_line_command
from backend.project.recent import (
    RecentItem,
    add_recent,
    load_recent,
    remove_recent,
    save_recent,
)
from backend.project.relink import relink_mismatches, to_footage_relpath
from backend.project.schema import (
    AudioFile,
    ExportSettings,
    FxChain,
    ImageFile,
    Line,
    Project,
    Source,
    Take,
    new_id,
)
from backend.project.store import (
    ProjectError,
    create_project,
    load_project,
    project_file,
    save_project,
)
from backend.project.summary import (
    FootageReport,
    ProjectSummary,
    describe_source,
    summarize,
)
from backend.project.template import (
    TemplateError,
    apply_template,
    external_source,
)
from backend.project.timeline import EditResult, TimelineState, build_timeline
from backend.project.usertemplates import (
    TemplateInfo,
    TemplateList,
    list_templates,
    resolve_template,
    save_template,
    template_folder_name,
    template_from_project,
    template_reference,
)
from backend.project.video_lane_commands import (
    STILL_DEFAULT_MS,
    AddImageFile,
    AddLaneClip,
    AddVideoLane,
    find_video_lane,
    free_video_lane_from,
)
from backend.project.voice_commands import AddVoiceProfile, SetReferenceClip
from backend.voice.generation import GenerationError, GenerationPlan
from backend.voice.generation import plan_generation as build_generation_plan
from backend.voice.linebank import LineBankState, build_line_bank
from backend.voice.presets import EmotionPreset, PresetError, load_presets_file
from backend.voice.profile import VoiceState, build_voice_state
from backend.voice.reference import (
    AudioInfoFn,
    FileHashCache,
    VoiceProfileError,
    import_reference,
    read_audio_info,
)
from backend.voice.stretchrender import FX_DIR_NAME
from backend.voice.takes import (
    RAW_DIR,
    AddTakeResult,
    NewTake,
    StorageReport,
    TakeDeleteReport,
    TakeError,
    TakeItem,
    TakeRemoval,
    TakeTrimInfo,
    build_delete_report,
    build_storage_report,
    build_take,
    build_take_item,
    find_take_by_key,
    raw_take_relpath,
    remove_line_and_takes,
    remove_takes,
)
from backend.voice.takestore import TakeStore
from backend.voice.userpresets import (
    PresetEdit,
    PresetsState,
    build_presets_state,
    check_edit,
    default_user_presets_path,
    delete_user_presets,
    load_effective,
    save_user_presets,
)

Probe = Callable[[Path], dict[str, Any]]

# Clean-up of takes_fx runs when the prefetcher is idle, but not more often.
CLEANUP_EVERY_S = 30.0

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SessionError(Exception):
    """A user-facing problem creating or opening a project."""


def clean_folder_name(name: str) -> str:
    """Validate a project name that is also used as a Windows folder name."""
    text = name.strip()
    if not text:
        raise ValueError("project name must not be empty")
    if _BAD_CHARS.search(text):
        raise ValueError('project name must not contain < > : " / \\ | ? *')
    if text.endswith("."):
        raise ValueError("project name must not end with a dot")
    if text.split(".")[0].upper() in _RESERVED:
        raise ValueError(f"'{text}' is a reserved Windows name")
    return text


def _folder_bytes(folder: Path) -> int:
    """Total size of the files directly in ``folder`` (0 when it is missing)."""
    total = 0
    try:
        with os.scandir(folder) as scan:
            for item in scan:
                try:
                    if item.is_file(follow_symlinks=False):
                        total += item.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _preview_keep_names(art_folder: str | None, project_folder: Path) -> set[str] | None:
    """Preview file names of every sprite in the current art. Empty when no art
    folder is set; None when the folder cannot be read (then nothing is deleted)."""
    if art_folder is None:
        return set()
    root = resolve_art_folder(art_folder, project_folder)
    try:
        art = scan_art_folder(root)
        return {
            preview_name(root / Path(*rel.split("/")))
            for expression in art.expressions
            for rel in expression.sprites.values()
        }
    except (ArtFolderError, OSError):
        return None


class Session:
    def __init__(
        self,
        *,
        template_path: Path | None = None,
        probe: Probe | None = None,
        recent_path: Path | None = None,
        audio_info: AudioInfoFn | None = None,
        presets: dict[str, EmotionPreset] | None = None,
        fx_presets: dict[str, FxChain] | None = None,
        user_presets_path: Path | None = None,
        user_templates_dir: Path | None = None,
        decode: Decode | None = None,
    ) -> None:
        # Re-entrant: the stack's on_change callback runs while a command
        # method already holds the lock.
        self._lock = threading.RLock()
        self._template_path = template_path
        self._probe: Probe = probe if probe is not None else run_ffprobe
        self._recent_path = recent_path
        self._audio_info: AudioInfoFn = (
            audio_info if audio_info is not None else read_audio_info
        )
        self._hashes = FileHashCache()
        # M8-1: decodes imported music and sound effects to WAV (ffmpeg by default).
        self._decode: Decode = (
            decode if decode is not None else make_ffmpeg_decoder(default_ffmpeg_path())
        )
        self._trims = TrimCache()
        self._avatar_track: FrameTrack | None = None  # last frame track built (M5-6)
        # Loaded from templates/emotion_presets.json on first use when not given.
        self._presets: dict[str, EmotionPreset] | None = presets
        # Loaded from templates/fx_presets.json on first use when not given.
        self._fx_presets: dict[str, FxChain] | None = fx_presets
        # M7 S5: emotion presets edited in Settings (app-wide). None: built-in only,
        # and Settings cannot save (tests and the default app).
        self._user_presets_path = user_presets_path
        # M7 S6: where "Save as template" writes; None: only the built-in template.
        self._user_templates_dir = user_templates_dir
        self._folder: Path | None = None
        self._stack: CommandStack | None = None
        self._save_error: str | None = None
        self._scan_errors: list[str] = []
        # Off until ``enable_prefetch``: a plain Session starts no thread.
        self._prefetch: Prefetcher | None = None
        self._last_cleanup = float("-inf")

    # ---- project lifecycle -------------------------------------------------

    def current(self) -> ProjectSummary | None:
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            return self._summary()

    def new_project(
        self, parent: str, name: str, template_id: str | None = None
    ) -> ProjectSummary:
        try:
            clean = clean_folder_name(name)
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        parent_path = Path(parent.strip())
        if not parent.strip() or not parent_path.is_dir():
            raise SessionError(f"parent folder does not exist: {parent_path}")
        folder = parent_path / clean
        if project_file(folder).exists():
            raise SessionError(f"a project already exists in {folder}")

        template, template_folder = resolve_template(
            self._user_templates_dir, template_id, self._template_path
        )
        reference = template_reference(template, template_folder)
        intro = self._probe_bookend(template.intro.path) if template.intro else None
        outro = self._probe_bookend(template.outro.path) if template.outro else None
        project = apply_template(
            template, clean, intro_source=intro, outro_source=outro
        )

        with self._lock:
            folder.mkdir(exist_ok=True)
            if template_folder is not None and project.voice_profiles:
                # A saved template's clip path is relative to the template: copy the
                # clip into media/voice/ (M7 S6). A clip that fails its check leaves
                # the profile without one; the Voice section then says so.
                profile = project.voice_profiles[0]
                profile.reference_clips = []
                if reference is not None:
                    try:
                        imported = import_reference(
                            folder, reference, audio_info=self._audio_info, hashes=self._hashes
                        )
                    except VoiceProfileError:
                        pass
                    else:
                        profile.reference_clips = [imported.rel_path]
            create_project(folder, project)
            return self._set_open(folder, project)

    # ---- channel templates (M7 S6) -------------------------------------------

    def templates(self) -> TemplateList:
        try:
            return list_templates(self._user_templates_dir, self._template_path)
        except TemplateError as exc:
            raise SessionError(str(exc)) from exc

    def save_as_template(self, name: str, *, replace: bool = False) -> TemplateInfo:
        """Save the open project's channel settings as a template (decision 5)."""
        if self._user_templates_dir is None:
            raise SessionError("saving templates is not available in this app instance")
        with self._lock:
            folder, stack = self._require_open()
            try:
                template_folder_name(name)
                template, reference = template_from_project(stack.project, folder, name)
                return save_template(
                    self._user_templates_dir, template, reference, replace=replace
                )
            except TemplateError as exc:
                raise SessionError(str(exc)) from exc
            except OSError as exc:
                raise SessionError(f"cannot save the template: {describe_error(exc)}") from exc

    def open_project(self, folder: str) -> ProjectSummary:
        folder_path = Path(folder.strip())
        if not folder.strip() or not project_file(folder_path).is_file():
            raise SessionError(f"no project.json found in {folder_path}")
        project = load_project(folder_path)
        with self._lock:
            return self._set_open(folder_path, project)

    # ---- footage -----------------------------------------------------------

    def footage(self) -> FootageReport:
        with self._lock:
            folder, stack = self._require_open()
            return self._report(folder, stack.project, added=0)

    def rescan_footage(self) -> FootageReport:
        with self._lock:
            folder, stack = self._require_open()
            added = self._scan(folder, stack)
            return self._report(folder, stack.project, added=added)

    def relink_source(self, source_id: str, new_path: str) -> FootageReport:
        """Point a footage source at a moved file, after checking it matches."""
        with self._lock:
            folder, stack = self._require_open()
            source = next(
                (s for s in stack.project.sources if s.id == source_id), None
            )
            if source is None:
                raise SessionError("unknown footage source")
            if source.external:
                raise SessionError(
                    "relinking template bookend clips is not supported yet"
                )
            picked = Path(new_path.strip())
            if not picked.is_file():
                raise SessionError(f"file not found: {picked}")
            try:
                rel = to_footage_relpath(folder.resolve(), picked.resolve())
            except ValueError as exc:
                raise SessionError(str(exc)) from exc
            if rel.casefold() == source.path.casefold():
                return self._report(folder, stack.project, added=0)

            probed = parse_probe(self._probe(picked), rel)
            problems = relink_mismatches(source, probed)
            if problems:
                raise SessionError(
                    "that file does not match the original footage: "
                    + "; ".join(problems)
                )
            try:
                stack.execute(RelinkSource(source.id, rel))
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._report(folder, stack.project, added=0)

    # ---- line bank ---------------------------------------------------------

    def lines(self) -> LineBankState:
        with self._lock:
            return self._line_bank_state()

    def edit_lines(
        self, ops: Sequence[LineEditOp], label: str | None = None
    ) -> LineBankState:
        """Apply line bank edits. One op without a label is a plain undo step;
        several ops (or a label) run as one group, so they undo together and
        either all apply or none do. An op that would change nothing is skipped
        and makes no undo step."""
        if not ops:
            raise SessionError("no edits given")
        with self._lock:
            _, stack = self._require_open()
            emotions = self._presets_or_raise()
            try:
                commands = [
                    build_line_command(op, known_emotions=emotions.keys())
                    for op in ops
                ]
                if len(commands) == 1 and label is None:
                    self._execute_unless_no_change(stack, commands[0])
                else:
                    with stack.group(label or "Edit lines"):
                        for command in commands:
                            self._execute_unless_no_change(stack, command)
            except (CommandError, ValueError) as exc:
                raise SessionError(str(exc)) from exc
            return self._line_bank_state()

    # ---- voice chain -------------------------------------------------------

    def fx(self) -> FxState:
        with self._lock:
            return self._fx_state()

    def edit_fx(self, ops: Sequence[FxEditOp], label: str | None = None) -> FxState:
        """Apply voice chain edits (the chain, the game audio level). One op without
        a label is a plain undo step; several ops (or a label) run as one group, so
        they undo together and either all apply or none do. An op that would change
        nothing is skipped and makes no undo step."""
        if not ops:
            raise SessionError("no edits given")
        with self._lock:
            _, stack = self._require_open()
            try:
                commands = [build_fx_command(op) for op in ops]
                if len(commands) == 1 and label is None:
                    self._execute_unless_no_change(stack, commands[0])
                else:
                    with stack.group(label or "Edit voice chain"):
                        for command in commands:
                            self._execute_unless_no_change(stack, command)
            except (CommandError, ValueError) as exc:
                raise SessionError(str(exc)) from exc
            return self._fx_state()

    def enable_prefetch(self, prefetcher: Prefetcher | None = None) -> None:
        """Render the processed takes the placed lines play in the background, now
        and after every change, and clean ``takes_fx`` when idle. The app calls this
        once; tests leave it off, so a plain ``Session()`` starts no thread."""
        with self._lock:
            if self._prefetch is not None:
                return
            self._prefetch = (
                prefetcher
                if prefetcher is not None
                else Prefetcher(self._trims, on_idle=self._cleanup_fx)
            )
            self._schedule_prefetch()

    def shutdown_prefetch(self) -> None:
        with self._lock:
            prefetch, self._prefetch = self._prefetch, None
        if prefetch is not None:
            prefetch.close()

    # ---- takes -------------------------------------------------------------

    def takes(self, line_id: str) -> list[TakeItem]:
        """The takes of one line, oldest first."""
        with self._lock:
            folder, stack = self._require_open()
            line = self._line_or_error(stack.project, line_id)
            store = TakeStore(folder)
            return [
                build_take_item(take, line, store.size(take.raw_file) is not None)
                for take in stack.project.takes
                if take.line_id == line_id
            ]

    def reuse_take(
        self,
        new: NewTake,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult | None:
        """Reuse an existing take with the same raw key (rule 3), or return None.

        Call this before spending GPU time. A take of another line with the same
        key is copied (a new take for this line, no generation). Not undoable.
        ``project_key`` (from ``project_key()``) refuses the call when another
        project has been opened since.
        """
        with self._lock:
            self._check_project(project_key)
            folder, stack = self._require_open()
            project = stack.project
            line = self._line_or_error(project, new.line_id)
            store = TakeStore(folder)
            existing = find_take_by_key(
                project, new.raw_key, prefer_line_id=new.line_id
            )
            if existing is None or store.size(existing.raw_file) is None:
                return None
            take = existing
            copied = False
            try:
                if existing.line_id != new.line_id:
                    take_id = self._free_take_id(project, new.take_id)
                    rel = raw_take_relpath(take_id)
                    take = build_take(new, take_id, rel, existing.duration_ms)
                    store.copy_raw(existing.raw_file, rel)
                    project.takes.append(take)
                    copied = True
            except TakeError as exc:
                raise SessionError(str(exc)) from exc
            return self._finish_take(
                line, take, reused=True, make_active=make_active, changed=copied
            )

    def add_take(
        self,
        new: NewTake,
        samples: np.ndarray,
        sample_rate: int,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult:
        """Store a generated take: write the file, record it, save the project.

        Takes persist and are not undoable (rule 1). If a take with this key
        already exists it is reused instead (see ``reuse_take``). ``project_key``
        refuses the call when another project has been opened since the request.
        """
        with self._lock:
            self._check_project(project_key)
            reused = self.reuse_take(
                new, make_active=make_active, project_key=project_key
            )
            if reused is not None:
                return reused
            folder, stack = self._require_open()
            project = stack.project
            line = self._line_or_error(project, new.line_id)
            store = TakeStore(folder)
            existing = find_take_by_key(
                project, new.raw_key, prefer_line_id=new.line_id
            )
            try:
                if existing is not None and existing.line_id == new.line_id:
                    # The record is there but its file is gone: write it back.
                    existing.duration_ms = store.write_raw(
                        existing.raw_file, samples, sample_rate
                    )
                    take = existing
                else:
                    take_id = self._free_take_id(project, new.take_id)
                    rel = raw_take_relpath(take_id)
                    take = build_take(new, take_id, rel, 0)  # validates first
                    take.duration_ms = store.write_raw(rel, samples, sample_rate)
                    project.takes.append(take)
            except TakeError as exc:
                raise SessionError(str(exc)) from exc
            return self._finish_take(
                line, take, reused=False, make_active=make_active, changed=True
            )

    def delete_take(self, take_id: str) -> TakeDeleteReport:
        """Delete one take and its file (storage manager; not undoable)."""
        return self._delete_takes(
            lambda project: remove_takes(project, [take_id]), removed_line=False
        )

    def delete_line(self, line_id: str) -> TakeDeleteReport:
        """Delete a line and all its takes (storage manager; not undoable)."""
        return self._delete_takes(
            lambda project: remove_line_and_takes(project, line_id),
            removed_line=True,
        )

    def plan_generation(
        self,
        line_id: str,
        *,
        model_version: str,
        reroll: bool = False,
        project_key: str | None = None,
    ) -> GenerationPlan:
        """Plan one generation: parameters, seed, raw key, chunks (no GPU, no
        writes). Pair it with ``reuse_take`` and ``add_take``."""
        with self._lock:
            self._check_project(project_key)
            folder, stack = self._require_open()
            voice = self._voice_state(folder, stack.project)
            if (
                not voice.ready
                or voice.profile_id is None
                or voice.hash is None
                or voice.reference_path is None
            ):
                detail = "; ".join(voice.problems) or voice.status
                raise SessionError(
                    f"the voice reference is not ready: {detail}. Choose a reference "
                    "clip in the Voice section of the project screen."
                )
            try:
                return build_generation_plan(
                    stack.project,
                    line_id,
                    self._presets_or_raise(),
                    voice_profile_id=voice.profile_id,
                    reference_hash=voice.hash,
                    reference_path=str(folder / voice.reference_path),
                    model_version=model_version,
                    reroll=reroll,
                )
            except GenerationError as exc:
                raise SessionError(str(exc)) from exc

    def take_path(self, take_id: str) -> Path | None:
        """Disk path of a take file of the open project, for the media endpoint.
        None when no project is open or the id is not one of its takes."""
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            take = next(
                (t for t in self._stack.project.takes if t.id == take_id), None
            )
            if take is None:
                return None
            try:
                return TakeStore(self._folder).path(take.raw_file)
            except TakeError:
                return None

    def take_trim(
        self,
        take_id: str,
        *,
        preview: bool = False,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TakeTrimInfo:
        """Trim view of one take for the trimmer (M5-0): the stored cut points, or with
        ``preview`` the given ones, and where the automatic trim keeps the take inside
        them. Reads the raw take (CPU only); nothing is changed or saved."""
        with self._lock:
            _, stack = self._require_open()
            assert self._folder is not None
            take = next((t for t in stack.project.takes if t.id == take_id), None)
            if take is None:
                raise SessionError(f"unknown take id {take_id!r}")
            try:
                raw_path = TakeStore(self._folder).path(take.raw_file)
            except TakeError as exc:
                raise SessionError(str(exc)) from exc
            stored = (take.trim_start_ms, take.trim_end_ms)
            duration_ms = take.duration_ms
        cuts = stored
        if preview:
            try:
                cuts = validate_manual_trim(start_ms, end_ms, duration_ms)
            except ManualTrimError as exc:
                raise SessionError(str(exc)) from exc
        try:
            if cuts == stored:
                bounds = trim_bounds_for(
                    raw_path, self._trims, manual_start_ms=cuts[0], manual_end_ms=cuts[1]
                )
            else:  # a preview: measure without touching the stored sidecar
                bounds = measure_bounds(raw_path, cuts[0], cuts[1])
        except ProcessError as exc:
            raise SessionError(str(exc)) from exc
        rate = bounds.sample_rate
        return TakeTrimInfo(
            take_id=take_id,
            duration_ms=duration_ms,
            trim_start_ms=cuts[0],
            trim_end_ms=cuts[1],
            stored_start_ms=stored[0],
            stored_end_ms=stored[1],
            auto_start_ms=bounds.start * 1000 // rate,
            auto_end_ms=-(-bounds.end * 1000 // rate),
            silent=bounds.silent,
        )

    def processed_take_path(self, take_id: str, stretch: float = 1.0) -> Path | None:
        """Disk path of a take run through the open project's voice chain (trim,
        stretch, EQ, compressor, effects, loudness), rendered first when it does not
        exist yet (rule 3: one file per key, never rendered twice). None when no
        project is open, the id is not one of its takes or its raw file is gone.

        The render runs outside the session lock, so editing is never blocked by it.
        """
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            project = self._stack.project
            take = next((t for t in project.takes if t.id == take_id), None)
            if take is None:
                return None
            try:
                raw_path = TakeStore(self._folder).path(take.raw_file)
            except TakeError:
                return None
            try:
                spec = processing_spec(project.fx_chain)
            except FxChainError as exc:
                raise SessionError(f"the voice chain cannot be used: {exc}") from exc
            spec = spec_with_manual_trim(spec, take.trim_start_ms, take.trim_end_ms)
            raw_key = take.raw_key
        if not raw_path.is_file():
            return None
        try:
            return ensure_processed(raw_path, raw_key, stretch, spec, cache=self._trims)
        except ProcessError as exc:
            raise SessionError(str(exc)) from exc

    def aligned_raw_take(self, take_id: str, stretch: float = 1.0) -> tuple[np.ndarray, int] | None:
        """A raw take cut, faded and stretched like its processed take, without the
        voice chain (M6-2 ``voice_raw.wav``). None when no project is open, the id is
        not one of its takes or its raw file is gone. Outside the lock, like renders."""
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            project = self._stack.project
            take = next((t for t in project.takes if t.id == take_id), None)
            if take is None:
                return None
            try:
                raw_path = TakeStore(self._folder).path(take.raw_file)
            except TakeError:
                return None
            try:
                spec = processing_spec(project.fx_chain)
            except FxChainError as exc:
                raise SessionError(f"the voice chain cannot be used: {exc}") from exc
            spec = spec_with_manual_trim(spec, take.trim_start_ms, take.trim_end_ms)
            cuts = (take.trim_start_ms, take.trim_end_ms)
        if not raw_path.is_file():
            return None
        try:
            bounds = trim_bounds_for(
                raw_path, self._trims, manual_start_ms=cuts[0], manual_end_ms=cuts[1]
            )
            return render_aligned_raw(raw_path, spec, stretch, bounds)
        except ProcessError as exc:
            raise SessionError(str(exc)) from exc

    def export_inputs(self) -> ExportInputs:
        """A snapshot of what an export needs (M6): the project, its timeline, the
        footage paths, the avatar frame track (the one the preview draws) and the art."""
        with self._lock:
            folder, stack = self._require_open()
            project = stack.project.model_copy(deep=True)
            timeline = self._timeline_state()
            art = self._art_or_none(folder, project)
            art_root = (
                None
                if project.avatar.art_folder is None
                else resolve_art_folder(project.avatar.art_folder, folder)
            )
        paths: dict[str, Path] = {}
        used = [clip.source_id for clip in timeline.clips]
        used += [c.source_id for c in timeline.lane_clips if c.source_id is not None]
        for source_id in used:
            path = self.source_path(source_id)
            if path is not None:
                paths[source_id] = path
        # M8-2: images on the video lanes.
        image_paths = {image.id: folder / image.path for image in project.image_files}
        track = self.avatar_track() if art is not None else None
        # M8-1: decoded WAVs of the imported audio (made again when missing; a file that
        # cannot be decoded is left out and the export reports it).
        audio_paths: dict[str, Path] = {}
        for audio_file in project.audio_files:
            try:
                decoded = self.audio_decoded_path(audio_file.id)
            except SessionError:
                continue
            if decoded is not None:
                audio_paths[audio_file.id] = decoded
        # M8-4: the rendered FX file of each audio clip that has FX (the preview plays it too).
        audio_fx_paths: dict[str, Path] = {}
        for sound in project.audio_clips:
            if sound.fx is None:
                continue
            try:
                rendered = self.audio_clip_fx_path(sound.id)
            except SessionError:
                continue  # pre-flight reported it
            if rendered is not None:
                audio_fx_paths[sound.id] = rendered
        return ExportInputs(
            project=project,
            timeline=timeline,
            source_paths=paths,
            track=track,
            art=art,
            art_root=art_root,
            audio_paths=audio_paths,
            audio_fx_paths=audio_fx_paths,
            image_paths=image_paths,
        )

    def export_defaults(self) -> ExportDefaults:
        """The export screen's starting choices: the project's ``exports`` folder and
        its export settings (M6-7)."""
        with self._lock:
            folder, stack = self._require_open()
            settings = stack.project.export
        return ExportDefaults(
            folder=str(folder / EXPORTS_DIR),
            include_overlay=settings.include_avatar_overlay,
            include_raw_links=settings.include_raw_video_link,
            unload_voice=settings.unload_tts_before_export,
            height=settings.height,
            fps=str(settings.fps),
        )

    def export_preflight(self, tools_problem: str | None = None) -> PreflightReport:
        """What blocks or needs confirming before an export (M6-1). ``tools_problem``
        is the ffmpeg / NVENC check, run by the caller (it starts a process)."""
        with self._lock:
            folder, stack = self._require_open()
            project = stack.project
            timeline = self._timeline_state()
            store = TakeStore(folder)
            placed = {p.take_id for p in timeline.placements if p.take_id is not None}
            missing: set[str] = set()
            for take in project.takes:
                if take.id not in placed:
                    continue
                try:
                    if not store.path(take.raw_file).is_file():
                        missing.add(take.id)
                except TakeError:
                    missing.add(take.id)
            art = self._avatar_state(folder, stack)
            used_files = {c.file_id for c in project.audio_clips}
            missing_audio = {
                f.id
                for f in project.audio_files
                if f.id in used_files and not (folder / f.path).is_file()
            }
            used_images = {c.image_id for c in project.lane_clips if c.image_id}
            missing_images = {
                i.id
                for i in project.image_files
                if i.id in used_images and not (folder / i.path).is_file()
            }
            fx_clips = [
                c.id for c in project.audio_clips if c.fx is not None and c.file_id not in missing_audio
            ]
        # M8-4: render every audio clip's FX now (outside the lock), so a render that fails
        # stops the export here and the export itself finds the files ready.
        fx_problems: dict[str, str] = {}
        for clip_id in fx_clips:
            try:
                self.audio_clip_fx_path(clip_id)
            except SessionError as exc:
                fx_problems[clip_id] = str(exc)
        return preflight(
            project,
            timeline,
            missing_take_ids=missing,
            art_status=art.status,
            art_problem=art.problem,
            art_warnings=art.warnings,
            tools_problem=tools_problem,
            missing_audio_file_ids=missing_audio,
            missing_image_ids=missing_images,
            audio_fx_problems=fx_problems,
        )

    def envelope(self, take_id: str, stretch: float = 1.0) -> EnvelopeReport | None:
        """Loudness envelope (M5-2) of a take as it plays: the processed file for this
        stretch, rendered first when needed, then measured once and cached in
        ``media/envelopes/``. None when the take or its file does not exist."""
        path = self.processed_take_path(take_id, stretch)
        if path is None:
            return None
        try:
            found = envelope_for(path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SessionError(f"cannot measure the take's loudness: {exc}") from exc
        return EnvelopeReport(
            take_id=take_id, stretch=stretch, hop_ms=found.hop_ms, values=list(found.values)
        )

    def storage(self) -> StorageReport:
        """Disk use per line and take, plus files no take points at."""
        with self._lock:
            folder, stack = self._require_open()
            store = TakeStore(folder)
            sizes = {
                take.raw_file: store.size(take.raw_file) for take in stack.project.takes
            }
            report = build_storage_report(
                stack.project, sizes, store.unreferenced(set(sizes))
            )
        media = folder / "media"
        cache = sum(
            _folder_bytes(media / name)
            for name in (FX_DIR_NAME, ENVELOPE_DIR_NAME, PREVIEW_DIR_NAME)
        )
        return report.model_copy(update={"cache_bytes": cache})

    def project_key(self) -> str | None:
        """Identifies the open project (its folder), or None when none is open.
        The job queue passes it back so a job requested for one project can
        never write into another."""
        with self._lock:
            return None if self._folder is None else str(self._folder)

    def _check_project(self, expected: str | None) -> None:
        if expected is None:
            return
        if self._folder is None or str(self._folder) != expected:
            raise SessionError(
                "the open project changed since this job was requested"
            )

    # ---- voice profile -----------------------------------------------------

    def voice(self) -> VoiceState:
        """State of the project's voice profile (the first one; v1 has one)."""
        with self._lock:
            folder, stack = self._require_open()
            return self._voice_state(folder, stack.project)

    def set_voice_reference(self, path: str) -> VoiceState:
        """Check a clip, copy it into ``media/voice/`` and make it the reference.

        Creates the voice profile first if the project has none. The edit is one
        undo step.
        """
        with self._lock:
            folder, stack = self._require_open()
            picked = Path(path.strip())
            if not path.strip() or not picked.is_file():
                raise SessionError(f"file not found: {picked}")
            try:
                imported = import_reference(
                    folder,
                    picked,
                    audio_info=self._audio_info,
                    hashes=self._hashes,
                )
            except VoiceProfileError as exc:
                raise SessionError(str(exc)) from exc
            profiles = stack.project.voice_profiles
            try:
                if not profiles:
                    adding = AddVoiceProfile("Default")
                    with stack.group("Set voice reference"):
                        stack.execute(adding)
                        stack.execute(
                            SetReferenceClip(adding.profile_id, imported.rel_path)
                        )
                elif profiles[0].reference_clips != [imported.rel_path]:
                    stack.execute(SetReferenceClip(profiles[0].id, imported.rel_path))
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._voice_state(folder, stack.project)

    # ---- avatar art (M5-1) --------------------------------------------------

    def avatar(self) -> AvatarState:
        """The project's avatar art: folder, expressions, warnings (scanned now)."""
        with self._lock:
            folder, stack = self._require_open()
            return self._avatar_state(folder, stack)

    def set_avatar_folder(self, path: str | None) -> AvatarState:
        """Point the project at an art folder on disk (None or "" clears it). The
        folder must exist; it is stored relative when inside the project, otherwise
        as an absolute POSIX path. Never copied. One undo step."""
        with self._lock:
            folder, stack = self._require_open()
            stored: str | None = None
            if path is not None and path.strip():
                picked = Path(path.strip())
                if not picked.is_dir():
                    raise SessionError(f"folder not found: {picked}")
                stored = to_stored_path(picked, folder)
            try:
                stack.execute(SetAvatarArtFolder(stored))
            except NoChange:
                pass
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._avatar_state(folder, stack)

    def avatar_track(self) -> FrameTrack:
        """The sampled frame track the preview draws (decision 13). Built from the
        current project; reused while ``version`` is unchanged. Envelopes of placed
        takes are made on the way (processed files rendered first when missing)."""
        with self._lock:
            folder, stack = self._require_open()
            project = stack.project.model_copy(deep=True)
            timeline = self._timeline_state()
            art = self._art_or_none(folder, project)
            presets = self._preset_expressions()
        envelopes: dict[str, Envelope] = {}
        for placement_id, take_id, stretch in placement_ids_needing_envelopes(timeline):
            try:
                report = self.envelope(take_id, stretch)
            except SessionError:
                continue  # a take that cannot be measured keeps its mouth closed
            if report is not None:
                envelopes[placement_id] = Envelope(report.hop_ms, tuple(report.values))
        inp = build_input(project, timeline, envelopes, art, presets)
        version = input_version(inp, art)
        cached = self._avatar_track
        if cached is not None and cached.version == version:
            return cached
        track = build_frame_track(build_solver(inp), art, version)
        self._avatar_track = track
        return track

    def avatar_sprite_path(self, expression: str, state: str) -> Path | None:
        """Downscaled preview copy of one sprite of the project's art, made on first
        request (``media/avatar_preview/``). Only sprites the loader found are served:
        the URL names an expression and a state, never a path."""
        with self._lock:
            folder, stack = self._require_open()
            art_folder = stack.project.avatar.art_folder
        if art_folder is None:
            return None
        root = resolve_art_folder(art_folder, folder)
        try:
            art = scan_art_folder(root)
        except ArtFolderError:
            return None
        rel = sprite_path_for_key(art, expression, state)
        if rel is None:
            return None
        try:
            return ensure_preview(root / Path(*rel.split("/")), folder / "media" / PREVIEW_DIR_NAME)
        except PreviewError as exc:
            raise SessionError(str(exc)) from exc

    def _art_or_none(self, folder: Path, project: Project) -> AvatarArt | None:
        if project.avatar.art_folder is None:
            return None
        try:
            return scan_art_folder(resolve_art_folder(project.avatar.art_folder, folder))
        except ArtFolderError:
            return None

    def _preset_expressions(self) -> dict[str, str]:
        try:
            return {name: preset.expression for name, preset in self._presets_or_raise().items()}
        except SessionError:
            return {}

    def _avatar_state(self, folder: Path, stack: CommandStack) -> AvatarState:
        state = build_avatar_state(stack.project.avatar.art_folder, folder)
        return state.model_copy(
            update={
                "can_undo": stack.can_undo,
                "can_redo": stack.can_redo,
                "undo_label": stack.undo_label,
                "redo_label": stack.redo_label,
                "save_error": self._save_error,
            }
        )

    # ---- media -------------------------------------------------------------

    def source_path(self, source_id: str) -> Path | None:
        """Disk path of a source of the open project, for the media endpoint.

        None when no project is open or the id is not one of its sources. The
        path comes only from the project's source list, never from the browser.
        """
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            source = next(
                (s for s in self._stack.project.sources if s.id == source_id), None
            )
            if source is None:
                return None
            return Path(source.path) if source.external else self._folder / source.path

    # ---- timeline ----------------------------------------------------------

    def timeline(self) -> TimelineState:
        with self._lock:
            return self._timeline_state()

    def add_clip(self, source_id: str, position: int | None = None) -> TimelineState:
        """Put a whole source on the timeline (before a trailing bookend)."""
        with self._lock:
            _, stack = self._require_open()
            try:
                stack.execute(AddClip(source_id, position=position))
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._timeline_state()

    def undo(self) -> EditResult:
        with self._lock:
            _, stack = self._require_open()
            try:
                label = stack.undo()
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return EditResult(label=label, timeline=self._timeline_state())

    def redo(self) -> EditResult:
        with self._lock:
            _, stack = self._require_open()
            try:
                label = stack.redo()
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return EditResult(label=label, timeline=self._timeline_state())

    def edit(self, ops: Sequence[EditOp], label: str | None = None) -> TimelineState:
        """Apply edit ops. One op without a label is a plain undo step; several
        ops (or a label) run as one group, so they undo together and either
        all apply or none do."""
        if not ops:
            raise SessionError("no edits given")
        with self._lock:
            _, stack = self._require_open()
            try:
                if len(ops) == 1 and label is None:
                    stack.execute(build_command(ops[0]))
                else:
                    with stack.group(label or "Edit"):
                        for op in ops:
                            stack.execute(build_command(op))
            except (CommandError, ValueError) as exc:
                raise SessionError(str(exc)) from exc
            return self._timeline_state()

    # ---- audio lanes (M8-1) ---------------------------------------------------

    def import_audio(
        self,
        paths: Sequence[str],
        lane_id: str | None,
        timeline_ms: int,
        *,
        new_lane: bool = False,
    ) -> AudioImportResult:
        """Copy dropped files into ``audio/`` and put them on the timeline.

        The files go one after another from ``timeline_ms``, each on the first
        lane from ``lane_id`` down with room for it (a new lane below the last when
        none has). ``new_lane`` puts them on a new lane below the last instead. All
        placed files (and a new lane) are one undo step. A file that cannot be used
        is reported in ``errors``; the others are still placed.
        """
        if timeline_ms < 0:
            raise SessionError("timeline time must not be negative")
        with self._lock:
            folder, stack = self._require_open()
            known = [f.model_copy() for f in stack.project.audio_files]
        # Copying, probing and decoding happen outside the lock.
        prepared: list[tuple[AudioFile, bool]] = []
        errors: list[str] = []
        for raw in paths:
            source = Path(raw.strip())
            if not raw.strip() or not source.is_file():
                errors.append(f"{source.name or raw}: file not found")
                continue
            try:
                audio_file, reused = import_audio_file(
                    folder, source, known, probe=self._probe, decode=self._decode
                )
            except AudioImportError as exc:
                errors.append(str(exc))
                continue
            except OSError as exc:
                errors.append(f"{source.name}: {describe_error(exc)}")
                continue
            if not reused:
                known.append(audio_file)
            prepared.append((audio_file, reused))
        with self._lock:
            now_folder, stack = self._require_open()
            if now_folder != folder:
                raise SessionError("the project changed while the files were imported")
            project = stack.project
            imported: list[ImportedAudio] = []
            if prepared:
                registered = {f.id for f in project.audio_files}
                try:
                    target = lane_id if lane_id is not None else project.audio_lanes[0].id
                    if not new_lane:
                        find_lane(project, target)
                    label = (
                        f"Import {prepared[0][0].name}"
                        if len(prepared) == 1
                        else f"Import {len(prepared)} audio files"
                    )
                    start = timeline_ms
                    with stack.group(label):
                        if new_lane:
                            adding_lane = AddAudioLane()
                            stack.execute(adding_lane)
                            target = adding_lane.lane_id
                        for audio_file, reused in prepared:
                            if audio_file.id not in registered:
                                stack.execute(AddAudioFile(audio_file))
                                registered.add(audio_file.id)
                            lane = free_lane_from(project, target, start, audio_file.duration_ms)
                            if lane is None:
                                adding = AddAudioLane()
                                stack.execute(adding)
                                lane = adding.lane_id
                            adding_clip = AddAudioClip(audio_file.id, lane, start)
                            stack.execute(adding_clip)
                            imported.append(
                                ImportedAudio(
                                    name=audio_file.name,
                                    clip_id=adding_clip.clip_id,
                                    lane_id=lane,
                                    lane_name=find_lane(project, lane)[1].name,
                                    timeline_ms=start,
                                    reused=reused,
                                )
                            )
                            start += audio_file.duration_ms
                except (CommandError, IndexError) as exc:
                    raise SessionError(f"could not place the audio: {exc}") from exc
            return AudioImportResult(
                imported=imported, errors=errors, timeline=self._timeline_state()
            )

    # ---- video lanes (M8-2) ---------------------------------------------------

    def import_lane_media(
        self,
        paths: Sequence[str],
        lane_id: str | None,
        timeline_ms: int,
        *,
        new_lane: bool = False,
    ) -> LaneImportResult:
        """Bring dropped images and videos onto the video lanes.

        Images are copied into ``images/``; a video from outside ``footage/`` is
        copied there first. The files go one after another from ``timeline_ms``, each
        on the first unlocked lane from ``lane_id`` up with room (a new lane on top
        when none has; the lowest lane when ``lane_id`` is None; a new lane first when
        ``new_lane`` or when there are no lanes). One undo step; a file that cannot be
        used is reported in ``errors`` and the others are still placed.
        """
        if timeline_ms < 0:
            raise SessionError("timeline time must not be negative")
        with self._lock:
            folder, stack = self._require_open()
            known_images = [i.model_copy() for i in stack.project.image_files]
            known_sources = [s.model_copy() for s in stack.project.sources]
        prepared: list[tuple[str, ImageFile | Source, bool, int, bool]] = []
        errors: list[str] = []
        for raw in paths:
            source_path = Path(raw.strip())
            if not raw.strip() or not source_path.is_file():
                errors.append(f"{source_path.name or raw}: file not found")
                continue
            kind = media_kind(source_path.name)
            try:
                if kind == "image":
                    image, reused = import_image(folder, source_path, known_images)
                    if not reused:
                        known_images.append(image)
                    prepared.append(("image", image, not reused, STILL_DEFAULT_MS, False))
                elif kind == "video":
                    video, is_new, copied = import_video(
                        folder, source_path, known_sources, probe=self._probe
                    )
                    if is_new:
                        known_sources.append(video)
                    prepared.append(("video", video, is_new, video.duration_ms, copied))
                else:
                    errors.append(
                        f"{source_path.name}: not an image or video "
                        "(PNG, JPG, or a video like MKV or MP4)"
                    )
            except LaneImportError as exc:
                errors.append(str(exc))
            except OSError as exc:
                errors.append(f"{source_path.name}: {describe_error(exc)}")
        with self._lock:
            now_folder, stack = self._require_open()
            if now_folder != folder:
                raise SessionError("the project changed while the files were imported")
            project = stack.project
            imported: list[ImportedLaneMedia] = []
            if prepared:
                images_known = {i.id for i in project.image_files}
                sources_known = {s.id for s in project.sources}
                label = (
                    f"Import {self._media_name(prepared[0][1])}"
                    if len(prepared) == 1
                    else f"Import {len(prepared)} files to video lanes"
                )
                try:
                    if lane_id is not None and not new_lane:
                        find_video_lane(project, lane_id)
                    start = timeline_ms
                    with stack.group(label):
                        if new_lane or not project.video_lanes:
                            adding_lane = AddVideoLane()
                            stack.execute(adding_lane)
                            target = adding_lane.lane_id
                        else:
                            target = lane_id if lane_id is not None else project.video_lanes[0].id
                        for kind, item, is_new, length, copied in prepared:
                            if isinstance(item, ImageFile):
                                if is_new and item.id not in images_known:
                                    stack.execute(AddImageFile(item))
                                    images_known.add(item.id)
                            elif is_new and item.id not in sources_known:
                                stack.execute(AddSource(item))
                                sources_known.add(item.id)
                            lane = free_video_lane_from(project, target, start, length)
                            if lane is None:
                                adding = AddVideoLane()
                                stack.execute(adding)
                                lane = adding.lane_id
                            adding_clip = AddLaneClip(
                                lane,
                                start,
                                source_id=item.id if isinstance(item, Source) else None,
                                image_id=item.id if isinstance(item, ImageFile) else None,
                                length_ms=length,
                            )
                            stack.execute(adding_clip)
                            imported.append(
                                ImportedLaneMedia(
                                    name=self._media_name(item),
                                    kind="image" if kind == "image" else "video",
                                    clip_id=adding_clip.clip_id,
                                    lane_id=lane,
                                    lane_name=find_video_lane(project, lane)[1].name,
                                    timeline_ms=start,
                                    copied_to_footage=copied,
                                )
                            )
                            start += length
                except CommandError as exc:
                    raise SessionError(f"could not place the files: {exc}") from exc
            return LaneImportResult(
                imported=imported, errors=errors, timeline=self._timeline_state()
            )

    @staticmethod
    def _media_name(item: "ImageFile | Source") -> str:
        return item.name if isinstance(item, ImageFile) else item.path.rsplit("/", 1)[-1]

    def image_path(self, image_id: str) -> Path | None:
        """Disk path of an imported image, from the project (never from the request)."""
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            image = next((i for i in self._stack.project.image_files if i.id == image_id), None)
            return None if image is None else self._folder / image.path

    def audio_decoded_path(self, file_id: str) -> Path | None:
        """The decoded WAV of an imported file (made again when missing); None for
        an unknown id. The path comes from the project, never from the request."""
        with self._lock:
            folder, stack = self._require_open()
            audio_file = next((f for f in stack.project.audio_files if f.id == file_id), None)
        if audio_file is None:
            return None
        try:
            return ensure_decoded(folder, audio_file, self._decode)
        except AudioImportError as exc:
            raise SessionError(str(exc)) from exc

    def audio_clip_fx_path(self, clip_id: str) -> Path | None:
        """An audio clip's processed file (M8-4), rendered when missing; None when the
        clip is unknown or plays its file as it is. The render runs outside the session
        lock, once per (file, chain) key; clips sharing both share the file."""
        with self._lock:
            folder, stack = self._require_open()
            clip = next((c for c in stack.project.audio_clips if c.id == clip_id), None)
            if clip is None:
                return None
            audio_file = next((f for f in stack.project.audio_files if f.id == clip.file_id), None)
            fx = None if clip.fx is None else clip.fx.model_copy(deep=True)
        if audio_file is None:
            return None
        try:
            spec = clip_processing_spec(fx)
        except FxChainError as exc:
            raise SessionError(f"the clip's FX cannot be used: {exc}") from exc
        if spec is None:
            return None
        dest = folder / AUDIO_FX_DIR / f"{clip_fx_key(audio_file.id, spec)}.wav"
        with _lock_for(f"clipfx:{dest.name}"):
            if not dest.is_file():
                try:
                    src = ensure_decoded(folder, audio_file, self._decode)
                    render_clip_fx(src, dest, spec)
                except (AudioImportError, ProcessError) as exc:
                    raise SessionError(f"cannot render the FX of {audio_file.name}: {exc}") from exc
        return dest

    # ---- recent projects ---------------------------------------------------

    def recent(self) -> list[RecentItem]:
        if self._recent_path is None:
            return []
        return [
            RecentItem(
                **entry.model_dump(),
                exists=project_file(Path(entry.folder)).is_file(),
            )
            for entry in load_recent(self._recent_path)
        ]

    def forget_recent(self, folder: str) -> None:
        if self._recent_path is None:
            return
        with self._lock:
            entries = load_recent(self._recent_path)
            save_recent(self._recent_path, remove_recent(entries, folder))

    # ---- internals ---------------------------------------------------------

    def _require_open(self) -> tuple[Path, CommandStack]:
        if self._folder is None or self._stack is None:
            raise SessionError("no project is open")
        return self._folder, self._stack

    def _timeline_state(self) -> TimelineState:
        folder, stack = self._require_open()
        missing = {
            source.id
            for source in stack.project.sources
            if not self._source_exists(folder, source)
        }
        state = build_timeline(
            stack.project,
            can_undo=stack.can_undo,
            can_redo=stack.can_redo,
            undo_label=stack.undo_label,
            redo_label=stack.redo_label,
            missing_source_ids=missing,
            trim_bounds=self._placed_trim_bounds(folder, stack.project),
        )
        return state.model_copy(update={"save_error": self._save_error})

    def _placed_trim_bounds(
        self, folder: Path, project: Project
    ) -> dict[str, TrimBounds]:
        """Trim bounds of the takes that placements may play, for the timeline's
        lengths. A take whose file cannot be read is left out: the timeline then
        uses its recorded length. Cached in memory and in sidecars, so after the
        first look this is a stat per take."""
        active = {line.id: line.active_take_id for line in project.lines}
        wanted: set[str] = set()
        for placement in project.placements:
            wanted.add(placement.take_override_id or "")
            wanted.add(active.get(placement.line_id) or "")
        wanted.discard("")
        takes = {take.id: take for take in project.takes}
        store = TakeStore(folder)
        found: dict[str, TrimBounds] = {}
        for take_id in sorted(wanted):
            take = takes.get(take_id)
            if take is None:
                continue
            try:
                found[take_id] = trim_bounds_for(
                    store.path(take.raw_file),
                    self._trims,
                    manual_start_ms=take.trim_start_ms,
                    manual_end_ms=take.trim_end_ms,
                )
            except (ProcessError, TakeError):
                continue
        return found

    @staticmethod
    def _line_or_error(project: Project, line_id: str) -> Line:
        for line in project.lines:
            if line.id == line_id:
                return line
        raise SessionError(f"unknown line id {line_id!r}")

    @staticmethod
    def _free_take_id(project: Project, wanted: str | None) -> str:
        take_id = wanted if wanted is not None else new_id()
        if any(take.id == take_id for take in project.takes):
            raise TakeError(f"take id {take_id!r} already exists")
        return take_id

    def _finish_take(
        self,
        line: Line,
        take: Take,
        *,
        reused: bool,
        make_active: bool,
        changed: bool,
    ) -> AddTakeResult:
        if make_active and line.active_take_id != take.id:
            line.active_take_id = take.id
            changed = True
        if changed:
            self._on_change()
        return AddTakeResult(take=build_take_item(take, line, True), reused=reused)

    def _delete_takes(
        self, remove: Callable[[Project], TakeRemoval], *, removed_line: bool
    ) -> TakeDeleteReport:
        with self._lock:
            folder, stack = self._require_open()
            store = TakeStore(folder)
            try:
                removal = remove(stack.project)
            except TakeError as exc:
                raise SessionError(str(exc)) from exc
            # Earlier undo steps may point at what is gone (an active take, a
            # star), so the history starts over.
            stack.clear()
            self._on_change()
            if self._save_error is not None:
                raise SessionError(
                    "could not save the project, so the take files were kept: "
                    f"{self._save_error}"
                )
            sizes = {rel: store.size(rel) or 0 for rel in removal.files}
            failed = store.delete_files(removal.files)
            freed = sum(size for rel, size in sizes.items() if rel not in failed)
            return build_delete_report(
                removal,
                removed_line=removed_line,
                freed_bytes=freed,
                failed_files=failed,
            )

    @staticmethod
    def _execute_unless_no_change(stack: CommandStack, command: Command) -> None:
        try:
            stack.execute(command)
        except NoChange:
            return

    def _presets_or_raise(self) -> dict[str, EmotionPreset]:
        if self._presets is None:
            try:
                _, self._presets, _, _ = load_effective(self._user_presets_path)
            except PresetError as exc:
                raise SessionError(str(exc)) from exc
        return self._presets

    # ---- settings (M7 S5) --------------------------------------------------

    def presets_state(self) -> PresetsState:
        """The emotion presets as Settings shows them; also reloads them."""
        with self._lock:
            try:
                builtin, effective, customized, problem = load_effective(
                    self._user_presets_path
                )
            except PresetError as exc:
                raise SessionError(str(exc)) from exc
            self._presets = effective
            self._avatar_track = None  # preset expressions feed the auto-keys
            path = self._user_presets_path or default_user_presets_path()
            return build_presets_state(
                builtin, effective, customized=customized, path=path, problem=problem
            )

    def save_presets(self, edits: list[PresetEdit]) -> PresetsState:
        """Save edited preset values app-wide. Values equal to the built-ins
        remove the file (nothing customized)."""
        with self._lock:
            path = self._require_user_presets_path()
            try:
                builtin = load_presets_file()
                edited = check_edit(builtin, edits)
            except PresetError as exc:
                raise SessionError(str(exc)) from exc
            try:
                if edited == builtin:
                    delete_user_presets(path)
                else:
                    save_user_presets(path, edited)
            except OSError as exc:
                raise SessionError(f"cannot save the presets: {describe_error(exc)}") from exc
            return self.presets_state()

    def reset_presets(self) -> PresetsState:
        with self._lock:
            path = self._require_user_presets_path()
            try:
                delete_user_presets(path)
            except OSError as exc:
                raise SessionError(f"cannot reset the presets: {describe_error(exc)}") from exc
            return self.presets_state()

    def _require_user_presets_path(self) -> Path:
        if self._user_presets_path is None:
            raise SessionError("editing presets is not available in this app instance")
        return self._user_presets_path

    def export_settings(self) -> ExportSettings | None:
        """The open project's export defaults (None without a project)."""
        with self._lock:
            if self._stack is None:
                return None
            return self._stack.project.export.model_copy(deep=True)

    def _fx_presets_or_raise(self) -> dict[str, FxChain]:
        if self._fx_presets is None:
            try:
                self._fx_presets = load_fx_presets_file()
            except (ValueError, OSError) as exc:
                raise SessionError(f"cannot load the voice presets: {exc}") from exc
        return self._fx_presets

    def _fx_state(self) -> FxState:
        folder, stack = self._require_open()
        state = build_fx_state(
            stack.project,
            self._fx_presets_or_raise(),
            processing=self._fx_processing(folder, stack.project),
            can_undo=stack.can_undo,
            can_redo=stack.can_redo,
            undo_label=stack.undo_label,
            redo_label=stack.redo_label,
        )
        return state.model_copy(update={"save_error": self._save_error})

    def _fx_processing(self, folder: Path, project: Project) -> FxProcessing:
        """How many of the processed files the placed lines play already exist.
        A take whose raw file is gone can never be rendered and is not counted."""
        total = ready = 0
        for job in plan_jobs(folder, project):
            if not job.raw_path.is_file():
                continue
            total += 1
            if job.dest.is_file():
                ready += 1
        error = self._prefetch.error() if self._prefetch is not None else None
        return FxProcessing(total=total, ready=ready, error=error)

    def _schedule_prefetch(self) -> None:
        if self._prefetch is None:
            return
        if self._folder is None or self._stack is None:
            self._prefetch.request([])  # nothing to render yet; this warms the worker
            return
        self._prefetch.request(plan_jobs(self._folder, self._stack.project))

    def _cleanup_fx(self) -> None:
        """Delete processed files nothing wants any more (``run_cleanup`` keeps the
        ones used in the last ten minutes, so undo stays quick). Runs on the
        prefetch thread, at most every ``CLEANUP_EVERY_S`` seconds."""
        now = time.monotonic()
        with self._lock:
            if self._folder is None or self._stack is None:
                return
            if now - self._last_cleanup < CLEANUP_EVERY_S:
                return
            folder, project = self._folder, self._stack.project
            try:
                processing_spec(project.fx_chain)
            except FxChainError:
                return  # an unusable chain wants nothing: delete nothing
            self._last_cleanup = now
            wanted = {job.dest.name for job in plan_jobs(folder, project)}
            art_folder = project.avatar.art_folder
        media = folder / "media"
        run_cleanup(media / FX_DIR_NAME, folder / RAW_DIR, wanted)
        # M7 S4: envelopes of processed takes that are gone, and preview sprites of
        # art that is no longer used (both re-created on demand).
        run_cache_cleanup(
            media / ENVELOPE_DIR_NAME, envelope_keep_names(media / FX_DIR_NAME), ENVELOPE_FILE
        )
        run_cache_cleanup(
            media / PREVIEW_DIR_NAME, _preview_keep_names(art_folder, folder), PREVIEW_FILE
        )

    def _line_bank_state(self) -> LineBankState:
        _, stack = self._require_open()
        state = build_line_bank(
            stack.project,
            self._presets_or_raise(),
            can_undo=stack.can_undo,
            can_redo=stack.can_redo,
            undo_label=stack.undo_label,
            redo_label=stack.redo_label,
        )
        return state.model_copy(update={"save_error": self._save_error})

    def _voice_state(self, folder: Path, project: Project) -> VoiceState:
        profile = project.voice_profiles[0] if project.voice_profiles else None
        exists = False
        info = None
        digest = None
        read_error = None
        if profile is not None and profile.reference_clips:
            clip = folder / profile.reference_clips[0]
            exists = clip.is_file()
            if exists:
                try:
                    info = self._audio_info(clip)
                    digest = self._hashes.digest(clip)
                except (VoiceProfileError, OSError) as exc:
                    info = None
                    read_error = str(exc)
        return build_voice_state(
            profile, exists=exists, info=info, read_error=read_error, digest=digest
        )

    def _summary(self) -> ProjectSummary:
        folder, stack = self._require_open()
        summary = summarize(str(folder), stack.project)
        avatar = build_avatar_state(stack.project.avatar.art_folder, folder)
        return summary.model_copy(
            update={
                "avatar_status": avatar_status_text(avatar),
                "save_error": self._save_error,
                "problem_count": len(check_references(stack.project))
                + len(check_voice_references(stack.project)),
            }
        )

    def _set_open(self, folder: Path, project: Project) -> ProjectSummary:
        self._folder = folder
        self._save_error = None
        self._scan_errors = []
        self._stack = CommandStack(project, on_change=self._on_change)
        self._record_recent(folder, project)
        # Opening must never fail because of footage trouble (for example a
        # missing ffprobe); problems are reported in the footage report.
        try:
            self._scan(folder, self._stack)
        except (FootageError, SessionError) as exc:
            self._scan_errors = [str(exc)]
        # Footage found on open is not an edit the user should be able to undo.
        self._stack.clear()
        self._schedule_prefetch()
        return self._summary()

    def _on_change(self, *_args: object) -> None:
        """Save right after every change (debounce comes later with M2)."""
        if self._folder is None or self._stack is None:
            return
        try:
            save_project(self._folder, self._stack.project)
        except (ProjectError, OSError) as exc:
            self._save_error = describe_error(exc)
        else:
            self._save_error = None
        self._schedule_prefetch()

    def _scan(self, folder: Path, stack: CommandStack) -> int:
        result = scan_footage(folder, list(stack.project.sources), probe=self._probe)
        self._scan_errors = [f"{rel}: {message}" for rel, message in result.errors]
        if not result.new_sources:
            return 0
        try:
            with stack.group("Add footage"):
                for source in result.new_sources:
                    stack.execute(AddSource(source))
        except CommandError as exc:
            raise SessionError(str(exc)) from exc
        return len(result.new_sources)

    def _report(self, folder: Path, project: Project, added: int) -> FootageReport:
        return FootageReport(
            items=[
                describe_source(source, self._source_exists(folder, source))
                for source in project.sources
            ],
            added=added,
            errors=list(self._scan_errors),
        )

    @staticmethod
    def _source_exists(folder: Path, source: Source) -> bool:
        path = Path(source.path) if source.external else folder / source.path
        return path.is_file()

    def _record_recent(self, folder: Path, project: Project) -> None:
        if self._recent_path is None:
            return
        opened_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            entries = load_recent(self._recent_path)
            save_recent(
                self._recent_path,
                add_recent(entries, project.name, str(folder), opened_at),
            )
        except OSError:
            # A failure to write the recent list must never block opening.
            return

    def _probe_bookend(self, raw_path: str) -> Source:
        data = self._probe(Path(raw_path))
        # The placeholder relative path is replaced by external_source.
        return external_source(parse_probe(data, "bookend.mkv"), raw_path)
