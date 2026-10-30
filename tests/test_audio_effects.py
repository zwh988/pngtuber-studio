"""Voice effect registry (M4-1): parameters, defaults, ranges, no-op detection."""

import math

import pytest

from backend.audio import effects
from backend.audio.effects import (
    EffectError,
    ParamDef,
    VoiceEffect,
    describe_effects,
    effect_stage,
    effect_types,
    get_effect,
    normalize_params,
    register,
)


def test_the_m4_effects_are_registered() -> None:
    assert effect_types() == ["pitch_shift", "chorus"]


def test_defaults_are_filled_in_declaration_order() -> None:
    assert normalize_params("chorus", {}) == {
        "rate_hz": 1.0,
        "depth": 0.25,
        "centre_delay_ms": 7.0,
        "feedback": 0.0,
        "mix": 0.5,
    }
    assert list(normalize_params("chorus", {"mix": 0.2, "rate_hz": 2})) == [
        "rate_hz",
        "depth",
        "centre_delay_ms",
        "feedback",
        "mix",
    ]


def test_floats_are_rounded() -> None:
    assert normalize_params("pitch_shift", {"semitones": 2.00004})["semitones"] == 2.0
    assert normalize_params("pitch_shift", {"semitones": 1.23456})["semitones"] == 1.235


def test_unknown_type_and_parameter() -> None:
    with pytest.raises(EffectError):
        get_effect("reverb")
    with pytest.raises(EffectError):
        normalize_params("pitch_shift", {"semitones": 1.0, "wet": 0.5})


@pytest.mark.parametrize("value", [13.0, -12.5, math.nan, math.inf, True, "2", None])
def test_bad_values_are_rejected(value: object) -> None:
    with pytest.raises(EffectError):
        normalize_params("pitch_shift", {"semitones": value})


def test_range_limits_are_inclusive() -> None:
    assert normalize_params("pitch_shift", {"semitones": 12})["semitones"] == 12.0
    assert normalize_params("pitch_shift", {"semitones": -12})["semitones"] == -12.0


def test_stage_has_the_plugin_name_and_parameters() -> None:
    assert effect_stage("pitch_shift", {"semitones": 3}) == {
        "plugin": "pitch_shift",
        "semitones": 3.0,
    }
    stage = effect_stage("chorus", {})
    assert stage is not None and stage["plugin"] == "chorus"


def test_effects_that_do_nothing_give_no_stage() -> None:
    assert effect_stage("pitch_shift", {"semitones": 0}) is None
    assert effect_stage("pitch_shift", {}) is None
    assert effect_stage("chorus", {"mix": 0}) is None


def test_describe_lists_every_parameter_with_its_range() -> None:
    described = {e["type"]: e for e in describe_effects()}
    pitch = described["pitch_shift"]
    assert pitch["label"] == "Pitch shift"
    assert pitch["params"][0]["min"] == -12.0
    assert pitch["params"][0]["max"] == 12.0
    assert [p["name"] for p in described["chorus"]["params"]][-1] == "mix"


def test_duplicate_registration_is_refused_and_new_effects_work() -> None:
    probe = VoiceEffect(
        type="probe_fx",
        label="Probe",
        plugin="probe",
        params=(ParamDef("amount", "Amount", "int", 1, 0, 5),),
    )
    register(probe)
    try:
        assert "probe_fx" in effect_types()
        assert effect_stage("probe_fx", {"amount": 2}) == {"plugin": "probe", "amount": 2}
        with pytest.raises(EffectError):
            normalize_params("probe_fx", {"amount": 1.5})  # int parameter, not whole
        with pytest.raises(EffectError):
            register(probe)
    finally:
        effects.REGISTRY.pop("probe_fx", None)
    assert "probe_fx" not in effect_types()
