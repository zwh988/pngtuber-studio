"""Session.project_key and the stale-project guard used by the job queue (M3-3)."""

from pathlib import Path

import numpy as np
import pytest

from backend.project.session import Session, SessionError
from backend.voice.takes import NewTake


def make_new_take() -> NewTake:
    return NewTake(
        line_id="a" * 12,
        seed=1,
        text="Hello there.",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="b" * 12,
        model_version="m1",
        raw_key="c" * 64,
    )


def test_no_key_without_a_project() -> None:
    assert Session().project_key() is None


def test_the_key_is_the_project_folder(tmp_path: Path) -> None:
    session = Session()
    session.new_project(str(tmp_path), "Rack")
    assert session.project_key() == str(tmp_path / "Rack")


def test_a_stale_key_is_refused(tmp_path: Path) -> None:
    session = Session()
    session.new_project(str(tmp_path), "Rack")
    stale = str(tmp_path / "Other")
    with pytest.raises(SessionError, match="changed"):
        session.plan_generation("a" * 12, model_version="m1", project_key=stale)
    with pytest.raises(SessionError, match="changed"):
        session.reuse_take(make_new_take(), project_key=stale)
    with pytest.raises(SessionError, match="changed"):
        session.add_take(
            make_new_take(), np.zeros(240, dtype=np.float32), 24000, project_key=stale
        )


def test_a_key_for_a_closed_project_is_refused() -> None:
    session = Session()
    with pytest.raises(SessionError, match="changed"):
        session.reuse_take(make_new_take(), project_key="C:/gone")
