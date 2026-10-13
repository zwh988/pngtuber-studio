import pytest

from backend.voice.overflow import (
    Overflow,
    PlacedLine,
    available_slack_ms,
    find_overflows,
)


def line(pid: str, start: int, duration: int, allow: bool = False) -> PlacedLine:
    return PlacedLine(placement_id=pid, start_ms=start, duration_ms=duration, allow_overlap=allow)


def test_no_items_or_one_item():
    assert find_overflows([]) == []
    assert find_overflows([line("a", 0, 5000)]) == []


def test_no_overflow_when_lines_fit_or_touch():
    assert find_overflows([line("a", 0, 1000), line("b", 1000, 500)]) == []
    assert find_overflows([line("a", 0, 1000), line("b", 2000, 500)]) == []


def test_overflow_amount_and_pair():
    result = find_overflows([line("a", 0, 1500), line("b", 1000, 500)])
    assert result == [Overflow("a", "b", 500, False)]


def test_input_order_does_not_matter():
    result = find_overflows([line("b", 1000, 500), line("a", 0, 1500)])
    assert result == [Overflow("a", "b", 500, False)]


def test_only_the_next_placement_counts():
    items = [line("a", 0, 5000), line("b", 1000, 500), line("c", 2000, 500)]
    assert find_overflows(items) == [Overflow("a", "b", 4000, False)]


def test_chain_of_overflows():
    items = [line("a", 0, 1200), line("b", 1000, 1200), line("c", 2000, 500)]
    assert find_overflows(items) == [Overflow("a", "b", 200, False), Overflow("b", "c", 200, False)]


def test_allow_overlap_is_flagged_not_dropped():
    result = find_overflows([line("a", 0, 1500, allow=True), line("b", 1000, 500)])
    assert result == [Overflow("a", "b", 500, True)]


def test_allow_overlap_belongs_to_the_overflowing_line():
    result = find_overflows([line("a", 0, 1500), line("b", 1000, 500, allow=True)])
    assert result == [Overflow("a", "b", 500, False)]


def test_same_start_is_ordered_by_id():
    result = find_overflows([line("b", 1000, 400), line("a", 1000, 400)])
    assert result == [Overflow("a", "b", 400, False)]


def test_validation():
    with pytest.raises(ValueError, match="duplicate"):
        find_overflows([line("a", 0, 10), line("a", 100, 10)])
    with pytest.raises(ValueError, match="negative"):
        find_overflows([line("a", -1, 10)])
    with pytest.raises(ValueError, match="negative"):
        find_overflows([line("a", 0, -10)])


def test_slack_first_line_can_move_to_zero():
    assert available_slack_ms([line("a", 800, 500)], "a") == 800


def test_slack_is_the_gap_after_the_previous_line():
    items = [line("a", 0, 1000), line("b", 1600, 500)]
    assert available_slack_ms(items, "b") == 600


def test_slack_is_zero_when_overlapping_or_touching():
    assert available_slack_ms([line("a", 0, 1500), line("b", 1000, 500)], "b") == 0
    assert available_slack_ms([line("a", 0, 1000), line("b", 1000, 500)], "b") == 0


def test_slack_unknown_id():
    with pytest.raises(ValueError, match="unknown"):
        available_slack_ms([line("a", 0, 10)], "zzz")
