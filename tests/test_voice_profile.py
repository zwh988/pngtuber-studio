"""Pure voice profile logic (M3-1): reference checks, file names, UI state."""

import pytest

from backend.project.schema import VoiceProfile
from backend.voice.profile import (
    ALLOWED_EXTENSIONS,
    AudioInfo,
    build_voice_state,
    check_reference,
    clean_stem,
    reference_filename,
    reference_relpath,
)

DIGEST = "0123456789abcdef" * 4
PROFILE_ID = "aaaaaaaaaaaa"


def info(ms: int = 8000, rate: int = 24000, channels: int = 1) -> AudioInfo:
    return AudioInfo(duration_ms=ms, sample_rate=rate, channels=channels)


def test_good_clip_has_no_problems_or_warnings() -> None:
    check = check_reference(info())
    assert check.ok
    assert check.problems == ()
    assert check.warnings == ()


@pytest.mark.parametrize("ms", [0, -5])
def test_empty_clip_is_a_problem(ms: int) -> None:
    check = check_reference(info(ms=ms))
    assert not check.ok
    assert "empty" in check.problems[0]


def test_under_one_second_is_a_problem() -> None:
    check = check_reference(info(ms=999))
    assert not check.ok
    assert "at least" in check.problems[0]


def test_exactly_one_second_is_allowed_with_a_short_warning() -> None:
    check = check_reference(info(ms=1000))
    assert check.ok
    assert len(check.warnings) == 1
    assert "short" in check.warnings[0]


def test_five_seconds_is_not_short() -> None:
    assert check_reference(info(ms=5000)).warnings == ()
    assert len(check_reference(info(ms=4999)).warnings) == 1


def test_thirty_seconds_is_not_long() -> None:
    assert check_reference(info(ms=30000)).warnings == ()
    warnings = check_reference(info(ms=30001)).warnings
    assert len(warnings) == 1
    assert "long" in warnings[0]


def test_low_sample_rate_warns() -> None:
    check = check_reference(info(rate=8000))
    assert check.ok
    assert any("sample rate" in w for w in check.warnings)


@pytest.mark.parametrize(("rate", "channels"), [(0, 1), (24000, 0)])
def test_invalid_format_is_a_problem(rate: int, channels: int) -> None:
    assert not check_reference(info(rate=rate, channels=channels)).ok


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my voice", "my voice"),
        ("  .weird..  ", "weird"),
        ("a/b\\c:d", "a_b_c_d"),
        ("日本語", "reference"),
        ("", "reference"),
        ("x" * 100, "x" * 40),
    ],
)
def test_clean_stem(raw: str, expected: str) -> None:
    assert clean_stem(raw) == expected


def test_reference_filename_uses_stem_hash_and_lowercase_extension() -> None:
    assert reference_filename("My Voice.WAV", DIGEST) == "My Voice-01234567.wav"


def test_reference_filename_same_inputs_same_name() -> None:
    assert reference_filename("a.wav", DIGEST) == reference_filename("a.wav", DIGEST)


def test_reference_filename_different_content_different_name() -> None:
    other = "f" * 64
    assert reference_filename("a.wav", DIGEST) != reference_filename("a.wav", other)


@pytest.mark.parametrize("name", ["voice.aac", "voice", "voice.txt"])
def test_reference_filename_rejects_unsupported_types(name: str) -> None:
    with pytest.raises(ValueError, match="unsupported audio type"):
        reference_filename(name, DIGEST)


@pytest.mark.parametrize("digest", ["", "abc", "ZZZZZZZZZZ", "0123456G"])
def test_reference_filename_rejects_bad_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        reference_filename("a.wav", digest)


def test_every_allowed_extension_is_accepted() -> None:
    for extension in ALLOWED_EXTENSIONS:
        assert reference_filename(f"a{extension}", DIGEST).endswith(extension)


def test_reference_relpath() -> None:
    assert reference_relpath("a-01234567.wav") == "media/voice/a-01234567.wav"


def test_state_without_profile() -> None:
    state = build_voice_state(
        None, exists=False, info=None, read_error=None, digest=None
    )
    assert state.status == "no_profile"
    assert not state.ready


def test_state_without_reference() -> None:
    profile = VoiceProfile(id=PROFILE_ID, name="Default")
    state = build_voice_state(
        profile, exists=False, info=None, read_error=None, digest=None
    )
    assert state.status == "no_reference"
    assert state.profile_id == PROFILE_ID
    assert state.reference_path is None
    assert not state.ready


def make_profile() -> VoiceProfile:
    return VoiceProfile(
        id=PROFILE_ID, name="Default", reference_clips=["media/voice/a-01234567.wav"]
    )


def test_state_file_missing() -> None:
    state = build_voice_state(
        make_profile(), exists=False, info=None, read_error=None, digest=None
    )
    assert state.status == "file_missing"
    assert state.reference_path == "media/voice/a-01234567.wav"
    assert not state.ready


def test_state_unreadable_carries_the_error() -> None:
    state = build_voice_state(
        make_profile(), exists=True, info=None, read_error="boom", digest=None
    )
    assert state.status == "unreadable"
    assert state.problems == ["boom"]


def test_state_invalid_when_too_short() -> None:
    state = build_voice_state(
        make_profile(), exists=True, info=info(ms=200), read_error=None, digest=DIGEST
    )
    assert state.status == "invalid"
    assert not state.ready
    assert state.problems


def test_state_ready_carries_details_and_warnings() -> None:
    state = build_voice_state(
        make_profile(), exists=True, info=info(ms=3000), read_error=None, digest=DIGEST
    )
    assert state.status == "ready"
    assert state.ready
    assert state.duration_ms == 3000
    assert state.sample_rate == 24000
    assert state.hash == DIGEST
    assert state.problems == []
    assert len(state.warnings) == 1
