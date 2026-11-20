"""Schema migrations for ``project.json``. Pure: dict in, dict out, no I/O.

Every schema change bumps ``SCHEMA_VERSION`` and registers a function here that
upgrades a project dict from version N to N+1 (CLAUDE.md rule 6).
"""

import copy
from collections.abc import Callable, Mapping
from typing import Any

from backend.project.schema import SCHEMA_VERSION, new_id

Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v2 adds ``Placement.stretch`` (default 1.0: the take plays as recorded)."""
    for placement in data.get("placements", []):
        if isinstance(placement, dict):
            placement.setdefault("stretch", 1.0)
    return data


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """v3 adds the manual take trim ``Take.trim_start_ms`` / ``trim_end_ms`` (no cut)."""
    for take in data.get("takes", []):
        if isinstance(take, dict):
            take.setdefault("trim_start_ms", None)
            take.setdefault("trim_end_ms", None)
    return data


AVATAR_V4_DEFAULTS: dict[str, float] = {
    "bounce": 1.0,
    "float_amp": 1.0,
    "float_speed": 1.0,
    "float_angle_deg": 0.0,
    "blink_rate": 1.0,
    "mouth_sensitivity": 1.0,
}


def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """v4 adds the avatar's base motion settings (bounce, float, blink, mouth)."""
    avatar = data.get("avatar")
    if isinstance(avatar, dict):
        for name, value in AVATAR_V4_DEFAULTS.items():
            avatar.setdefault(name, value)
    return data


def _v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    """v5 adds audio files, audio lanes (one empty "Audio 1") and audio clips (M8-1)."""
    data.setdefault("audio_files", [])
    data.setdefault(
        "audio_lanes",
        [{"id": new_id(), "name": "Audio 1", "gain_db": 0.0, "mute": False, "solo": False}],
    )
    data.setdefault("audio_clips", [])
    return data


def _v5_to_v6(data: dict[str, Any]) -> dict[str, Any]:
    """v6 adds video lanes, their clips and imported images (M8-2), all empty."""
    data.setdefault("image_files", [])
    data.setdefault("video_lanes", [])
    data.setdefault("lane_clips", [])
    return data


# Maps "from version" -> function upgrading that version to version + 1.
MIGRATIONS: dict[int, Migration] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
}


class MigrationError(Exception):
    """The project data cannot be migrated."""


class ProjectTooNewError(MigrationError):
    """The project was saved by a newer version of the app."""


def migrate(
    data: Mapping[str, Any],
    target: int = SCHEMA_VERSION,
    migrations: Mapping[int, Migration] | None = None,
) -> dict[str, Any]:
    """Return a copy of ``data`` upgraded to ``target``, running steps in order.

    ``schema_version`` is set by this function after each step; migrations
    need not touch it. The input is never mutated.
    """
    registry = MIGRATIONS if migrations is None else migrations
    result = copy.deepcopy(dict(data))

    version = result.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MigrationError(f"invalid schema_version: {version!r}")
    if version > target:
        raise ProjectTooNewError(
            f"this project was saved by a newer version of PNGtuber Studio (schema "
            f"version {version}, this app reads up to {target}). Update the app to "
            "open it; the project was not changed."
        )

    while version < target:
        step = registry.get(version)
        if step is None:
            raise MigrationError(f"no migration registered from version {version}")
        result = step(result)
        version += 1
        result["schema_version"] = version
    return result
