"""Autosave timing logic. Pure: the caller passes ``now`` (seconds); no clock,
threads, or I/O here. A scheduler (added with the backend API) asks
``seconds_until_due`` how long to sleep and calls the store when ``should_save``.

Policy: save once edits have been quiet for ``debounce_s``, but never let
unsaved changes wait longer than ``max_wait_s`` during continuous editing.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AutosavePolicy:
    debounce_s: float = 2.0
    max_wait_s: float = 15.0


class AutosaveTracker:
    def __init__(self, policy: AutosavePolicy | None = None) -> None:
        self._policy = policy or AutosavePolicy()
        self._revision = 0
        self._saved_revision = 0
        self._first_change: float | None = None
        self._last_change: float | None = None

    @property
    def dirty(self) -> bool:
        return self._revision != self._saved_revision

    def mark_dirty(self, now: float) -> None:
        """Record a change at time ``now``."""
        self._revision += 1
        if self._first_change is None:
            self._first_change = now
        self._last_change = now

    def begin_save(self) -> int:
        """Call right before saving; pass the returned token to ``finish_save``."""
        return self._revision

    def finish_save(self, token: int) -> None:
        """Call after a *successful* save. Changes made while saving stay dirty.

        If the save failed, do not call this: the project stays dirty.
        """
        self._saved_revision = token
        if self._saved_revision == self._revision:
            self._first_change = None
            self._last_change = None
        else:
            # Changes arrived during the save; their wait starts from the latest.
            self._first_change = self._last_change

    def due_at(self) -> float | None:
        """Time at which a save becomes due, or None if nothing is dirty."""
        if not self.dirty or self._first_change is None or self._last_change is None:
            return None
        return min(
            self._last_change + self._policy.debounce_s,
            self._first_change + self._policy.max_wait_s,
        )

    def should_save(self, now: float) -> bool:
        due = self.due_at()
        return due is not None and now >= due

    def seconds_until_due(self, now: float) -> float | None:
        due = self.due_at()
        return None if due is None else max(0.0, due - now)
