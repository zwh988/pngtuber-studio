"""Schema migrations for ``project.json``. Pure: dict in, dict out, no I/O.

Every schema change bumps ``SCHEMA_VERSION`` and registers a function here that
upgrades a project dict from version N to N+1 (CLAUDE.md rule 6).
"""

import copy
from collections.abc import Callable, Mapping
from typing import Any

from backend.project.schema import SCHEMA_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Maps "from version" -> function upgrading that version to version + 1.
# Empty while the schema is at v1. Example for a future v2:
#     MIGRATIONS[1] = _v1_to_v2
MIGRATIONS: dict[int, Migration] = {}


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
            f"project schema version {version} is newer than supported ({target})"
        )

    while version < target:
        step = registry.get(version)
        if step is None:
            raise MigrationError(f"no migration registered from version {version}")
        result = step(result)
        version += 1
        result["schema_version"] = version
    return result
