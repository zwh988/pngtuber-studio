"""Tests for backend/edl/timemap.py (pure, no I/O)."""

from backend.edl.timemap import (
    clip_duration_ms,
    clip_spans,
    frame_to_ms,
    ms_to_frame,
    round_half_up,
    snap_to_frame,
    timeline_duration,
    to_source,
    to_timeline,
)
from backend.project.schema import Anchor, Clip

SRC = "5" * 12


def cid(n: int) -> str:
    return f"{n:012x}"


def make_clip(
    n: int, in_ms: int, out_ms: int, speed: float = 1.0, track: int = 0
) -> Clip:
    return Clip(
        id=cid(n), source_id=SRC, in_ms=in_ms, out_ms=out_ms, speed=speed, track=track
    )


def anchor(n: int, source_ms: int) -> Anchor:
    return Anchor(clip_id=cid(n), source_ms=source_ms)


# --------------------------------------------------------------------------
# rounding and frames
# --------------------------------------------------------------------------


def test_round_half_up_ties_go_up() -> None:
    from fractions import Fraction

    assert round_half_up(Fraction(1, 2)) == 1
    assert round_half_up(Fraction(3, 2)) == 2
    assert round_half_up(Fraction(5, 2)) == 3  # not banker's rounding
    assert round_half_up(Fraction(49, 100)) == 0
    assert round_half_up(7) == 7


def test_frame_to_ms_60_fps() -> None:
    assert frame_to_ms(0, 60, 1) == 0
    assert frame_to_ms(1, 60, 1) == 17  # 16.667
    assert frame_to_ms(3, 60, 1) == 50
    assert frame_to_ms(60, 60, 1) == 1000


def test_frame_to_ms_59_94_fps() -> None:
    assert frame_to_ms(1, 60000, 1001) == 17  # 16.683
    assert frame_to_ms(2, 60000, 1001) == 33  # 33.367
    assert frame_to_ms(3, 60000, 1001) == 50  # 50.050
    assert frame_to_ms(60, 60000, 1001) == 1001


def test_ms_to_frame_rounds_to_nearest_not_floor() -> None:
    # 25 ms is 1.498 frames at 59.94: nearest is 1; 26 ms is 1.558: nearest is 2.
    assert ms_to_frame(25, 60000, 1001) == 1
    assert ms_to_frame(26, 60000, 1001) == 2
    assert ms_to_frame(0, 60000, 1001) == 0


def test_ms_to_frame_tie_rounds_up() -> None:
    # 1 fps: frames at 0 and 1000 ms; 500 ms is exactly between them.
    assert ms_to_frame(500, 1, 1) == 1
    assert ms_to_frame(499, 1, 1) == 0


def test_snap_to_frame_values() -> None:
    assert snap_to_frame(0, 60, 1) == 0
    assert snap_to_frame(8, 60, 1) == 0
    assert snap_to_frame(10, 60, 1) == 17
    assert snap_to_frame(25, 60000, 1001) == 17
    assert snap_to_frame(26, 60000, 1001) == 33
    assert snap_to_frame(1001, 60000, 1001) == 1001


def test_snap_to_frame_is_idempotent() -> None:
    for fps_num, fps_den in ((60, 1), (60000, 1001), (30, 1), (24000, 1001)):
        for ms in range(0, 5000, 7):
            once = snap_to_frame(ms, fps_num, fps_den)
            assert snap_to_frame(once, fps_num, fps_den) == once


def test_frame_index_round_trip() -> None:
    for fps_num, fps_den in ((60, 1), (60000, 1001)):
        for frame in range(0, 10000, 13):
            ms = frame_to_ms(frame, fps_num, fps_den)
            assert ms_to_frame(ms, fps_num, fps_den) == frame


def test_snap_error_is_at_most_half_a_frame_plus_rounding() -> None:
    for ms in range(3000):
        assert abs(snap_to_frame(ms, 60000, 1001) - ms) <= 9  # 8.34 + 0.5 rounding


