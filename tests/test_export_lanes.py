"""Video-lane clips in the export (M8-2): picture maths, inputs, filter text, layering
around the avatar and padding past the footage. Pure; the real render is in
``test_export_render.py``."""

from fractions import Fraction
from pathlib import Path

import pytest

from backend.export.editgraph import OutputFormat, build_edit_graph
from backend.export.errors import ExportError
from backend.export.lanes import (
    PipRect,
    build_lane_graph,
    overlay_steps,
    pip_rect,
    program_end_ms,
)
from backend.export.runner import final_filters
from backend.project.schema import (
    AudioClip,
    AudioFile,
    AudioLane,
    Clip,
    ImageFile,
    LaneClip,
    Project,
    Source,
    VideoLane,
)

FMT = OutputFormat(1920, 1080, Fraction(30))
MAIN, BROLL, MUTE = "1" * 12, "2" * 12, "3" * 12
IMG = "4" * 12
V2, V3, V4 = "a" * 12, "b" * 12, "c" * 12
PATHS = {MAIN: Path("C:/f/main.mp4"), BROLL: Path("C:/f/b roll.mp4"), MUTE: Path("C:/f/m.mp4")}
IMAGES = {IMG: Path("C:/p/images/title.png")}


def hid(n: int) -> str:
    return f"{n:012x}"


def make_project(**kw: object) -> Project:
    return Project(
        name="t",
        sources=[
            Source(id=MAIN, path="footage/main.mp4", duration_ms=10_000, fps_num=30, width=1920, height=1080, audio_tracks=1),
            Source(id=BROLL, path="footage/b roll.mp4", duration_ms=8000, fps_num=30, width=1280, height=720, audio_tracks=1),
            Source(id=MUTE, path="footage/m.mp4", duration_ms=8000, fps_num=30, width=640, height=480),
        ],
        clips=[Clip(id=hid(1), source_id=MAIN, in_ms=0, out_ms=4000)],
        image_files=[ImageFile(id=IMG, path="images/title.png", name="title.png", size_bytes=1, width=800, height=200)],
        video_lanes=[VideoLane(id=V2, name="Video 2"), VideoLane(id=V3, name="Video 3"), VideoLane(id=V4, name="Video 4")],
        **kw,
    )  # fmt: skip


def test_pip_rect_matches_the_preview() -> None:
    # The same case as videoLanes.test.ts: a 16:9 picture at 40 % in the lower right.
    assert pip_rect(1920, 1080, 1280, 720, 0.72, 0.7, 0.4) == PipRect(998, 540, 768, 432)
    assert pip_rect(1920, 1080, 1920, 1080, 0.5, 0.5, 1.0) == PipRect(0, 0, 1920, 1080)
    # 4:1 title fitted by width, half size, centred.
    assert pip_rect(1920, 1080, 800, 200, 0.5, 0.5, 0.5) == PipRect(480, 420, 960, 240)
    assert pip_rect(1920, 1080, 800, 200, 0.5, 0.5, 0.0005).width == 2  # never below 2 px
    with pytest.raises(ExportError):
        pip_rect(1920, 1080, 0, 0, 0.5, 0.5, 1.0)


def test_program_end_is_the_last_clip_on_any_lane() -> None:
    project = make_project()
    assert program_end_ms(project) == 4000
    project.lane_clips.append(LaneClip(id=hid(10), lane_id=V2, image_id=IMG, timeline_ms=3000, out_ms=3500))
    assert program_end_ms(project) == 6500
    project.audio_files.append(
        AudioFile(id=hid(20), path="audio/a.wav", name="a.wav", size_bytes=1, duration_ms=9000, sample_rate=48_000, channels=2)
    )
    project.audio_lanes = [AudioLane(id=hid(21))]
    project.audio_clips.append(AudioClip(id=hid(22), lane_id=hid(21), file_id=hid(20), timeline_ms=1000, out_ms=7000))
    assert program_end_ms(project) == 8000


def clips_project() -> Project:
    return make_project(
        lane_clips=[
            # Video 2: a title (still), half transparent.
            LaneClip(id=hid(10), lane_id=V2, image_id=IMG, timeline_ms=1000, out_ms=1000, opacity=0.5, scale=0.5),
            # Video 3: B-roll with sound at -6 dB, then a freeze frame of it.
            LaneClip(id=hid(11), lane_id=V3, source_id=BROLL, timeline_ms=500, in_ms=2000, out_ms=3000, gain_db=-6, x=0.75, y=0.25, scale=0.25),
            LaneClip(id=hid(12), lane_id=V3, source_id=BROLL, timeline_ms=1500, out_ms=1000, freeze_ms=3000),
            # Video 4: a muted recording, and a clip on a hidden lane is left out below.
            LaneClip(id=hid(13), lane_id=V4, source_id=BROLL, timeline_ms=0, in_ms=0, out_ms=1000, mute=True),
            LaneClip(id=hid(14), lane_id=V4, source_id=MUTE, timeline_ms=2000, in_ms=0, out_ms=1000),
        ],
    )  # fmt: skip


