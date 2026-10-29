"""Overflow flags on placed lines (M3-9, S8a). Pure: no project needed."""

from backend.project.timeline import TimelinePlacement, mark_overflows


def placed(
    pid: str,
    start: int | None,
    duration: int | None,
    *,
    allow: bool = False,
    orphaned: bool = False,
) -> TimelinePlacement:
    end = None if start is None or duration is None else start + duration
    return TimelinePlacement(
        id=pid,
        line_id="l" + pid,
        line_text=pid,
        allow_overlap=allow,
        take_id=None if duration is None else "t" + pid,
        duration_ms=duration,
        raw_duration_ms=duration,
        start_ms=start,
        end_ms=end,
        anchor_clip_id="c1",
        anchor_source_ms=0,
        orphaned=orphaned,
    )


def by_id(items: list[TimelinePlacement]) -> dict[str, TimelinePlacement]:
    return {p.id: p for p in items}


def test_no_overflow_leaves_zero() -> None:
    out = by_id(mark_overflows([placed("a", 0, 1000), placed("b", 1000, 500)]))
    assert out["a"].overflow_ms == 0
    assert out["a"].overflow_next_id is None


def test_overflow_is_measured_and_names_the_next_line() -> None:
    out = by_id(mark_overflows([placed("a", 0, 1500), placed("b", 1000, 500)]))
    assert out["a"].overflow_ms == 500
    assert out["a"].overflow_next_id == "b"
    assert out["b"].overflow_ms == 0


def test_allow_overlap_still_reports_the_number() -> None:
    out = by_id(mark_overflows([placed("a", 0, 1500, allow=True), placed("b", 1000, 500)]))
    assert out["a"].overflow_ms == 500
    assert out["a"].allow_overlap is True


def test_orphaned_and_unmapped_and_takeless_are_ignored() -> None:
    items = [
        placed("a", 0, 5000),
        placed("o", 1000, 500, orphaned=True),
        placed("n", None, None),
        placed("t", 2000, None),
        placed("z", 6000, 500),
    ]
    out = by_id(mark_overflows(items))
    assert out["a"].overflow_ms == 0  # next playing line is z at 6000
    assert out["o"].overflow_ms == 0


def test_only_the_next_line_counts() -> None:
    out = by_id(
        mark_overflows([placed("a", 0, 3000), placed("b", 1000, 100), placed("c", 2000, 100)])
    )
    assert out["a"].overflow_next_id == "b"
    assert out["a"].overflow_ms == 2000


def test_input_is_not_changed() -> None:
    items = [placed("a", 0, 1500), placed("b", 1000, 500)]
    mark_overflows(items)
    assert items[0].overflow_ms == 0


def test_empty_list() -> None:
    assert mark_overflows([]) == []


def test_slack_is_the_gap_after_the_previous_playing_line() -> None:
    items = [placed("p", 0, 1000), placed("a", 3000, 2500), placed("b", 4000, 500)]
    out = by_id(mark_overflows(items))
    assert out["a"].overflow_ms == 1500
    assert out["a"].slack_ms == 2000


def test_slack_for_the_first_line_is_its_start() -> None:
    out = by_id(mark_overflows([placed("a", 400, 2000), placed("b", 1000, 500)]))
    assert out["a"].slack_ms == 400


def test_slack_is_zero_when_lines_touch() -> None:
    items = [placed("p", 0, 3000), placed("a", 3000, 2500), placed("b", 4000, 500)]
    assert by_id(mark_overflows(items))["a"].slack_ms == 0


def test_fit_stretch_clears_the_overflow() -> None:
    out = by_id(mark_overflows([placed("a", 0, 1500), placed("b", 1000, 500)]))
    assert out["a"].fit_stretch == 1.5  # 1500 / (1500 - 500)


def test_no_fit_stretch_without_overflow() -> None:
    out = by_id(mark_overflows([placed("a", 0, 1000), placed("b", 1000, 500)]))
    assert out["a"].fit_stretch is None
