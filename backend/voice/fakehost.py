"""In-memory stand-in for the open project, for queue and endpoint tests (M3-3).

It follows the ``GenerationHost`` contract of ``jobqueue.py`` without a project
folder: lines are text pieces in ``lines``, takes are kept in memory, the raw key
is a hash of line, text, seed and model version. The first generation uses seed
1000, a reroll the lowest unused ``1000 + k`` (the real seed policy's shape).
"""

import hashlib
from datetime import UTC, datetime

import numpy as np

from backend.project.session import SessionError
from backend.voice.generation import GenerationPlan
from backend.voice.takes import AddTakeResult, NewTake, TakeItem

BASE_SEED = 1000


class FakeHost:
    def __init__(self, lines: dict[str, tuple[str, ...]] | None = None) -> None:
        self.project = "project-1"
        self.lines: dict[str, tuple[str, ...]] = (
            lines if lines is not None else {"short": ("Hello there.",)}
        )
        self.takes: list[NewTake] = []
        self.saved: list[tuple[NewTake, np.ndarray, int]] = []

    def project_key(self) -> str | None:
        return self.project

    def plan_generation(
        self,
        line_id: str,
        *,
        model_version: str,
        reroll: bool = False,
        project_key: str | None = None,
    ) -> GenerationPlan:
        self._check(project_key)
        chunks = self.lines.get(line_id)
        if chunks is None:
            raise SessionError(f"unknown line id {line_id!r}")
        seed = BASE_SEED
        if reroll:
            used = {take.seed for take in self.takes if take.line_id == line_id}
            while seed in used:
                seed += 1
        text = " ".join(chunks)
        key = hashlib.sha256(
            f"{line_id}|{text}|{seed}|{model_version}".encode()
        ).hexdigest()
        new = NewTake(
            line_id=line_id,
            seed=seed,
            text=text,
            exaggeration=0.5,
            cfg_weight=0.5,
            voice_profile_id="v" * 12,
            model_version=model_version,
            raw_key=key,
        )
        return GenerationPlan(
            new_take=new,
            chunks=chunks,
            reference_path="C:/Projects/Rack/media/voice/ref.wav",
            reroll=reroll,
        )

    def reuse_take(
        self,
        new: NewTake,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult | None:
        self._check(project_key)
        for take in self.takes:
            if take.raw_key == new.raw_key:
                return self._result(take, reused=True)
        return None

    def add_take(
        self,
        new: NewTake,
        samples: np.ndarray,
        sample_rate: int,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult:
        self._check(project_key)
        self.takes.append(new)
        self.saved.append((new, samples, sample_rate))
        return self._result(new, reused=False)

    def _check(self, project_key: str | None) -> None:
        if project_key is not None and project_key != self.project:
            raise SessionError("the open project changed since this job was requested")

    @staticmethod
    def _result(take: NewTake, *, reused: bool) -> AddTakeResult:
        take_id = "t" + take.raw_key[:11]
        item = TakeItem(
            id=take_id,
            line_id=take.line_id,
            seed=take.seed,
            text=take.text,
            exaggeration=take.exaggeration,
            cfg_weight=take.cfg_weight,
            duration_ms=1000,
            starred=False,
            active=True,
            created=datetime.now(UTC),
            raw_file=f"media/takes_raw/{take_id}.wav",
            file_exists=True,
        )
        return AddTakeResult(take=item, reused=reused)
