"""Export defaults saved back to the project (M7 S5, decision 4). Pure.

``SetExportSettings`` changes any of the project's ``ExportSettings`` fields in one
undo step (rule 11). The export screen starts from these values. Vertical and 4K
output are out of scope for v1, so the height is 720 or 1080.
"""

import math

from backend.project.commands import Command, CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import Project

EXPORT_HEIGHTS: tuple[int, ...] = (720, 1080)
FPS_MIN, FPS_MAX = 1.0, 120.0
_FLAGS = ("include_avatar_overlay", "include_raw_video_link", "unload_tts_before_export")


def check_fps(value: object) -> str | float:
    if value == "match":
        return "match"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError('the frame rate must be "match" or a number')
    fps = float(value)
    if not (math.isfinite(fps) and FPS_MIN <= fps <= FPS_MAX):
        raise CommandError(f"the frame rate must be between {FPS_MIN:g} and {FPS_MAX:g}")
    return round(fps, 3)


class SetExportSettings(Command):
    """Change export defaults (None keeps a field)."""

    def __init__(
        self,
        *,
        height: int | None = None,
        fps: str | float | None = None,
        include_avatar_overlay: bool | None = None,
        include_raw_video_link: bool | None = None,
        unload_tts_before_export: bool | None = None,
    ) -> None:
        self.changes: dict[str, object] = {}
        if height is not None:
            if isinstance(height, bool) or height not in EXPORT_HEIGHTS:
                heights = " or ".join(str(h) for h in EXPORT_HEIGHTS)
                raise CommandError(f"the export height must be {heights}")
            self.changes["height"] = int(height)
        if fps is not None:
            self.changes["fps"] = check_fps(fps)
        flags = {
            "include_avatar_overlay": include_avatar_overlay,
            "include_raw_video_link": include_raw_video_link,
            "unload_tts_before_export": unload_tts_before_export,
        }
        for name in _FLAGS:
            value = flags[name]
            if value is None:
                continue
            if not isinstance(value, bool):
                raise CommandError(f"{name} must be true or false")
            self.changes[name] = value
        self._old: dict[str, object] | None = None

    @property
    def label(self) -> str:
        return "Change export defaults"

    def apply(self, project: Project) -> None:
        settings = project.export
        old = {name: getattr(settings, name) for name in self.changes}
        if old == self.changes:
            raise NoChange("the export defaults are already set that way")
        for name, value in self.changes.items():
            setattr(settings, name, value)
        self._old = old

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        for name, value in self._old.items():
            setattr(project.export, name, value)
