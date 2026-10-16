"""Worker protocol: encoding, decoding, validation, plan to command (M3-3)."""

import json

import pytest
from pydantic import ValidationError

from backend.voice.chunking import chunk_seed
from backend.voice.generation import GenerationPlan
from backend.voice.protocol import (
    CancelCommand,
    CancelledEvent,
    DoneEvent,
    ErrorEvent,
    GenerateCommand,
    LoadCommand,
    ProgressEvent,
    ProtocolError,
    ReadyEvent,
    ShutdownCommand,
    UnloadCommand,
    UnloadedEvent,
    WorkerCommand,
    WorkerEvent,
    build_generate_command,
    decode_command,
    decode_event,
    encode_message,
)
from backend.voice.takes import NewTake


def make_generate(**changes: object) -> GenerateCommand:
    data: dict[str, object] = {
        "job_id": "job1",
        "chunks": ("Hello there.",),
        "seeds": (1234,),
        "reference_path": "C:/Projects/Rack 1/media/voice/ref-ab12cd34.wav",
        "output_path": "C:/Temp/job1.wav",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
    }
    data.update(changes)
    return GenerateCommand(**data)


COMMANDS = [
    LoadCommand(),
    LoadCommand(device="cpu"),
    make_generate(),
    make_generate(chunks=("One.", "Two."), seeds=(7, 8)),
    CancelCommand(job_id="job1"),
    UnloadCommand(),
    ShutdownCommand(),
]

EVENTS = [
    ReadyEvent(model_version="chatterbox-tts 0.1.7", sample_rate=24000, device="cuda"),
    ProgressEvent(job_id="job1", chunks_done=1, chunk_count=3),
    DoneEvent(
        job_id="job1",
        output_path="C:/Temp/job1.wav",
        sample_rate=24000,
        duration_ms=5200,
        chunk_count=2,
    ),
    CancelledEvent(job_id="job1"),
    UnloadedEvent(),
    ErrorEvent(message="out of memory", fatal=True),
    ErrorEvent(job_id="job1", message="bad piece"),
]


@pytest.mark.parametrize("command", COMMANDS)
def test_command_round_trip(command: WorkerCommand) -> None:
    assert decode_command(encode_message(command)) == command


@pytest.mark.parametrize("event", EVENTS)
def test_event_round_trip(event: WorkerEvent) -> None:
    assert decode_event(encode_message(event)) == event


def test_encoded_message_is_one_tagged_line() -> None:
    line = encode_message(make_generate())
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line)["type"] == "generate"


def test_newline_inside_text_does_not_split_the_line() -> None:
    command = make_generate(chunks=("first\nsecond",))
    line = encode_message(command)
    assert line.count("\n") == 1
    assert decode_command(line) == command


def test_unicode_text_round_trips() -> None:
    command = make_generate(chunks=("Café — “quoted” ✓",))
    assert decode_command(encode_message(command)) == command


def test_decode_ignores_surrounding_whitespace() -> None:
    assert decode_command("  " + encode_message(UnloadCommand()) + "  ") == (
        UnloadCommand()
    )


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   \n",
        "not json",
        "[1, 2]",
        "42",
        '{"job_id": "x"}',
        '{"type": "nope"}',
        '{"type": "cancel"}',
        '{"type": "unload", "extra": 1}',
    ],
)
def test_decode_command_rejects_bad_lines(line: str) -> None:
    with pytest.raises(ProtocolError):
        decode_command(line)


@pytest.mark.parametrize(
    "line",
    ["", "garbage", '{"type": "ready"}', '{"type": "unloaded", "extra": 1}'],
)
def test_decode_event_rejects_bad_lines(line: str) -> None:
    with pytest.raises(ProtocolError):
        decode_event(line)


def test_an_event_is_not_a_command_and_the_reverse() -> None:
    with pytest.raises(ProtocolError):
        decode_command(encode_message(CancelledEvent(job_id="job1")))
    with pytest.raises(ProtocolError):
        decode_event(encode_message(CancelCommand(job_id="job1")))


def test_protocol_error_message_names_the_problem() -> None:
    with pytest.raises(ProtocolError, match="command"):
        decode_command('{"type": "cancel"}')


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": ""},
        {"chunks": ()},
        {"chunks": ("   ",)},
        {"seeds": (1, 2)},
        {"seeds": (-1,)},
        {"reference_path": ""},
        {"output_path": ""},
        {"exaggeration": -0.1},
        {"exaggeration": float("nan")},
        {"cfg_weight": float("inf")},
    ],
)
def test_generate_command_validation(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_generate(**changes)


def test_messages_are_frozen_and_forbid_extra_fields() -> None:
    command = CancelCommand(job_id="job1")
    with pytest.raises(ValidationError):
        command.job_id = "other"
    with pytest.raises(ValidationError):
        CancelCommand(job_id="job1", surprise=1)


def test_progress_cannot_exceed_its_count() -> None:
    with pytest.raises(ValidationError):
        ProgressEvent(job_id="job1", chunks_done=4, chunk_count=3)


def make_plan(chunks: tuple[str, ...], seed: int = 1000) -> GenerationPlan:
    take = NewTake(
        line_id="a" * 12,
        seed=seed,
        text=" ".join(chunks),
        exaggeration=0.65,
        cfg_weight=0.4,
        voice_profile_id="b" * 12,
        model_version="m1",
        raw_key="c" * 64,
    )
    return GenerationPlan(
        new_take=take,
        chunks=chunks,
        reference_path="C:/Projects/Rack 1/media/voice/ref.wav",
        reroll=False,
    )


def test_build_generate_command_single_chunk_keeps_the_take_seed() -> None:
    command = build_generate_command("job9", make_plan(("Only one.",)), "C:/T/o.wav")
    assert command.job_id == "job9"
    assert command.chunks == ("Only one.",)
    assert command.seeds == (1000,)
    assert command.exaggeration == 0.65
    assert command.cfg_weight == 0.4
    assert command.reference_path == "C:/Projects/Rack 1/media/voice/ref.wav"
    assert command.output_path == "C:/T/o.wav"


def test_build_generate_command_uses_chunk_seeds() -> None:
    command = build_generate_command(
        "job9", make_plan(("One.", "Two.", "Three."), seed=4242), "C:/T/o.wav"
    )
    assert command.chunks == ("One.", "Two.", "Three.")
    assert command.seeds[0] == 4242
    assert command.seeds == tuple(chunk_seed(4242, i) for i in range(3))
    assert decode_command(encode_message(command)) == command
