import pytest

from backend.voice.keys import (
    SEED_MODULUS,
    base_seed,
    next_unused_seed,
    normalize_text,
    raw_key,
)


def kwargs(**changes) -> dict:
    base = {
        "text": "Nice break.",
        "voice_profile_id": "aaaaaaaaaaaa",
        "reference_hash": "ref-hash-1",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "seed": 1234,
        "model_version": "chatterbox-0.1.7",
    }
    base.update(changes)
    return base


def test_normalize_text():
    assert normalize_text("  Hello \n  world\t!  ") == "Hello world !"
    assert normalize_text("   ") == ""


def test_key_is_stable_64_hex():
    key = raw_key(**kwargs())
    assert key == raw_key(**kwargs())
    assert len(key) == 64
    assert key == key.lower()
    int(key, 16)


def test_every_input_changes_the_key():
    original = raw_key(**kwargs())
    changes = [
        {"text": "Nice break!"},
        {"voice_profile_id": "bbbbbbbbbbbb"},
        {"reference_hash": "ref-hash-2"},
        {"exaggeration": 0.6},
        {"cfg_weight": 0.4},
        {"seed": 1235},
        {"model_version": "chatterbox-0.1.8"},
    ]
    keys = {raw_key(**kwargs(**change)) for change in changes}
    assert original not in keys
    assert len(keys) == len(changes)


def test_whitespace_only_edits_keep_the_key():
    assert raw_key(**kwargs(text="Nice   break.\n")) == raw_key(**kwargs(text=" Nice break. "))


def test_float_noise_and_negative_zero():
    assert raw_key(**kwargs(exaggeration=0.1 + 0.2)) == raw_key(**kwargs(exaggeration=0.3))
    assert raw_key(**kwargs(exaggeration=-0.0)) == raw_key(**kwargs(exaggeration=0.0))
    assert raw_key(**kwargs(exaggeration=0.5)) == raw_key(**kwargs(exaggeration=0.50004))
    assert raw_key(**kwargs(exaggeration=0.5)) != raw_key(**kwargs(exaggeration=0.5001))


def test_invalid_inputs():
    with pytest.raises(ValueError):
        raw_key(**kwargs(text="  \n "))
    with pytest.raises(ValueError):
        raw_key(**kwargs(voice_profile_id=""))
    with pytest.raises(ValueError):
        raw_key(**kwargs(reference_hash=""))
    with pytest.raises(ValueError):
        raw_key(**kwargs(model_version=""))
    with pytest.raises(ValueError):
        raw_key(**kwargs(exaggeration=float("nan")))
    with pytest.raises(ValueError):
        raw_key(**kwargs(cfg_weight=float("inf")))


def test_base_seed_is_deterministic_and_in_range():
    seed = base_seed(42, "abcdef012345")
    assert seed == base_seed(42, "abcdef012345")
    assert 0 <= seed < SEED_MODULUS
    assert seed != base_seed(43, "abcdef012345")
    assert seed != base_seed(42, "abcdef012346")


def test_next_unused_seed_first_use_is_the_base():
    assert next_unused_seed(100, lambda s: raw_key(**kwargs(seed=s)), []) == 100


def test_next_unused_seed_skips_used_seeds():
    def key_for(seed: int) -> str:
        return raw_key(**kwargs(seed=seed))

    used = {key_for(100), key_for(101), key_for(103)}
    assert next_unused_seed(100, key_for, used) == 102
    used.add(key_for(102))
    assert next_unused_seed(100, key_for, used) == 104


def test_next_unused_seed_ignores_keys_for_other_text():
    other = raw_key(**kwargs(text="Something else.", seed=100))
    assert next_unused_seed(100, lambda s: raw_key(**kwargs(seed=s)), [other]) == 100


def test_next_unused_seed_wraps_around_the_modulus():
    def key_for(seed: int) -> str:
        return raw_key(**kwargs(seed=seed))

    base = SEED_MODULUS - 1
    assert next_unused_seed(base, key_for, [key_for(base)]) == 0


def test_next_unused_seed_rejects_a_key_function_that_ignores_the_seed():
    with pytest.raises(ValueError):
        next_unused_seed(5, lambda s: "same", ["same"])
