"""Voice FX presets (M4-2): parsing, validation, the shipped file, file errors."""

import copy
import json
from pathlib import Path

import pytest

from backend.audio.chainspec import build_stages, validate_chain
from backend.audio.fxpresets import (
    DEFAULT_PRESET,
    FxPresetError,
    default_fx_presets_path,
    load_fx_presets_file,
    parse_fx_presets,
)
from backend.project.schema import FxChain

CLEAN = {
    "eq_bass_db": 0.0,
    "eq_mid_db": 0.0,
    "eq_treble_db": 0.0,
    "compressor": {
        "enabled": False,
        "threshold_db": -18.0,
        "ratio": 3.0,
        "attack_ms": 10.0,
        "release_ms": 100.0,
    },
    "effects": [],
    "loudness_target_lufs": -16.0,
}


def doc(**presets: dict) -> dict:
    return {"presets": {"Clean": copy.deepcopy(CLEAN), **presets}}


def test_shipped_file_loads_with_the_four_presets() -> None:
    presets = load_fx_presets_file()
    assert list(presets) == ["Clean", "Warm", "Radio", "Podcast"]
    assert default_fx_presets_path().name == "fx_presets.json"


def test_shipped_presets_are_usable() -> None:
    for chain in load_fx_presets_file().values():
        validate_chain(chain)


def test_clean_is_the_neutral_chain() -> None:
    clean = load_fx_presets_file()[DEFAULT_PRESET]
    assert clean == FxChain()
    assert build_stages(clean) == []


def test_other_shipped_presets_change_the_sound() -> None:
    presets = load_fx_presets_file()
    for name in ("Warm", "Radio", "Podcast"):
        assert build_stages(presets[name]) != []


def test_file_order_is_kept() -> None:
    data = doc(Zeta=copy.deepcopy(CLEAN), Alpha=copy.deepcopy(CLEAN))
    assert list(parse_fx_presets(data)) == ["Clean", "Zeta", "Alpha"]


def test_missing_fields_use_chain_defaults() -> None:
    chain = parse_fx_presets(doc(Bassy={"eq_bass_db": 4.0}))["Bassy"]
    assert chain.eq_bass_db == 4.0
    assert chain.loudness_target_lufs == -16.0


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"presets": []},
        {"presets": {}},  # no Clean
        {"presets": {"Warm": CLEAN}},  # no Clean
        {"presets": {"Clean": CLEAN}, "extra": 1},
        {"presets": {"": CLEAN}},
        {"presets": {" Clean": CLEAN}},
        {"presets": {"Clean": "nope"}},
    ],
)
def test_malformed_files_are_refused(data: object) -> None:
    with pytest.raises(FxPresetError):
        parse_fx_presets(data)


def test_unknown_key_in_a_preset_is_refused() -> None:
    bad = copy.deepcopy(CLEAN)
    bad["eq_bas_db"] = 3.0
    with pytest.raises(FxPresetError):
        parse_fx_presets(doc(Typo=bad))


def test_unusable_values_name_the_preset() -> None:
    bad = copy.deepcopy(CLEAN)
    bad["eq_mid_db"] = 30.0
    with pytest.raises(FxPresetError) as info:
        parse_fx_presets(doc(Loud=bad))
    assert "Loud" in str(info.value)


def test_unknown_effect_is_refused() -> None:
    bad = copy.deepcopy(CLEAN)
    bad["effects"] = [{"type": "reverb", "params": {}}]
    with pytest.raises(FxPresetError):
        parse_fx_presets(doc(Echo=bad))


def test_effect_presets_work() -> None:
    body = copy.deepcopy(CLEAN)
    body["effects"] = [{"type": "pitch_shift", "params": {"semitones": -3}}]
    chain = parse_fx_presets(doc(Deep=body))["Deep"]
    assert build_stages(chain)[-1] == {"plugin": "pitch_shift", "semitones": -3.0}


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FxPresetError):
        load_fx_presets_file(tmp_path / "nope.json")


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "fx.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FxPresetError):
        load_fx_presets_file(path)


def test_a_custom_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "fx.json"
    path.write_text(json.dumps(doc()), encoding="utf-8")
    assert list(load_fx_presets_file(path)) == ["Clean"]