# --------------------------------------------------------------------------
# spans and duration
# --------------------------------------------------------------------------


def test_empty_list() -> None:
    assert clip_spans([]) == []
    assert timeline_duration([]) == 0
    assert to_timeline([], anchor(1, 0)) is None
    assert to_source([], 0) is None


def test_single_clip_span() -> None:
    clips = [make_clip(1, 0, 5000)]
    spans = clip_spans(clips)
    assert len(spans) == 1
    span = spans[0]
    assert (span.clip_id, span.index) == (cid(1), 0)
    assert (span.start_ms, span.end_ms, span.duration_ms) == (0, 5000, 5000)
    assert timeline_duration(clips) == 5000


def test_trimmed_clip_starts_at_zero_on_timeline() -> None:
    clips = [make_clip(1, 2000, 3500)]
    assert clip_spans(clips)[0].start_ms == 0
    assert timeline_duration(clips) == 1500


def test_several_clips_are_gapless_in_list_order() -> None:
    clips = [make_clip(1, 0, 1000), make_clip(2, 500, 2500), make_clip(3, 0, 300)]
    spans = clip_spans(clips)
    assert [(s.start_ms, s.end_ms) for s in spans] == [(0, 1000), (1000, 3000), (3000, 3300)]
    assert [s.clip_id for s in spans] == [cid(1), cid(2), cid(3)]
    assert timeline_duration(clips) == 3300


def test_speed_changes_duration() -> None:
    assert clip_duration_ms(make_clip(1, 0, 1000, 2.0)) == 500
    assert clip_duration_ms(make_clip(1, 0, 1000, 0.25)) == 4000
    assert clip_duration_ms(make_clip(1, 0, 8000, 8.0)) == 1000
    assert clip_duration_ms(make_clip(1, 0, 1000, 0.5)) == 2000


def test_duration_rounds_half_up() -> None:
    assert clip_duration_ms(make_clip(1, 0, 12, 8.0)) == 2  # 1.5 -> 2
    assert clip_duration_ms(make_clip(1, 0, 4, 8.0)) == 1  # 0.5 -> 1
    assert clip_duration_ms(make_clip(1, 0, 20, 8.0)) == 3  # 2.5 -> 3
    assert clip_duration_ms(make_clip(1, 0, 3, 8.0)) == 0  # 0.375 -> 0


def test_decimal_speed_is_exact() -> None:
    # 1.1 as a binary float is slightly above 1.1; the decimal text must be used.
    assert clip_duration_ms(make_clip(1, 0, 11, 1.1)) == 10
    assert clip_duration_ms(make_clip(1, 0, 33, 1.1)) == 30


def test_spans_mixed_speeds_accumulate_rounded_lengths() -> None:
    clips = [make_clip(1, 0, 1000, 2.0), make_clip(2, 0, 1000, 0.25), make_clip(3, 0, 12, 8.0)]
    spans = clip_spans(clips)
    assert [(s.start_ms, s.end_ms) for s in spans] == [(0, 500), (500, 4500), (4500, 4502)]


def test_other_tracks_are_ignored_but_indexes_refer_to_input_list() -> None:
    clips = [make_clip(1, 0, 1000), make_clip(2, 0, 9999, track=1), make_clip(3, 0, 400)]
    spans = clip_spans(clips)
    assert [(s.clip_id, s.index, s.start_ms, s.end_ms) for s in spans] == [
        (cid(1), 0, 0, 1000),
        (cid(3), 2, 1000, 1400),
    ]
    assert timeline_duration(clips) == 1400
    assert to_timeline(clips, anchor(2, 100)) is None


# --------------------------------------------------------------------------
# to_timeline
# --------------------------------------------------------------------------


def test_to_timeline_basic_and_edges() -> None:
    clips = [make_clip(1, 1000, 2000), make_clip(2, 0, 500)]
    assert to_timeline(clips, anchor(1, 1000)) == 0
    assert to_timeline(clips, anchor(1, 1400)) == 400
    assert to_timeline(clips, anchor(1, 2000)) == 1000  # out edge maps to the clip end
    assert to_timeline(clips, anchor(2, 0)) == 1000
    assert to_timeline(clips, anchor(2, 250)) == 1250


