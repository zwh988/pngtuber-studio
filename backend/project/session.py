"""The one project the app currently has open (M1-6).

``clean_folder_name`` is pure. ``Session`` does file I/O through ``store`` and
runs ffprobe (injectable) for footage and template bookend clips. Every
change made through the command stack is saved straight away (``on_change``).
Pass ``recent_path`` to record opened projects; ``None`` records nothing.
"""

import re
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from backend.edl.anchoring import check_references, check_voice_references
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
from backend.project.schema import Line, Project, Source, Take, new_id
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
    apply_template,
    external_source,
    load_template_file,
)
from backend.project.timeline import EditResult, TimelineState, build_timeline
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
from backend.voice.takes import (
    AddTakeResult,
    NewTake,
    StorageReport,
    TakeDeleteReport,
    TakeError,
    TakeItem,
    TakeRemoval,
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

Probe = Callable[[Path], dict[str, Any]]

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


class Session:
    def __init__(
        self,
        *,
        template_path: Path | None = None,
        probe: Probe | None = None,
        recent_path: Path | None = None,
        audio_info: AudioInfoFn | None = None,
        presets: dict[str, EmotionPreset] | None = None,
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
        # Loaded from templates/emotion_presets.json on first use when not given.
        self._presets: dict[str, EmotionPreset] | None = presets
        self._folder: Path | None = None
        self._stack: CommandStack | None = None
        self._save_error: str | None = None
        self._scan_errors: list[str] = []

    # ---- project lifecycle -------------------------------------------------

    def current(self) -> ProjectSummary | None:
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            return self._summary()

    def new_project(self, parent: str, name: str) -> ProjectSummary:
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

        template = load_template_file(self._template_path)
        intro = self._probe_bookend(template.intro.path) if template.intro else None
        outro = self._probe_bookend(template.outro.path) if template.outro else None
        project = apply_template(
            template, clean, intro_source=intro, outro_source=outro
        )

        with self._lock:
            folder.mkdir(exist_ok=True)
            create_project(folder, project)
            return self._set_open(folder, project)

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
                raise SessionError(f"the voice reference is not ready: {detail}")
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

    def storage(self) -> StorageReport:
        """Disk use per line and take, plus files no take points at."""
        with self._lock:
            folder, stack = self._require_open()
            store = TakeStore(folder)
            sizes = {
                take.raw_file: store.size(take.raw_file) for take in stack.project.takes
            }
            return build_storage_report(
                stack.project, sizes, store.unreferenced(set(sizes))
            )

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
        )
        return state.model_copy(update={"save_error": self._save_error})

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
                self._presets = load_presets_file()
            except PresetError as exc:
                raise SessionError(str(exc)) from exc
        return self._presets

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
        return summary.model_copy(
            update={
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
        return self._summary()

    def _on_change(self, *_args: object) -> None:
        """Save right after every change (debounce comes later with M2)."""
        if self._folder is None or self._stack is None:
            return
        try:
            save_project(self._folder, self._stack.project)
        except (ProjectError, OSError) as exc:
            self._save_error = str(exc)
        else:
            self._save_error = None

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
