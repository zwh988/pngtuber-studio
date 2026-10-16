"""WorkerLoop: generate, cancel, join and write, with a recording engine (M3-3)."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.voice.chunking import crossfade_join
from backend.voice.engine import EngineInfo
from backend.voice.protocol import (
    CancelCommand,
    CancelledEvent,
    DoneEvent,
    ErrorEvent,
    GenerateCommand,
    LoadCommand,
    ProgressEvent,
    ReadyEvent,
    ShutdownCommand,
    UnloadCommand,
    UnloadedEvent,
    WorkerEvent,
)
from backend.voice.workerloop import WorkerLoop

RATE = 24000


class RecordingEngine:
    def __init__(
        self,
        *,
        fail_load: bool = False,
        fail_warm_up: bool = False,
        fail_on_call: int | None = None,
        bad_audio: np.ndarray | None = None,
        on_synthesize: Callable[[int], None] | None = None,
    ) -> None:
        self.fail_load = fail_load
        self.fail_warm_up = fail_warm_up
        self.fail_on_call = fail_on_call
        self.bad_audio = bad_audio
        self.on_synthesize = on_synthesize
        self.calls: list[dict[str, object]] = []
        self.returned: list[np.ndarray] = []
        self.load_count = 0
        self.warm_up_count = 0
        self.unload_count = 0

    def load(self, device: str) -> EngineInfo:
        self.load_count += 1
        if self.fail_load:
            raise RuntimeError("no GPU")
        return EngineInfo(model_version="rec-1", sample_rate=RATE)

    def warm_up(self) -> None:
        self.warm_up_count += 1
        if self.fail_warm_up:
            raise RuntimeError("warm-up failed")

    def synthesize(
        self,
        text: str,
        *,
        seed: int,
        reference_path: str,
        exaggeration: float,
        cfg_weight: float,
    ) -> np.ndarray:
        number = len(self.calls)
        self.calls.append(
            {
                "text": text,
                "seed": seed,
                "reference_path": reference_path,
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
            }
        )
        if self.on_synthesize is not None:
            self.on_synthesize(number)
        if self.fail_on_call == number:
            raise RuntimeError("synthesis failed")
        if self.bad_audio is not None:
            return self.bad_audio
        samples = np.full(4800, 0.1 * (number + 1), dtype=np.float32)
        self.returned.append(samples)
        return samples

    def unload(self) -> None:
        self.unload_count += 1


class Harness:
    def __init__(self, engine: RecordingEngine) -> None:
        self.engine = engine
        self.events: list[WorkerEvent] = []
        self.loop = WorkerLoop(engine, self.events.append)

    def load(self) -> None:
        assert self.loop.handle(LoadCommand())
        self.events.clear()


def make_generate(
    folder: Path,
    *,
    job_id: str = "j1",
    chunks: tuple[str, ...] = ("One.",),
    seeds: tuple[int, ...] | None = None,
) -> GenerateCommand:
    return GenerateCommand(
        job_id=job_id,
        chunks=chunks,
        seeds=seeds if seeds is not None else tuple(range(100, 100 + len(chunks))),
        reference_path=str(folder / "ref.wav"),
        output_path=str(folder / "out" / f"{job_id}.wav"),
        exaggeration=0.65,
        cfg_weight=0.4,
    )


@pytest.fixture
def harness() -> Harness:
    return Harness(RecordingEngine())


@pytest.fixture
def loaded(harness: Harness) -> Harness:
    harness.load()
    return harness


def test_load_warms_up_then_reports_ready(harness: Harness) -> None:
    assert harness.loop.handle(LoadCommand(device="cuda"))
    assert harness.engine.warm_up_count == 1
    assert harness.events == [
        ReadyEvent(model_version="rec-1", sample_rate=RATE, device="cuda")
    ]


def test_a_second_load_does_not_load_again(harness: Harness) -> None:
    harness.load()
    harness.loop.handle(LoadCommand())
    assert harness.engine.load_count == 1
    assert isinstance(harness.events[0], ReadyEvent)


def test_a_failed_warm_up_still_gives_ready() -> None:
    harness = Harness(RecordingEngine(fail_warm_up=True))
    assert harness.loop.handle(LoadCommand())
    assert isinstance(harness.events[0], ReadyEvent)


def test_a_failed_load_is_fatal_and_stops_the_worker() -> None:
    harness = Harness(RecordingEngine(fail_load=True))
    assert not harness.loop.handle(LoadCommand())
    assert len(harness.events) == 1
    error = harness.events[0]
    assert isinstance(error, ErrorEvent)
    assert error.fatal
    assert "no GPU" in error.message


def test_generate_before_load_is_an_error(harness: Harness, tmp_path: Path) -> None:
    assert harness.loop.handle(make_generate(tmp_path))
    assert len(harness.events) == 1
    error = harness.events[0]
    assert isinstance(error, ErrorEvent)
    assert error.job_id == "j1"
    assert not error.fatal
    assert harness.engine.calls == []


def test_single_piece_job(loaded: Harness, tmp_path: Path) -> None:
    command = make_generate(tmp_path, chunks=("Hello there.",), seeds=(777,))
    loaded.loop.handle(command)
    assert loaded.engine.calls == [
        {
            "text": "Hello there.",
            "seed": 777,
            "reference_path": command.reference_path,
            "exaggeration": 0.65,
            "cfg_weight": 0.4,
        }
    ]
    assert loaded.events[0] == ProgressEvent(job_id="j1", chunks_done=1, chunk_count=1)
    done = loaded.events[1]
    assert isinstance(done, DoneEvent)
    assert done.sample_rate == RATE
    assert done.chunk_count == 1
    assert done.duration_ms == 200  # 4800 samples at 24 kHz
    samples, rate = soundfile.read(command.output_path, dtype="float32")
    assert rate == RATE
    assert np.array_equal(samples, loaded.engine.returned[0])


def test_multi_piece_job_is_joined_with_the_crossfade(
    loaded: Harness, tmp_path: Path
) -> None:
    command = make_generate(tmp_path, chunks=("A.", "B.", "C."), seeds=(5, 6, 7))
    loaded.loop.handle(command)
    assert [c["seed"] for c in loaded.engine.calls] == [5, 6, 7]
    assert [c["text"] for c in loaded.engine.calls] == ["A.", "B.", "C."]
    progress = [e for e in loaded.events if isinstance(e, ProgressEvent)]
    assert [e.chunks_done for e in progress] == [1, 2, 3]
    done = loaded.events[-1]
    assert isinstance(done, DoneEvent)
    assert done.chunk_count == 3
    expected = crossfade_join(loaded.engine.returned, RATE)
    samples, _ = soundfile.read(command.output_path, dtype="float32")
    assert np.allclose(samples, expected)
    assert done.duration_ms == round(expected.size * 1000 / RATE)


def test_no_temp_file_is_left_behind(loaded: Harness, tmp_path: Path) -> None:
    command = make_generate(tmp_path)
    loaded.loop.handle(command)
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["j1.wav"]


def test_cancel_during_a_piece_stops_after_it(tmp_path: Path) -> None:
    holder: list[Harness] = []

    def cancel_in_flight(number: int) -> None:
        if number == 0:
            holder[0].loop.request_cancel("j1")

    harness = Harness(RecordingEngine(on_synthesize=cancel_in_flight))
    holder.append(harness)
    harness.load()
    command = make_generate(tmp_path, chunks=("A.", "B.", "C."))
    harness.loop.handle(command)
    assert len(harness.engine.calls) == 1
    assert harness.events == [
        ProgressEvent(job_id="j1", chunks_done=1, chunk_count=3),
        CancelledEvent(job_id="j1"),
    ]
    assert not Path(command.output_path).exists()


def test_cancel_of_a_single_piece_job_discards_the_result(
    loaded: Harness, tmp_path: Path
) -> None:
    loaded.loop.request_cancel("j1")  # arrived while the piece was generating
    command = make_generate(tmp_path)
    loaded.loop.handle(command)
    assert loaded.events == [
        ProgressEvent(job_id="j1", chunks_done=1, chunk_count=1),
        CancelledEvent(job_id="j1"),
    ]
    assert not Path(command.output_path).exists()


def test_cancel_command_works_like_request_cancel(
    loaded: Harness, tmp_path: Path
) -> None:
    loaded.loop.handle(CancelCommand(job_id="j1"))
    loaded.loop.handle(make_generate(tmp_path))
    assert isinstance(loaded.events[-1], CancelledEvent)


def test_a_cancel_for_another_job_changes_nothing(
    loaded: Harness, tmp_path: Path
) -> None:
    loaded.loop.request_cancel("someone-else")
    loaded.loop.handle(make_generate(tmp_path))
    assert isinstance(loaded.events[-1], DoneEvent)


def test_next_job_is_unaffected_by_an_earlier_cancel(
    loaded: Harness, tmp_path: Path
) -> None:
    loaded.loop.request_cancel("a")
    loaded.loop.handle(make_generate(tmp_path, job_id="a"))
    loaded.events.clear()
    loaded.loop.handle(make_generate(tmp_path, job_id="b"))
    assert isinstance(loaded.events[-1], DoneEvent)


def test_engine_error_ends_the_job_not_the_worker(tmp_path: Path) -> None:
    harness = Harness(RecordingEngine(fail_on_call=1))
    harness.load()
    command = make_generate(tmp_path, chunks=("A.", "B."))
    assert harness.loop.handle(command)
    assert isinstance(harness.events[0], ProgressEvent)
    error = harness.events[1]
    assert isinstance(error, ErrorEvent)
    assert error.job_id == "j1"
    assert not error.fatal
    assert "synthesis failed" in error.message
    assert not Path(command.output_path).exists()
    harness.engine.fail_on_call = None
    harness.events.clear()
    harness.loop.handle(make_generate(tmp_path, job_id="j2"))
    assert isinstance(harness.events[-1], DoneEvent)


@pytest.mark.parametrize(
    "audio",
    [
        np.zeros(0, dtype=np.float32),
        np.array([0.1, float("nan")], dtype=np.float32),
        np.zeros((2, 10), dtype=np.float32),
    ],
    ids=["empty", "nan", "stereo"],
)
def test_bad_audio_from_the_engine_is_an_error(
    audio: np.ndarray, tmp_path: Path
) -> None:
    harness = Harness(RecordingEngine(bad_audio=audio))
    harness.load()
    command = make_generate(tmp_path)
    harness.loop.handle(command)
    assert len(harness.events) == 1
    assert isinstance(harness.events[0], ErrorEvent)
    assert not Path(command.output_path).exists()


def test_an_unwritable_output_path_is_an_error(loaded: Harness, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    command = GenerateCommand(
        job_id="j1",
        chunks=("One.",),
        seeds=(1,),
        reference_path=str(tmp_path / "ref.wav"),
        output_path=str(blocker / "out.wav"),
        exaggeration=0.5,
        cfg_weight=0.5,
    )
    loaded.loop.handle(command)
    assert isinstance(loaded.events[-1], ErrorEvent)
    assert loaded.events[-1].job_id == "j1"


def test_unload_frees_the_model(loaded: Harness, tmp_path: Path) -> None:
    assert loaded.loop.handle(UnloadCommand())
    assert loaded.engine.unload_count == 1
    assert loaded.events == [UnloadedEvent()]
    loaded.events.clear()
    loaded.loop.handle(make_generate(tmp_path))
    assert isinstance(loaded.events[0], ErrorEvent)
    loaded.loop.handle(LoadCommand())
    assert loaded.engine.load_count == 2


def test_shutdown_releases_the_engine_and_stops(loaded: Harness) -> None:
    assert not loaded.loop.handle(ShutdownCommand())
    assert loaded.engine.unload_count == 1