def test_to_timeline_outside_clip_or_unknown_clip_is_none() -> None:
    clips = [make_clip(1, 1000, 2000)]
    assert to_timeline(clips, anchor(1, 999)) is None
    assert to_timeline(clips, anchor(1, 2001)) is None
    assert to_timeline(clips, anchor(9, 1500)) is None


def test_to_timeline_with_speed() -> None:
    clips = [make_clip(1, 0, 1000, 2.0), make_clip(2, 0, 1000, 0.5)]
    assert to_timeline(clips, anchor(1, 600)) == 300
    assert to_timeline(clips, anchor(2, 100)) == 500 + 200
    assert to_timeline(clips, anchor(2, 1000)) == 500 + 2000


def test_to_timeline_rounds_half_up() -> None:
    clips = [make_clip(1, 0, 1000, 2.0)]
    assert to_timeline(clips, anchor(1, 1)) == 1  # 0.5 -> 1
    assert to_timeline(clips, anchor(1, 3)) == 2  # 1.5 -> 2


def test_reordering_keeps_anchors_attached() -> None:
    a = make_clip(1, 0, 1000)
    b = make_clip(2, 200, 1200)
    item = anchor(2, 700)  # 500 ms into clip b
    assert to_timeline([a, b], item) == 1000 + 500
    assert to_timeline([b, a], item) == 500  # b first now; the anchor did not change
    assert item.source_ms == 700 and item.clip_id == cid(2)


def test_trim_moves_timeline_time_but_not_source_time() -> None:
    before = [make_clip(1, 0, 5000)]
    after = [make_clip(1, 1000, 5000)]
    item = anchor(1, 3000)
    assert to_timeline(before, item) == 3000
    assert to_timeline(after, item) == 2000


def test_speed_change_ripples_timeline_time_not_source_time() -> None:
    item = anchor(2, 500)
    slow = [make_clip(1, 0, 1000), make_clip(2, 0, 1000)]
    fast = [make_clip(1, 0, 1000, 2.0), make_clip(2, 0, 1000)]
    assert to_timeline(slow, item) == 1500
    assert to_timeline(fast, item) == 1000  # first clip got shorter, ripple


def test_precomputed_spans_give_same_results() -> None:
    clips = [make_clip(1, 0, 1000), make_clip(2, 0, 1000, 4.0)]
    spans = clip_spans(clips)
    assert to_timeline(clips, anchor(2, 400), spans=spans) == to_timeline(clips, anchor(2, 400))
    assert to_source(clips, 1100, spans=spans) == to_source(clips, 1100)


# --------------------------------------------------------------------------
# to_source
# --------------------------------------------------------------------------


def test_to_source_basic() -> None:
    clips = [make_clip(1, 1000, 2000), make_clip(2, 0, 500)]
    assert to_source(clips, 0) == anchor(1, 1000)
    assert to_source(clips, 400) == anchor(1, 1400)
    assert to_source(clips, 1250) == anchor(2, 250)


def test_to_source_boundary_belongs_to_the_clip_that_starts_there() -> None:
    clips = [make_clip(1, 0, 1000), make_clip(2, 300, 800)]
    assert to_source(clips, 999) == anchor(1, 999)
    assert to_source(clips, 1000) == anchor(2, 300)


def test_to_source_outside_timeline_is_none() -> None:
    clips = [make_clip(1, 0, 1000)]
    assert to_source(clips, -1) is None
    assert to_source(clips, 1000) is None  # the very end belongs to no clip
    assert to_source(clips, 5000) is None


def test_to_source_with_speed() -> None:
    clips = [make_clip(1, 0, 1000, 2.0)]
    assert to_source(clips, 100) == anchor(1, 200)
    slow = [make_clip(1, 0, 1000, 0.5)]
    assert to_source(slow, 100) == anchor(1, 50)


