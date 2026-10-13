import json

import pytest

from backend.voice.presets import (
    PresetError,
    default_presets_path,
    load_presets_file,
    parse_presets,
    resolve_params,
)


def good() -> dict:
    return {
        "presets": {
            "neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"},
            "excited": {"exaggeration": 0.75, "cfg_weight": 0.35, "expression": "excited"},
        }
    }


def test_parse_keeps_file_order_and_values():
    presets = parse_presets(good())
    assert list(presets) == ["neutral", "excited"]
    assert presets["excited"].exaggeration == 0.75
    assert presets["excited"].cfg_weight == 0.35
    assert presets["excited"].expression == "excited"
    assert presets["excited"].name == "excited"


def test_neutral_is_required():
    data = good()
    del data["presets"]["neutral"]
    with pytest.raises(PresetError, match="neutral"):
        parse_presets(data)


def test_not_an_object():
    with pytest.raises(PresetError):
        parse_presets([])
    with pytest.raises(PresetError):
        parse_presets({"presets": []})


def test_unknown_top_level_key():
    data = good()
    data["extra"] = 1
    with pytest.raises(PresetError, match="unknown keys"):
        parse_presets(data)


def test_unknown_and_missing_preset_keys():
    data = good()
    data["presets"]["excited"]["speed"] = 1.0
    with pytest.raises(PresetError, match="unknown keys"):
        parse_presets(data)
    data = good()
    del data["presets"]["excited"]["cfg_weight"]
    with pytest.raises(PresetError, match="missing"):
        parse_presets(data)


def test_out_of_range_and_wrong_types():
    for field, value in [
        ("exaggeration", 2.5),
        ("exaggeration", -0.1),
        ("cfg_weight", 1.5),
        ("cfg_weight", "0.5"),
        ("exaggeration", True),
        ("exaggeration", float("nan")),
    ]:
        data = good()
        data["presets"]["excited"][field] = value
        with pytest.raises(PresetError):
            parse_presets(data)


def test_bad_expression_and_name():
    data = good()
    data["presets"]["excited"]["expression"] = "  "
    with pytest.raises(PresetError, match="expression"):
        parse_presets(data)
    data = good()
    data["presets"][" padded"] = data["presets"]["excited"]
    with pytest.raises(PresetError, match="name"):
        parse_presets(data)


def test_resolve_uses_preset_when_no_overrides():
    presets = parse_presets(good())
    assert resolve_params("excited", None, None, presets) == (0.75, 0.35)


def test_resolve_applies_each_override_independently():
    presets = parse_presets(good())
    assert resolve_params("excited", 1.0, None, presets) == (1.0, 0.35)
    assert resolve_params("excited", None, 0.2, presets) == (0.75, 0.2)
    assert resolve_params("neutral", 0.0, 0.0, presets) == (0.0, 0.0)


def test_resolve_unknown_emotion_and_bad_override():
    presets = parse_presets(good())
    with pytest.raises(PresetError, match="unknown emotion 'angry'"):
        resolve_params("angry", None, None, presets)
    with pytest.raises(PresetError):
        resolve_params("neutral", 3.0, None, presets)
    with pytest.raises(PresetError):
        resolve_params("neutral", None, -0.5, presets)


def test_shipped_file_matches_spec_table():
    presets = load_presets_file()
    assert default_presets_path().is_file()
    assert {name: (p.exaggeration, p.cfg_weight, p.expression) for name, p in presets.items()} == {
        "neutral": (0.50, 0.50, "neutral"),
        "excited": (0.75, 0.35, "excited"),
        "confident": (0.55, 0.50, "smug"),
        "nervous": (0.65, 0.40, "worried"),
        "disappointed": (0.40, 0.55, "sad"),
    }


def test_load_file_errors(tmp_path):
    with pytest.raises(PresetError, match="cannot read"):
        load_presets_file(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PresetError, match="not valid JSON"):
        load_presets_file(bad)
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(good()), encoding="utf-8")
    assert "neutral" in load_presets_file(ok)
