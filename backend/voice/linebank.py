"""The line bank as the UI sees it (M3-4). Pure: reads a Project, changes nothing."""

from collections import Counter

from pydantic import BaseModel, Field

from backend.project.schema import Line, Project
from backend.voice.presets import EmotionPreset, PresetError, resolve_params


class LineItem(BaseModel):
    id: str
    text: str
    emotion: str
    # False when the line's emotion is not in the presets file any more.
    emotion_known: bool
    # The overrides as stored (null means "use the preset").
    exaggeration: float | None
    cfg_weight: float | None
    # What generation would actually use (preset values, then overrides).
    # Null when the emotion is unknown.
    effective_exaggeration: float | None
    effective_cfg_weight: float | None
    allow_overlap: bool
    active_take_id: str | None
    # A line counts as generated when it has an active take.
    generated: bool
    take_count: int
    placement_count: int


class LineBankState(BaseModel):
    lines: list[LineItem] = Field(default_factory=list)
    # Emotion preset names in file order, for the emotion dropdown.
    emotions: list[str] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    undo_label: str | None = None
    redo_label: str | None = None
    save_error: str | None = None


def build_line_item(
    line: Line,
    presets: dict[str, EmotionPreset],
    *,
    take_count: int,
    placement_count: int,
) -> LineItem:
    effective: tuple[float | None, float | None]
    try:
        effective = resolve_params(
            line.emotion, line.exaggeration, line.cfg_weight, presets
        )
    except PresetError:
        effective = (None, None)
    return LineItem(
        id=line.id,
        text=line.text,
        emotion=line.emotion,
        emotion_known=line.emotion in presets,
        exaggeration=line.exaggeration,
        cfg_weight=line.cfg_weight,
        effective_exaggeration=effective[0],
        effective_cfg_weight=effective[1],
        allow_overlap=line.allow_overlap,
        active_take_id=line.active_take_id,
        generated=line.active_take_id is not None,
        take_count=take_count,
        placement_count=placement_count,
    )


def build_line_bank(
    project: Project,
    presets: dict[str, EmotionPreset],
    *,
    can_undo: bool = False,
    can_redo: bool = False,
    undo_label: str | None = None,
    redo_label: str | None = None,
) -> LineBankState:
    takes = Counter(take.line_id for take in project.takes)
    placed = Counter(p.line_id for p in project.placements)
    return LineBankState(
        lines=[
            build_line_item(
                line,
                presets,
                take_count=takes[line.id],
                placement_count=placed[line.id],
            )
            for line in project.lines
        ],
        emotions=list(presets),
        can_undo=can_undo,
        can_redo=can_redo,
        undo_label=undo_label,
        redo_label=redo_label,
    )
