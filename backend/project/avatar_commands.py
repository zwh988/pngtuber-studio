"""Avatar settings commands (M5-1). Pure: they change the in-memory project only."""

from backend.project.commands import Command, CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import AvatarSettings, Project


class SetAvatarArtFolder(Command):
    """Point the project at an avatar art folder (stored path) or clear it (None)."""

    def __init__(self, art_folder: str | None) -> None:
        self.art_folder = art_folder
        self._old: str | None = None
        self._applied = False

    @property
    def label(self) -> str:
        return "Clear avatar art" if self.art_folder is None else "Set avatar art"

    def apply(self, project: Project) -> None:
        if project.avatar.art_folder == self.art_folder:
            raise NoChange("the project already uses that art folder")
        try:
            AvatarSettings(art_folder=self.art_folder)
        except ValueError as exc:
            raise CommandError(f"invalid art folder path: {exc}") from exc
        self._old = project.avatar.art_folder
        project.avatar.art_folder = self.art_folder
        self._applied = True

    def revert(self, project: Project) -> None:
        if not self._applied:
            raise CommandError("nothing to restore: command was not applied")
        project.avatar.art_folder = self._old