def test_lane_graph_inputs_filters_and_sound() -> None:
    graph = build_lane_graph(clips_project(), PATHS, IMAGES, FMT, 4000, first_input=5)
    assert [i.clip_id for i in graph.inputs] == [hid(n) for n in (10, 11, 12, 13, 14)]  # bottom lane first
    assert graph.inputs[0].args == ("-loop", "1", "-framerate", "30/1", "-t", "1.000", "-i", "C:\\p\\images\\title.png")
    assert graph.inputs[1].args == ("-ss", "2.000", "-t", "1.000", "-i", "C:\\f\\b roll.mp4")
    assert graph.inputs[2].args == ("-ss", "3.000", "-t", "0.250", "-i", "C:\\f\\b roll.mp4")
    title, broll, frozen = graph.filters[0], graph.filters[1], graph.filters[3]
    assert title == (
        "[5:v:0]setpts=PTS-STARTPTS,fps=30/1,scale=960:240,setsar=1,format=rgba,"
        "colorchannelmixer=aa=0.5000,tpad=stop_mode=clone:stop=31,trim=end_frame=31,"
        "setpts=PTS-STARTPTS+30*1/30/TB[lane0]"
    )
    assert broll.startswith("[6:v:0]setpts=PTS-STARTPTS,fps=30/1,scale=480:270,")
    assert "colorchannelmixer" not in broll
    assert graph.filters[2] == (
        "[6:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "volume=-6.00dB,apad,atrim=end_sample=48000,adelay=delays=24000S:all=1,apad,"
        "atrim=end_sample=192000[lanea1]"
    )
    assert frozen.startswith("[7:v:0]trim=end_frame=1,setpts=PTS-STARTPTS,")
    assert graph.audio == ["lanea1"]  # the freeze, the muted clip and the silent file add none
    b = graph.layers[1]
    assert (b.left, b.top, b.start_frame, b.end_frame) == (1200, 135, 15, 45)
    assert all(not layer.over_avatar for layer in graph.layers)  # avatar on top by default


def test_hidden_lanes_the_avatar_layer_and_the_end() -> None:
    project = clips_project()
    project.video_lanes[2].hidden = True
    project.avatar_below_lane_id = V3
    graph = build_lane_graph(project, PATHS, IMAGES, FMT, 1800, first_input=0)
    # Video 4 is hidden; the freeze frame is cut at 1.8 s.
    assert [layer.clip_id for layer in graph.layers] == [hid(10), hid(11), hid(12)]
    assert [layer.over_avatar for layer in graph.layers] == [False, True, True]
    assert graph.layers[2].end_frame == 54
    with pytest.raises(ExportError, match="cannot be found"):
        build_lane_graph(project, {}, IMAGES, FMT, 4000, first_input=0)


def test_overlay_steps_and_final_layering() -> None:
    project = clips_project()
    project.avatar_below_lane_id = V3
    graph = build_lane_graph(project, PATHS, IMAGES, FMT, 4000, first_input=3)
    under = [layer for layer in graph.layers if not layer.over_avatar]
    steps = overlay_steps("vmain", under, "vunder", FMT, "lu")
    assert steps == [
        (
            "[vmain][lane0]overlay=x=480:y=420:eof_action=pass:format=auto:"
            "enable='gte(t,30*1/30)*lt(t,60*1/30)'[vunder]"
        )
    ]
    assert overlay_steps("a", [], "b", FMT, "x") == ["[a]null[b]"]
    edit = build_edit_graph(project, PATHS, FMT, first_input=2, total_ms=4000)
    filters = final_filters(edit, FMT, with_avatar=True, game_db=0, lanes=graph)
    text = "\n".join(filters)
    assert text.index("[vunder][avatar]overlay") < text.index("[vavatar][lane1]overlay")
    assert "[game][voice][lanea1]amix=inputs=3:" in text


def test_edit_graph_pads_past_the_footage() -> None:
    project = make_project()
    graph = build_edit_graph(project, PATHS, FMT, total_ms=6000)
    assert (graph.frames, graph.samples, graph.duration_ms) == (180, 288_000, 6000)
    assert graph.filters[-3].endswith("concat=n=1:v=1:a=1[vcat][acat]")
    assert graph.filters[-2] == "[vcat]tpad=stop_mode=add:stop=60:color=black[vedit]"
    assert graph.filters[-1] == "[acat]apad=whole_len=288000[aedit]"
    same = build_edit_graph(project, PATHS, FMT, total_ms=3000)  # never shorter than the footage
    assert same.duration_ms == 4000 and same.filters[-1].endswith("[vedit][aedit]")
