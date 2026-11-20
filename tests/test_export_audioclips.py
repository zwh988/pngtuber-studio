"""Audio-lane clips in the export (M8-1): the level rules (same as the preview's
audioMix.ts), the mix, the bundle file, the final ffmpeg filters and the pre-flight."""

from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.export.audioclips import (
    AUDIO_CLIPS_NAME,
    AudioClipCue,
    audible_lane_ids,
    audio_clip_schedule,
    clip_envelope,
    db_to_gain,
    gain_points,
    mix_audio_clips,
    write_audio_clip_track,
)
from backend.export.editgraph import OutputFormat, build_edit_graph
from backend.export.errors import ExportError
from backend.export.preflight import preflight
from backend.export.runner import final_filters, first_clip_input
from backend.project.schema import (
    AudioClip,
    AudioFile,
    AudioLane,
    Clip,
    Project,
    Source,
)
from backend.project.timeline import build_timeline


def hid(n: int) -> str:
    return f"{n:012x}"


L1, L2, F1, F2 = hid(1), hid(2), hid(3), hid(4)
RATE = 1000  # 1 sample per ms keeps the maths readable


def make_clip(**over: object) -> AudioClip:
    data: dict[str, object] = {
        "id": hid(10),
        "lane_id": L1,
        "file_id": F1,
        "timeline_ms": 1000,
        "in_ms": 500,
        "out_ms": 4500,
    }
    data.update(over)
    return AudioClip.model_validate(data)


def make_file(file_id: str, name: str, ms: int = 10_000) -> AudioFile:
    return AudioFile(
        id=file_id,
        path=f"audio/{name}",
        name=name,
        size_bytes=1,
        duration_ms=ms,
        sample_rate=48_000,
        channels=2,
    )


def project_with(
    clips: list[AudioClip], lanes: list[AudioLane] | None = None
) -> Project:
    return Project(
        name="p",
        audio_files=[make_file(F1, "music.mp3"), make_file(F2, "pop.wav")],
        audio_lanes=lanes or [AudioLane(id=L1), AudioLane(id=L2, name="Audio 2")],
        audio_clips=clips,
    )


# ---- level rules: the same cases as frontend/src/audioMix.test.ts --------------------


def test_gain_points_flat_at_clip_plus_lane_gain() -> None:
    assert gain_points(make_clip(gain_db=-6), 0) == [
        (0, db_to_gain(-6)),
        (4000, db_to_gain(-6)),
    ]
    assert gain_points(make_clip(gain_db=-3), -3)[0][1] == pytest.approx(db_to_gain(-6))


def test_gain_points_with_fades() -> None:
    assert gain_points(make_clip(fade_in_ms=1000, fade_out_ms=2000), 0) == [
        (0, 0.0),
        (1000, 1.0),
        (2000, 1.0),
        (4000, 0.0),
    ]
    assert gain_points(make_clip(fade_in_ms=2000, fade_out_ms=2000), 0) == [
        (0, 0.0),
        (2000, 1.0),
        (4000, 0.0),
    ]


def test_audible_lanes_follow_mute_and_solo() -> None:
    a, b, c = (
        AudioLane(id=hid(1)),
        AudioLane(id=hid(2), mute=True),
        AudioLane(id=hid(3)),
    )
    assert audible_lane_ids([a, b, c]) == {a.id, c.id}
    soloed = [
        a.model_copy(update={"solo": True}),
        b.model_copy(update={"solo": True}),
        c,
    ]
    assert audible_lane_ids(soloed) == {a.id}


def test_schedule_skips_unheard_and_late_clips() -> None:
    clips = [
        make_clip(),
        make_clip(id=hid(11), lane_id=L2, timeline_ms=0, in_ms=0, out_ms=100),
        make_clip(id=hid(12), timeline_ms=20_000, in_ms=0, out_ms=100),
    ]
    project = project_with(
        clips, [AudioLane(id=L1, gain_db=-6), AudioLane(id=L2, mute=True)]
    )
    cues = audio_clip_schedule(project, total_ms=10_000)
    assert [c.clip_id for c in cues] == [hid(10)]
    assert cues[0].points[0][1] == pytest.approx(db_to_gain(-6))


def test_clip_envelope_is_linear() -> None:
    env = clip_envelope(((0, 0.0), (10, 1.0), (20, 1.0)), 21, RATE)
    assert (
        env[0] == 0 and env[5] == pytest.approx(0.5) and env[10] == 1 and env[20] == 1
    )


# ---- mix -------------------------------------------------------------------------------


def cue(
    start: int, in_ms: int, length: int, points: tuple[tuple[int, float], ...]
) -> AudioClipCue:
    return AudioClipCue(
        clip_id="c",
        file_id="f",
        start_ms=start,
        in_ms=in_ms,
        length_ms=length,
        points=points,
    )