def test_to_source_never_returns_out_ms() -> None:
    # speed 0.25: last timeline ms would round up to out_ms; it must clamp to out - 1.
    clips = [make_clip(1, 0, 10, 0.25)]  # 40 ms long
    last = to_source(clips, 39)
    assert last is not None
    assert last.source_ms == 9


def test_anchor_in_last_half_speed_ms_maps_to_clip_end() -> None:
    # At 2x, source 399 of 0..400 is 199.5 -> 200 ms: the clip's end, which is
    # also where the next clip starts. Known quantization edge, not a bug.
    clips = [make_clip(1, 0, 400, 2.0), make_clip(2, 0, 400)]
    assert to_timeline(clips, anchor(1, 399)) == 200
    assert to_timeline(clips, anchor(1, 398)) == 199


def test_to_source_skips_zero_length_spans() -> None:
    clips = [make_clip(1, 0, 3, 8.0), make_clip(2, 0, 800)]  # clip 1 lasts 0 ms
    assert to_source(clips, 0) == anchor(2, 0)


# --------------------------------------------------------------------------
# round trips
# --------------------------------------------------------------------------


def _multi(speed: float) -> list[Clip]:
    return [
        make_clip(1, 0, 2400, speed),
        make_clip(2, 1000, 5000, speed),
        make_clip(3, 333, 1777, speed),
    ]


def test_timeline_source_timeline_exact_at_speed_one_and_above() -> None:
    for speed in (1.0, 1.5, 2.0, 4.0, 8.0):
        clips = _multi(speed)
        for t in range(timeline_duration(clips)):
            back = to_source(clips, t)
            assert back is not None
            assert to_timeline(clips, back) == t, (speed, t)


def test_timeline_source_timeline_error_bounded_below_speed_one() -> None:
    for speed in (0.25, 0.5):
        clips = _multi(speed)
        bound = 1 / speed  # 0.5/speed rounding, plus the clamp to out - 1 at a clip's last ms
        for t in range(timeline_duration(clips)):
            back = to_source(clips, t)
            assert back is not None
            mapped = to_timeline(clips, back)
            assert mapped is not None
            assert abs(mapped - t) <= bound, (speed, t, mapped)


def test_source_timeline_source_error_bounded() -> None:
    for speed in (0.25, 0.5, 1.0, 2.0, 8.0):
        clips = _multi(speed)
        bound = speed / 2 + 0.5
        for n, clip in enumerate(clips, start=1):
            for source_ms in range(clip.in_ms, clip.out_ms):
                t = to_timeline(clips, anchor(n, source_ms))
                assert t is not None
                back = to_source(clips, t)
                if back is None:  # last ms of timeline rounding up to the end
                    continue
                assert back.clip_id in {cid(n), cid(n + 1)}
                if back.clip_id == cid(n):
                    assert abs(back.source_ms - source_ms) <= bound, (speed, source_ms)


def test_round_trip_at_speed_one_is_exact_in_both_directions() -> None:
    clips = _multi(1.0)
    for n, clip in enumerate(clips, start=1):
        for source_ms in range(clip.in_ms, clip.out_ms):
            t = to_timeline(clips, anchor(n, source_ms))
            assert t is not None
            assert to_source(clips, t) == anchor(n, source_ms)


def test_trim_then_reorder_round_trip() -> None:
    a = make_clip(1, 100, 900)
    b = make_clip(2, 0, 400, 2.0)
    c = make_clip(3, 50, 650)
    reordered = [c, a, b]
    for n, clip in ((1, a), (2, b), (3, c)):
        for source_ms in (clip.in_ms, (clip.in_ms + clip.out_ms) // 2, clip.out_ms - 4):
            t = to_timeline(reordered, anchor(n, source_ms))
            assert t is not None
            back = to_source(reordered, t)
            assert back is not None and back.clip_id == cid(n)
            assert abs(back.source_ms - source_ms) <= 1
