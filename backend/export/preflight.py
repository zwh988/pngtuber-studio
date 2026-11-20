"""Export pre-flight (M6-1). Pure: the caller passes in what needs the disk.

``preflight`` lists what is wrong before an export. ``error`` issues block it (the
export could not be made, or would be wrong in a way the user cannot accept);
``warning`` issues allow it once the user confirms (something will be silent, left
out or drawn with a fallback). Each issue may carry a timeline time so the export
screen can jump there.
"""

from collections.abc import Collection, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from backend.audio.chainspec import FxChainError, validate_chain
from backend.export.clipeffects import get_effect
from backend.project.schema import Project
from backend.project.timeline import TimelineState

Severity = Literal["error", "warning"]

# Reference problems (``check_references``) that make an export impossible; the
# others only mean something will be left out.
BLOCKING_REFERENCE_KINDS = frozenset({"clip_missing_source"})


class PreflightIssue(BaseModel):
    severity: Severity
    kind: str
    message: str
    item_id: str | None = None
    t_ms: int | None = None


class PreflightReport(BaseModel):
    """``GET /api/export/preflight``. ``ok``: no errors (warnings may remain)."""

    ok: bool
    error_count: int
    warning_count: int
    issues: list[PreflightIssue] = Field(default_factory=list)


def _short(text: str, limit: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def preflight(
    project: Project,
    timeline: TimelineState,
    *,
    missing_take_ids: Collection[str] = (),
    art_status: str = "ready",
    art_problem: str | None = None,
    art_warnings: Sequence[str] = (),
    tools_problem: str | None = None,
    missing_audio_file_ids: Collection[str] = (),
) -> PreflightReport:
    """Check a project before export.

    ``timeline`` is ``build_timeline`` of this project (with the sources missing on
    disk marked); ``missing_take_ids`` are takes whose raw file is missing;
    ``art_status`` / ``art_problem`` / ``art_warnings`` come from the avatar state;
    ``tools_problem`` says why ffmpeg or NVENC cannot be used (None when they can);
    ``missing_audio_file_ids`` are imported audio files no longer in ``audio/`` (M8-1).
    """
    issues: list[PreflightIssue] = []

    def add(
        severity: Severity,
        kind: str,
        message: str,
        item_id: str | None = None,
        t_ms: int | None = None,
    ) -> None:
        issues.append(
            PreflightIssue(
                severity=severity, kind=kind, message=message, item_id=item_id, t_ms=t_ms
            )
        )

    # --- tools and settings ---------------------------------------------------------
    if tools_problem is not None:
        add("error", "tools", tools_problem)
    try:
        validate_chain(project.fx_chain)
    except FxChainError as exc:
        add("error", "fx_chain_invalid", f"The voice chain cannot be used: {exc}")

    # --- footage --------------------------------------------------------------------
    if not timeline.clips:
        add("error", "no_clips", "The timeline has no clips.")
    reported_sources: set[str] = set()
    for clip in timeline.clips:
        source = clip.source
        if source is not None and source.file_missing and source.id not in reported_sources:
            reported_sources.add(source.id)
            add(
                "error",
                "source_missing",
                "A footage file used on the timeline is missing (relink it on the project screen).",
                source.id,
                clip.start_ms,
            )
    clips_by_id = {clip.id: clip for clip in project.clips}
    for clip in timeline.clips:
        stored = clips_by_id.get(clip.id)
        if stored is None:
            continue
        for effect in stored.effects:
            if get_effect(effect.type) is None:
                add(
                    "error",
                    "clip_effect_unknown",
                    f"A clip uses the effect {effect.type!r}, which this version cannot export.",
                    clip.id,
                    clip.start_ms,
                )
    if timeline.other_track_clips:
        add(
            "warning",
            "other_tracks",
            f"{_plural(timeline.other_track_clips, 'clip')} on other tracks will not be exported.",
        )
    for problem in timeline.problems:
        severity: Severity = "error" if problem.kind in BLOCKING_REFERENCE_KINDS else "warning"
        add(severity, f"reference_{problem.kind}", problem.message, problem.owner_id)

    # --- voice ----------------------------------------------------------------------
    missing_takes = set(missing_take_ids)
    for placement in timeline.placements:
        label = f'"{_short(placement.line_text)}"' if placement.line_text else "A placed line"
        if placement.orphaned:
            add(
                "warning",
                "orphan_placement",
                f"{label} is orphaned (its footage was cut away) and will be left out.",
                placement.id,
                placement.start_ms,
            )
            continue
        if placement.start_ms is None:
            add(
                "warning",
                "placement_off_timeline",
                f"{label} is not on the timeline and will be left out.",
                placement.id,
            )
            continue
        if placement.take_id is None:
            add(
                "warning",
                "no_take",
                f"{label} has no take yet and will be silent.",
                placement.id,
                placement.start_ms,
            )
            continue
        if placement.take_id in missing_takes:
            add(
                "error",
                "take_file_missing",
                f"The take file of {label} is missing.",
                placement.id,
                placement.start_ms,
            )
            continue
        if placement.overflow_ms > 0 and not placement.allow_overlap:
            add(
                "warning",
                "overflow",
                f"{label} runs {placement.overflow_ms} ms into the next line; both will play mixed.",
                placement.id,
                placement.start_ms,
            )

    # --- audio lanes (M8-1) -----------------------------------------------------------
    missing_audio = set(missing_audio_file_ids)
    names = {f.id: f.name for f in project.audio_files}
    reported_audio: set[str] = set()
    for sound in sorted(project.audio_clips, key=lambda c: (c.timeline_ms, c.id)):
        if sound.file_id in missing_audio and sound.file_id not in reported_audio:
            reported_audio.add(sound.file_id)
            add(
                "error",
                "audio_file_missing",
                f"The audio file {names.get(sound.file_id, '?')} is missing from the "
                "project's audio folder; remove its clips or drop the file again.",
                sound.id,
                sound.timeline_ms,
            )

    # --- avatar ---------------------------------------------------------------------
    orphan_keys = sum(1 for key in timeline.keyframes if key.orphaned)
    if orphan_keys:
        add(
            "warning",
            "orphan_keyframes",
            f"{_plural(orphan_keys, 'avatar key')} orphaned (footage cut away) will be left out.",
        )
    orphan_reactions = sum(1 for r in timeline.reactions if r.orphaned)
    if orphan_reactions:
        add(
            "warning",
            "orphan_reactions",
            f"{_plural(orphan_reactions, 'reaction')} orphaned (footage cut away) will be left out.",
        )
    if art_status != "ready":
        reason = f" ({art_problem})" if art_problem else ""
        add("warning", "no_avatar", f"No usable avatar art{reason}: the video is exported without the avatar.")
    else:
        for warning in art_warnings:
            add("warning", "art_warning", f"Avatar art: {warning}")

    errors = sum(1 for issue in issues if issue.severity == "error")
    return PreflightReport(
        ok=errors == 0,
        error_count=errors,
        warning_count=len(issues) - errors,
        issues=issues,
    )