def test_mix_places_trims_and_upmixes_mono() -> None:
    mono = np.arange(100, dtype=np.float32) / 100  # sample k = k/100
    flat = ((0, 1.0), (10, 1.0))
    track, peak, cut = mix_audio_clips([(cue(5, 20, 10, flat), mono)], RATE, 50)
    assert track.shape == (50, 2)
    assert track[4].tolist() == [0, 0]
    assert track[5].tolist() == pytest.approx(
        [0.20, 0.20]
    )  # file sample 20 on both channels
    assert track[14].tolist() == pytest.approx([0.29, 0.29])
    assert track[15].tolist() == [0, 0]
    assert peak == pytest.approx(0.29) and cut == 0


def test_mix_applies_fades_sums_and_cuts_at_the_end() -> None:
    stereo = np.ones((100, 2), dtype=np.float32)
    stereo[:, 1] = 0.5
    fade = ((0, 0.0), (10, 1.0), (20, 1.0))
    track, peak, cut = mix_audio_clips(
        [
            (cue(0, 0, 20, fade), stereo),
            (cue(15, 0, 20, ((0, 1.0), (20, 1.0))), stereo),
        ],
        RATE,
        30,
    )
    assert track[5].tolist() == pytest.approx([0.5, 0.25])
    assert track[17].tolist() == pytest.approx([2.0, 1.0])  # two clips overlap: summed
    assert peak == pytest.approx(2.0)
    assert cut == 5  # the second clip runs 5 ms past the end


def test_write_track_from_decoded_files(tmp_path: Path) -> None:
    decoded = tmp_path / "dec.wav"
    soundfile.write(str(decoded), np.full((48_000, 2), 0.25, dtype=np.float32), 48_000)
    clip = make_clip(timeline_ms=100, in_ms=0, out_ms=500, gain_db=-6)
    out = tmp_path / "out"
    out.mkdir()
    report = write_audio_clip_track(project_with([clip]), 1000, out, {F1: decoded})
    assert report is not None
    assert (report.clips, report.cut_ms) == (1, 0)
    assert report.files == [{"path": "audio/music.mp3", "name": "music.mp3"}]
    data, rate = soundfile.read(str(out / AUDIO_CLIPS_NAME), always_2d=True)
    assert rate == 48_000 and data.shape == (48_000, 2)
    assert data[4800 + 100, 0] == pytest.approx(0.25 * db_to_gain(-6), rel=1e-5)
    assert data[4799, 0] == 0 and data[28_800, 0] == 0


def test_write_track_none_without_heard_clips_and_error_when_missing(
    tmp_path: Path,
) -> None:
    assert write_audio_clip_track(project_with([]), 1000, tmp_path, {}) is None
    with pytest.raises(ExportError, match="music.mp3 is missing"):
        write_audio_clip_track(project_with([make_clip()]), 10_000, tmp_path, {})


# ---- final ffmpeg filters --------------------------------------------------------------

FMT = OutputFormat(width=1920, height=1080, fps=Fraction(30, 1))


def footage_project() -> Project:
    return Project(
        name="p",
        sources=[
            Source(
                id=hid(50),
                path="footage/a.mkv",
                duration_ms=60_000,
                fps_num=30,
                width=1920,
                height=1080,
                audio_tracks=1,
            )
        ],
        clips=[Clip(id=hid(51), source_id=hid(50), in_ms=0, out_ms=2000)],
    )


def test_music_is_a_third_input_mixed_before_the_limiter() -> None:
    assert first_clip_input(False, True) == 2 and first_clip_input(True, True) == 3
    project = footage_project()
    graph = build_edit_graph(project, {hid(50): Path("a.mkv")}, FMT, first_input=3)
    filters = final_filters(graph, FMT, with_avatar=True, game_db=0, with_music=True)
    joined = ";".join(filters)
    assert "[2:a:0]aresample=48000" in joined  # [0] avatar, [1] voice, [2] music
    assert "[game][voice][music]amix=inputs=3:normalize=0" in joined
    assert joined.index("amix") < joined.index("alimiter")
    plain = ";".join(final_filters(graph, FMT, with_avatar=False, game_db=0))
    assert "[game][voice]amix=inputs=2" in plain and "[music]" not in plain


# ---- pre-flight ------------------------------------------------------------------------


def test_preflight_blocks_a_missing_audio_file() -> None:
    project = footage_project().model_copy(
        update={
            "audio_files": [make_file(F1, "music.mp3")],
            "audio_lanes": [AudioLane(id=L1)],
            "audio_clips": [make_clip(), make_clip(id=hid(11), timeline_ms=6000)],
        }
    )
    report = preflight(project, build_timeline(project), missing_audio_file_ids={F1})
    issues = [i for i in report.issues if i.kind == "audio_file_missing"]
    assert len(issues) == 1 and issues[0].severity == "error" and issues[0].t_ms == 1000
    assert "music.mp3" in issues[0].message
    clean = preflight(project, build_timeline(project))
    assert not any(i.kind == "audio_file_missing" for i in clean.issues)
