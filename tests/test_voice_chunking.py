import numpy as np
import pytest

from backend.voice.chunking import (
    MAX_CHUNK_CHARS,
    chunk_seed,
    crossfade_join,
    plan_chunks,
    split_sentences,
)
from backend.voice.keys import SEED_MODULUS

# --- split_sentences --------------------------------------------------------


def test_split_basic_sentences():
    assert split_sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_split_normalizes_whitespace_and_empty():
    assert split_sentences("  A.\n\n  B.  ") == ["A.", "B."]
    assert split_sentences("   ") == []


def test_split_keeps_closing_quotes_and_ellipsis():
    assert split_sentences('He said "go." Then left… Done.') == [
        'He said "go."',
        "Then left…",
        "Done.",
    ]
    assert split_sentences("Well... maybe. Okay.") == ["Well...", "maybe.", "Okay."]


def test_split_ignores_abbreviations_initials_and_decimals():
    assert split_sentences("Mr. Smith broke 3.5 racks. Nice.") == [
        "Mr. Smith broke 3.5 racks.",
        "Nice.",
    ]
    assert split_sentences("Ask J. Smith about it. Fine.") == ["Ask J. Smith about it.", "Fine."]
    assert split_sentences("Pool, e.g. nine ball. Fun.") == ["Pool, e.g. nine ball.", "Fun."]


def test_split_i_can_end_a_sentence():
    assert split_sentences("So do I. Really.") == ["So do I.", "Really."]


# --- plan_chunks ------------------------------------------------------------


def test_short_text_is_one_normalized_chunk():
    assert plan_chunks("  Nice   break. Great.  ") == ["Nice break. Great."]
    assert plan_chunks("") == []
    assert plan_chunks("   \n") == []


def test_text_exactly_at_the_limit_is_not_split():
    text = "x" * MAX_CHUNK_CHARS
    assert plan_chunks(text) == [text]


def test_long_text_splits_at_sentence_boundaries_and_packs():
    sentences = [f"This is sentence number {i} of the long line." for i in range(1, 11)]
    text = " ".join(sentences)
    chunks = plan_chunks(text, max_chars=100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert " ".join(chunks) == text
    # every chunk starts at a sentence start and ends at a sentence end
    assert all(chunk.startswith("This is sentence") and chunk.endswith(".") for chunk in chunks)


def test_greedy_packing_fills_chunks():
    text = "Aaaa aaaa aaaa. Bbbb bbbb bbbb. Cccc cccc cccc. Dddd dddd dddd."
    assert plan_chunks(text, max_chars=40) == [
        "Aaaa aaaa aaaa. Bbbb bbbb bbbb.",
        "Cccc cccc cccc. Dddd dddd dddd.",
    ]


def test_giant_sentence_splits_at_commas_first():
    text = "alpha beta gamma delta, epsilon zeta eta theta, iota kappa lambda mu nu xi"
    chunks = plan_chunks(text, max_chars=40)
    assert " ".join(chunks) == text
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert chunks[0].endswith(",")


def test_giant_sentence_without_commas_splits_at_spaces():
    text = " ".join(["word"] * 30)
    chunks = plan_chunks(text, max_chars=50)
    assert " ".join(chunks) == text
    assert all(len(chunk) <= 50 for chunk in chunks)


def test_one_giant_word_is_hard_cut():
    text = "z" * 95
    chunks = plan_chunks(text, max_chars=30)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 30 for chunk in chunks)


def test_max_chars_floor():
    with pytest.raises(ValueError):
        plan_chunks("anything", max_chars=5)


# --- chunk_seed -------------------------------------------------------------


def test_chunk_seed():
    assert chunk_seed(1234, 0) == 1234
    assert chunk_seed(1234, 3) == 1237
    assert chunk_seed(SEED_MODULUS - 1, 1) == 0


# --- crossfade_join ---------------------------------------------------------

SR = 1000  # 1 ms = 1 sample keeps the arithmetic obvious


def test_join_empty_and_single():
    assert len(crossfade_join([], SR)) == 0
    single = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    assert np.array_equal(crossfade_join([single], SR), single)


def test_join_length_is_sum_minus_overlaps():
    a = np.ones(500, dtype=np.float32)
    b = np.ones(500, dtype=np.float32)
    c = np.ones(500, dtype=np.float32)
    out = crossfade_join([a, b, c], SR, crossfade_ms=40)
    assert len(out) == 1500 - 2 * 40
    assert out.dtype == np.float32


def test_join_blend_endpoints_and_untouched_parts():
    a = np.full(200, 0.5, dtype=np.float32)
    b = np.full(200, -0.25, dtype=np.float32)
    out = crossfade_join([a, b], SR, crossfade_ms=40)
    assert np.all(out[:160] == 0.5)
    assert np.all(out[-160:] == -0.25)
    assert out[160] == pytest.approx(0.5)  # blend starts fully on the first chunk
    assert out[199] == pytest.approx(-0.25)  # and ends fully on the second


def test_join_is_equal_power():
    a = np.ones(200, dtype=np.float32)
    b = np.ones(200, dtype=np.float32)
    out = crossfade_join([a, b], SR, crossfade_ms=40)
    blend = out[160:200]
    # cos^2 + sin^2 = 1, so uncorrelated power stays flat; for identical signals the
    # amplitude peaks at sqrt(2) in the middle
    assert blend.max() == pytest.approx(2**0.5, abs=0.02)


def test_fade_shrinks_for_short_chunks():
    a = np.ones(10, dtype=np.float32)
    b = np.ones(10, dtype=np.float32)
    out = crossfade_join([a, b], SR, crossfade_ms=40)  # wants 40 samples, may use 5
    assert len(out) == 20 - 5


def test_zero_crossfade_is_plain_concatenation():
    a = np.array([1, 2, 3], dtype=np.float32)
    b = np.array([4, 5], dtype=np.float32)
    assert np.array_equal(crossfade_join([a, b], SR, crossfade_ms=0), np.array([1, 2, 3, 4, 5]))


def test_join_rejects_bad_input():
    with pytest.raises(ValueError):
        crossfade_join([np.zeros((2, 3))], SR)
    with pytest.raises(ValueError):
        crossfade_join([np.zeros(3)], 0)
    with pytest.raises(ValueError):
        crossfade_join([np.zeros(3)], SR, crossfade_ms=-1)


def test_join_does_not_modify_inputs():
    a = np.full(100, 0.5, dtype=np.float32)
    b = np.full(100, 0.25, dtype=np.float32)
    a_copy, b_copy = a.copy(), b.copy()
    crossfade_join([a, b], SR)
    assert np.array_equal(a, a_copy)
    assert np.array_equal(b, b_copy)
