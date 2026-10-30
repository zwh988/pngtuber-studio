"""Processed take keys (M4-1): stability, sensitivity, float noise, canonical form."""

import math
import re

import pytest

from backend.voice.keys import canonical_json, fx_version, processed_key, processed_name

RAW = "b" * 64
SPEC = {
    "version": 1,
    "trim": {"threshold_db": -45.0, "frame_ms": 10},
    "stages": [{"plugin": "low_shelf", "gain_db": 3.0}],
    "loudness": {"target_lufs": -16.0},
}


def key(**over: object) -> str:
    args: dict = {"raw_key": RAW, "stretch": 1.0, "spec": SPEC}
    args.update(over)
    return processed_key(**args)


def test_key_is_64_lowercase_hex_and_stable() -> None:
    k = key()
    assert re.fullmatch(r"[0-9a-f]{64}", k)
    assert k == key()


def test_each_input_changes_the_key() -> None:
    base = key()
    assert key(raw_key="c" * 64) != base
    assert key(stretch=1.083) != base
    changed = {**SPEC, "stages": [{"plugin": "low_shelf", "gain_db": 3.5}]}
    assert key(spec=changed) != base
    assert key(spec={**SPEC, "version": 2}) != base


def test_float_noise_and_int_float_spelling_do_not_matter() -> None:
    a = {"x": 0.1 + 0.2, "n": 3}
    b = {"x": 0.3, "n": 3.0}
    assert key(spec=a) == key(spec=b)
    assert key(stretch=1.0) == key(stretch=1.00001)
    assert key(spec={"x": -0.0}) == key(spec={"x": 0.0})


def test_dict_order_does_not_matter_but_list_order_does() -> None:
    a = {"p": 1, "q": 2}
    b = {"q": 2, "p": 1}
    assert key(spec=a) == key(spec=b)
    assert key(spec={"s": [1, 2]}) != key(spec={"s": [2, 1]})


def test_a_stretch_of_one_is_a_real_value_not_a_missing_one() -> None:
    assert key(stretch=1.0) != key(stretch=1.25)


def test_bad_arguments() -> None:
    with pytest.raises(ValueError):
        key(raw_key="")
    for bad in (0, -1.0, math.nan):
        with pytest.raises(ValueError):
            key(stretch=bad)
    with pytest.raises(ValueError):
        key(spec={"x": math.nan})
    with pytest.raises(TypeError):
        key(spec={"x": object()})
    with pytest.raises(TypeError):
        key(spec={1: "a"})


def test_canonical_json_is_compact_sorted_and_rounded() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "x", 2.5]}) == (
        '{"a":[true,null,"x","2.5000"],"b":"1.0000"}'
    )
    assert canonical_json({"t": (1, 2)}) == '{"t":["1.0000","2.0000"]}'


def test_bools_are_not_numbers() -> None:
    assert canonical_json({"on": True}) != canonical_json({"on": 1})


def test_processed_name_uses_the_first_16_chars() -> None:
    assert processed_name("0123456789abcdef" + "0" * 48) == "0123456789abcdef.wav"
    with pytest.raises(ValueError):
        processed_name("abc")


def test_fx_version_is_short_and_follows_the_spec() -> None:
    v = fx_version(SPEC)
    assert re.fullmatch(r"[0-9a-f]{8}", v)
    assert v == fx_version(dict(reversed(list(SPEC.items()))))
    assert v != fx_version({**SPEC, "version": 2})
