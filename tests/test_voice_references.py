"""check_voice_references: links between lines, takes and placements (M3-4)."""

from backend.edl.anchoring import check_references, check_voice_references
from backend.project.schema import Anchor, Line, Placement, Project, Take

L1 = "aaaaaaaaaaaa"
L2 = "bbbbbbbbbbbb"
T1 = "111111111111"
T2 = "222222222222"
P1 = "444444444444"
CLIP = "555555555555"


def make_take(take_id: str, line_id: str) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="x",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="666666666666",
        model_version="m",
        raw_key="0" * 64,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=1,
    )


def placement(line_id: str = L1, override: str | None = None) -> Placement:
    return Placement(
        id=P1,
        line_id=line_id,
        anchor=Anchor(clip_id=CLIP, source_ms=0),
        take_override_id=override,
    )


def kinds(project: Project) -> list[str]:
    return [problem.kind for problem in check_voice_references(project)]


def test_a_consistent_voice_project_has_no_problems() -> None:
    project = Project(
        name="Rack",
        lines=[Line(id=L1, active_take_id=T1)],
        takes=[make_take(T1, L1)],
        placements=[placement(L1, override=T1)],
    )
    assert kinds(project) == []


def test_empty_project_has_no_problems() -> None:
    assert check_voice_references(Project(name="Rack")) == []


def test_take_of_a_missing_line() -> None:
    project = Project(name="Rack", takes=[make_take(T1, L1)])
    [problem] = check_voice_references(project)
    assert (problem.kind, problem.owner_id, problem.missing_id) == (
        "take_missing_line",
        T1,
        L1,
    )


def test_active_take_that_does_not_exist() -> None:
    project = Project(name="Rack", lines=[Line(id=L1, active_take_id=T1)])
    [problem] = check_voice_references(project)
    assert (problem.kind, problem.owner_id, problem.missing_id) == (
        "line_missing_take",
        L1,
        T1,
    )


def test_active_take_that_belongs_to_another_line() -> None:
    project = Project(
        name="Rack",
        lines=[Line(id=L1, active_take_id=T2), Line(id=L2)],
        takes=[make_take(T2, L2)],
    )
    assert kinds(project) == ["line_missing_take"]


def test_placement_of_a_missing_line() -> None:
    project = Project(name="Rack", placements=[placement(L1)])
    assert kinds(project) == ["placement_missing_line"]


def test_placement_override_that_does_not_exist_or_is_another_lines() -> None:
    missing = Project(name="Rack", lines=[Line(id=L1)], placements=[placement(L1, T1)])
    assert kinds(missing) == ["placement_missing_take"]
    other = Project(
        name="Rack",
        lines=[Line(id=L1), Line(id=L2)],
        takes=[make_take(T1, L2)],
        placements=[placement(L1, T1)],
    )
    assert kinds(other) == ["placement_missing_take"]


def test_the_m2_check_does_not_look_at_lines_and_takes() -> None:
    project = Project(name="Rack", placements=[placement(L1)])
    assert [p.kind for p in check_references(project)] == ["item_missing_clip"]


def test_check_voice_references_never_changes_the_project() -> None:
    project = Project(name="Rack", lines=[Line(id=L1, active_take_id=T1)])
    before = project.model_dump()
    check_voice_references(project)
    assert project.model_dump() == before
