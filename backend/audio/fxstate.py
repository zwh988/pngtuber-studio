"""What the Voice FX tab needs (M4-2): the chain, the presets, the limits. Pure.

``build_fx_state`` turns the open project plus the preset list into one model the
API returns. It does no file access; the session counts the processed files and
passes the result in as ``processing``.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from backend.audio.chainspec import (
    COMPRESSOR_RANGES,
    EQ_GAIN_LIMIT_DB,
    FxChainError,
    processing_spec,
)
from backend.audio.effects import describe_effects
from backend.audio.gamemix import GAME_AUDIO_MAX_DB, GAME_AUDIO_MIN_DB
from backend.audio.loudness import TARGET_MAX_LUFS, TARGET_MIN_LUFS
from backend.project.schema import FxChain, Project
from backend.voice.keys import fx_version as chain_version


class EffectParamInfo(BaseModel):
    name: str
    label: str
    kind: Literal["float", "int"]
    default: float
    minimum: float
    maximum: float
    unit: str = ""


class EffectInfo(BaseModel):
    type: str
    label: str
    params: list[EffectParamInfo]


class FxPresetItem(BaseModel):
    name: str
    chain: FxChain


class FxLimits(BaseModel):
    """The ranges the backend accepts, so the sliders never offer more."""

    eq_gain_limit_db: float
    # name -> [low, high]; checked only while the compressor is enabled.
    compressor: dict[str, list[float]]
    loudness_min_lufs: float
    loudness_max_lufs: float
    game_audio_min_db: float
    game_audio_max_db: float


class FxProcessing(BaseModel):
    """How many of the (take, stretch) files the placed lines play are rendered."""

    total: int = 0
    ready: int = 0
    # The first render problem since the last change (for example a missing
    # library). While it is set the files will not appear: stop waiting and show it.
    error: str | None = None


class FxState(BaseModel):
    chain: FxChain
    # Short hash of the processing spec; "invalid" when the chain cannot be used.
    fx_version: str
    # Why the chain cannot be used (only when ``fx_version`` is "invalid").
    problem: str | None = None
    game_audio_db: float
    presets: list[FxPresetItem] = Field(default_factory=list)
    effects: list[EffectInfo] = Field(default_factory=list)
    limits: FxLimits
    processing: FxProcessing = Field(default_factory=FxProcessing)
    can_undo: bool = False
    can_redo: bool = False
    undo_label: str | None = None
    redo_label: str | None = None
    # Set by the session when the last automatic save failed.
    save_error: str | None = None


def build_limits() -> FxLimits:
    return FxLimits(
        eq_gain_limit_db=EQ_GAIN_LIMIT_DB,
        compressor={
            name: [low, high] for name, (low, high) in COMPRESSOR_RANGES.items()
        },
        loudness_min_lufs=TARGET_MIN_LUFS,
        loudness_max_lufs=TARGET_MAX_LUFS,
        game_audio_min_db=GAME_AUDIO_MIN_DB,
        game_audio_max_db=GAME_AUDIO_MAX_DB,
    )


def build_effect_infos() -> list[EffectInfo]:
    return [
        EffectInfo(
            type=effect["type"],
            label=effect["label"],
            params=[
                EffectParamInfo(
                    name=param["name"],
                    label=param["label"],
                    kind=param["kind"],
                    default=param["default"],
                    minimum=param["min"],
                    maximum=param["max"],
                    unit=param["unit"],
                )
                for param in effect["params"]
            ],
        )
        for effect in describe_effects()
    ]


def build_fx_state(
    project: Project,
    presets: Mapping[str, FxChain],
    *,
    processing: FxProcessing,
    can_undo: bool = False,
    can_redo: bool = False,
    undo_label: str | None = None,
    redo_label: str | None = None,
) -> FxState:
    problem: str | None = None
    try:
        version = chain_version(processing_spec(project.fx_chain))
    except FxChainError as exc:
        version = "invalid"
        problem = str(exc)
    return FxState(
        chain=project.fx_chain,
        fx_version=version,
        problem=problem,
        game_audio_db=project.game_audio_db,
        presets=[
            FxPresetItem(name=name, chain=chain) for name, chain in presets.items()
        ],
        effects=build_effect_infos(),
        limits=build_limits(),
        processing=processing,
        can_undo=can_undo,
        can_redo=can_redo,
        undo_label=undo_label,
        redo_label=redo_label,
    )
