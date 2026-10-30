"""Voice chain to processing spec (M4-1): stages, skipped no-ops, validation, key effect."""

import json
import math

import pytest

from backend.audio.chainspec import (
    EQ_GAIN_LIMIT_DB,
    PROCESSING_VERSION,
    FxChainError,
    build_stages,
    processing_spec,
    validate_chain,
)
from backend.project.schema import CompressorSettings, EffectSpec, FxChain
from backend.voice.keys import fx_version, processed_key

RAW = "a" * 64


def key_for(chain: FxChain, stretch: float = 1.0) -> str:
    return processed_key(raw_key=RAW, stretch=stretch, spec=processing_spec(chain))


def test_default_chain_has_no_stages() -> None:
    assert build_stages(FxChain()) == []


def test_spec_shape() -> None:
    spec = processing_spec(FxChain())
    assert spec["version"] == PROCESSING_VERSION
    assert spec["stages"] == []
    assert spec["trim"]["threshold_db"] == -45.0
    assert spec["loudness"]["target_lufs"] == -16.0
    json.dumps(spec)  # plain data


def test_eq_bands_come_first_in_bass_mid_treble_order() -> None:
    stages = build_stages(FxChain(eq_bass_db=3.0, eq_mid_db=-2.0, eq_treble_db=1.5))
    assert [s["plugin"] for s in stages] == ["low_shelf", "peak", "high_shelf"]
    assert [s["gain_db"] for s in stages] == [3.0, -2.0, 1.5]
    assert stages[0]["cutoff_frequency_hz"] == 120.0
    assert all("q" in s for s in stages)


def test_bands_at_zero_are_left_out() -> None:
    stages = build_stages(FxChain(eq_mid_db=2.0, eq_bass_db=0.005))
    assert [s["plugin"] for s in stages] == ["peak"]


def test_compressor_stage_only_when_enabled() -> None:
    off = FxChain(compressor=CompressorSettings(enabled=False, threshold_db=-30.0))
    assert build_stages(off) == []
    on = FxChain(compressor=CompressorSettings(enabled=True, threshold_db=-20.0, ratio=2.5))
    (stage,) = build_stages(on)
    assert stage == {
        "plugin": "compressor",
        "threshold_db": -20.0,
        "ratio": 2.5,
        "attack_ms": 10.0,
        "release_ms": 100.0,
    }


def test_effects_follow_the_compressor_in_list_order() -> None:
    chain = FxChain(
        compressor=CompressorSettings(enabled=True),
        effects=[
            EffectSpec(type="chorus", params={"mix": 0.3}),
            EffectSpec(type="pitch_shift", params={"semitones": -2}),
        ],
    )
    assert [s["plugin"] for s in build_stages(chain)] == ["compressor", "chorus", "pitch_shift"]


def test_effects_that_do_nothing_are_dropped() -> None:
    chain = FxChain(
        effects=[
            EffectSpec(type="pitch_shift", params={"semitones": 0}),
            EffectSpec(type="chorus", params={"mix": 0}),
        ]
    )
    assert build_stages(chain) == []


def test_unused_controls_do_not_change_the_key() -> None:
    base = key_for(FxChain())
    assert key_for(FxChain(compressor=CompressorSettings(enabled=False, ratio=8.0))) == base
    assert key_for(FxChain(eq_bass_db=0.0)) == base
    assert key_for(FxChain(effects=[EffectSpec(type="pitch_shift", params={})])) == base


def test_used_controls_do_change_the_key() -> None:
    base = key_for(FxChain())
    assert key_for(FxChain(eq_treble_db=1.0)) != base
    assert key_for(FxChain(loudness_target_lufs=-14.0)) != base
    assert key_for(FxChain(compressor=CompressorSettings(enabled=True))) != base
    assert key_for(FxChain(effects=[EffectSpec(type="chorus", params={})])) != base
    assert key_for(FxChain(), stretch=1.05) != base


def test_fx_version_follows_the_spec() -> None:
    a = fx_version(processing_spec(FxChain()))
    assert a == fx_version(processing_spec(FxChain(compressor=CompressorSettings(ratio=9.0))))
    assert a != fx_version(processing_spec(FxChain(eq_bass_db=2.0)))
    assert len(a) == 8


@pytest.mark.parametrize("field", ["eq_bass_db", "eq_mid_db", "eq_treble_db"])
def test_eq_gain_limit(field: str) -> None:
    validate_chain(FxChain(**{field: EQ_GAIN_LIMIT_DB}))
    validate_chain(FxChain(**{field: -EQ_GAIN_LIMIT_DB}))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(**{field: EQ_GAIN_LIMIT_DB + 0.5}))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(**{field: -EQ_GAIN_LIMIT_DB - 0.5}))


def test_non_finite_gain_is_refused() -> None:
    with pytest.raises(FxChainError):
        validate_chain(FxChain(eq_mid_db=math.nan))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(eq_mid_db=math.inf))


def test_loudness_target_range() -> None:
    validate_chain(FxChain(loudness_target_lufs=-14.0))
    for bad in (-50.0, 0.0, math.nan):
        with pytest.raises(FxChainError):
            validate_chain(FxChain(loudness_target_lufs=bad))


def test_enabled_compressor_values_are_checked() -> None:
    with pytest.raises(FxChainError):
        validate_chain(FxChain(compressor=CompressorSettings(enabled=True, threshold_db=5.0)))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(compressor=CompressorSettings(enabled=True, attack_ms=500.0)))
    # a disabled compressor is not checked: it is not used
    validate_chain(FxChain(compressor=CompressorSettings(enabled=False, threshold_db=5.0)))


def test_bad_effects_become_chain_errors() -> None:
    with pytest.raises(FxChainError):
        validate_chain(FxChain(effects=[EffectSpec(type="reverb")]))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(effects=[EffectSpec(type="pitch_shift", params={"semitones": 40})]))
    with pytest.raises(FxChainError):
        validate_chain(FxChain(effects=[EffectSpec(type="chorus", params={"wet": 1})]))
