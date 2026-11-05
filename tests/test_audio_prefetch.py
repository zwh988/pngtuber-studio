"""Background rendering of processed takes (M4-1, S3d). The render step is replaced
by a fake, so no audio library is needed."""

import threading
from pathlib import Path

from backend.audio.chainspec import processing_spec
from backend.audio.prefetch import Prefetcher, RenderJob, plan_jobs
from backend.audio.render import ProcessError
from backend.project.schema import (
    Anchor,
    FxChain,
    Line,
    Placement,
    Project,
    Take,
)

CLIP = "2" * 12
LINE_A, LINE_B = "3" * 12, "4" * 12
TAKE_A, TAKE_B = "5" * 12, "6" * 12
PLACE_1, PLACE_2, PLACE_3 = "7" * 12, "8" * 12, "b" * 12
VOICE = "9" * 12


def make_take(take_id: str, line_id: str, raw_key: str) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id=VOICE,
        model_version="m",
        raw_key=raw_key,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=1000,
    )


def place(place_id: str, line_id: str, stretch: float = 1.0) -> Placement:
    return Placement(
        id=place_id,
        line_id=line_id,
        anchor=Anchor(clip_id=CLIP, source_ms=1000),
        stretch=stretch,
    )


def make_project(placements: list[Placement]) -> Project:
    return Project(
        name="t",
        lines=[
            Line(id=LINE_A, text="a", active_take_id=TAKE_A),
            Line(id=LINE_B, text="b", active_take_id=TAKE_B),
        ],
        takes=[
            make_take(TAKE_A, LINE_A, "k" * 64),
            make_take(TAKE_B, LINE_B, "n" * 64),
        ],
        placements=placements,
    )


# --- plan_jobs -----------------------------------------------------------------


def test_one_job_per_played_take_and_stretch(tmp_path: Path) -> None:
    project = make_project(
        [place(PLACE_1, LINE_A), place(PLACE_2, LINE_A, 1.08), place(PLACE_3, LINE_B)]
    )
    jobs = plan_jobs(tmp_path, project)
    assert len(jobs) == 3
    assert [job.stretch for job in jobs] == [1.0, 1.08, 1.0]
    assert len({job.dest for job in jobs}) == 3  # one file each
    for job in jobs:
        assert job.raw_path.parent == tmp_path / "media" / "takes_raw"
        assert job.dest.parent == tmp_path / "media" / "takes_fx"
        assert job.spec == processing_spec(project.fx_chain)


def test_the_destination_follows_the_chain(tmp_path: Path) -> None:
    project = make_project([place(PLACE_1, LINE_A)])
    before = plan_jobs(tmp_path, project)[0].dest
    project.fx_chain = FxChain(eq_treble_db=3.0)
    assert plan_jobs(tmp_path, project)[0].dest != before


def test_an_unusable_chain_plans_nothing(tmp_path: Path) -> None:
    project = make_project([place(PLACE_1, LINE_A)])
    project.fx_chain.eq_bass_db = 99.0
    assert plan_jobs(tmp_path, project) == []


# --- Prefetcher ----------------------------------------------------------------


def job(name: str) -> RenderJob:
    folder = Path("project") / "media"
    return RenderJob(
        raw_path=folder / "takes_raw" / f"{name}.wav",
        raw_key="k" * 64,
        stretch=1.0,
        spec={},
        dest=folder / "takes_fx" / f"{name}.wav",
    )


class Recorder:
    """A fake render that notes which jobs it was given."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(self, item: RenderJob) -> None:
        self.names.append(item.dest.stem)


def test_every_requested_job_is_rendered_in_order() -> None:
    recorder = Recorder()
    prefetcher = Prefetcher(render=recorder)
    prefetcher.request([job("a"), job("b"), job("c")])
    assert prefetcher.join(5)
    assert recorder.names == ["a", "b", "c"]
    prefetcher.close()


def test_the_newest_request_replaces_the_pending_jobs() -> None:
    entered = threading.Event()
    release = threading.Event()
    names: list[str] = []

    def render(item: RenderJob) -> None:
        names.append(item.dest.stem)
        if item.dest.stem == "a":
            entered.set()
            assert release.wait(5)

    prefetcher = Prefetcher(render=render)
    prefetcher.request([job("a"), job("b"), job("c")])
    assert entered.wait(5)  # "a" is being rendered; "b" and "c" are still waiting
    prefetcher.request([job("d")])
    release.set()
    assert prefetcher.join(5)
    assert names == ["a", "d"]  # "a" finished, "b" and "c" were dropped
    prefetcher.close()


def test_a_failed_render_is_remembered_and_the_rest_still_run() -> None:
    names: list[str] = []

    def render(item: RenderJob) -> None:
        if item.dest.stem == "bad":
            raise ProcessError("boom")
        names.append(item.dest.stem)

    prefetcher = Prefetcher(render=render)
    prefetcher.request([job("bad"), job("good")])
    assert prefetcher.join(5)
    assert names == ["good"]
    assert prefetcher.error() == "boom"
    prefetcher.request([job("good")])  # a new request starts with a clean slate
    assert prefetcher.join(5)
    assert prefetcher.error() is None
    prefetcher.close()


def test_a_value_error_does_not_stop_the_worker() -> None:
    names: list[str] = []

    def render(item: RenderJob) -> None:
        if item.dest.stem == "odd":
            raise ValueError("odd take")
        names.append(item.dest.stem)

    prefetcher = Prefetcher(render=render)
    prefetcher.request([job("odd"), job("fine")])
    assert prefetcher.join(5)
    assert names == ["fine"]
    assert prefetcher.error() == "odd take"
    prefetcher.close()


def test_on_idle_runs_once_after_the_list_is_drained() -> None:
    calls: list[int] = []
    recorder = Recorder()
    prefetcher = Prefetcher(
        render=recorder, on_idle=lambda: calls.append(len(recorder.names))
    )
    prefetcher.request([job("a"), job("b"), job("c")])
    assert prefetcher.join(5)
    assert calls == [3]  # once, after all three
    prefetcher.request([])  # an empty request still ends in one idle call
    assert prefetcher.join(5)
    assert calls == [3, 3]
    prefetcher.close()


def test_the_default_render_skips_a_take_whose_file_is_gone(tmp_path: Path) -> None:
    prefetcher = Prefetcher()
    missing = RenderJob(
        raw_path=tmp_path / "media" / "takes_raw" / "gone.wav",
        raw_key="k" * 64,
        stretch=1.0,
        spec={},
        dest=tmp_path / "media" / "takes_fx" / "gone.wav",
    )
    prefetcher.request([missing])
    assert prefetcher.join(5)
    assert prefetcher.error() is None
    prefetcher.close()


def test_nothing_runs_after_close() -> None:
    recorder = Recorder()
    prefetcher = Prefetcher(render=recorder)
    prefetcher.request([job("a")])
    assert prefetcher.join(5)
    prefetcher.close()
    prefetcher.request([job("b")])
    assert recorder.names == ["a"]
