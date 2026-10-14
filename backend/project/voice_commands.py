"""Voice profile commands (M3-1). Pure: they mutate the in-memory Project only.

The reference clip file is copied into the project by ``Session`` before the
command runs; undo only changes which file the profile points at (the copy
stays on disk, which is harmless and keeps rule 1's spirit).
"""

from backend.project.commands import Command, CommandError
from backend.project.schema import Project, VoiceProfile, _check_relative_posix, new_id
from backend.voice.profile import VOICE_DIR


def _find_profile(project: Project, profile_id: str) -> VoiceProfile:
    for profile in project.voice_profiles:
        if profile.id == profile_id:
            return profile
    raise CommandError(f"unknown voice profile id {profile_id!r}")


class AddVoiceProfile(Command):
    def __init__(self, name: str, profile_id: str | None = None) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise CommandError("voice profile name must not be empty")
        self.profile = VoiceProfile(id=profile_id or new_id(), name=cleaned)

    @property
    def profile_id(self) -> str:
        return self.profile.id

    @property
    def label(self) -> str:
        return "Add voice profile"

    def apply(self, project: Project) -> None:
        if any(p.id == self.profile.id for p in project.voice_profiles):
            raise CommandError(f"voice profile id {self.profile.id!r} already exists")
        project.voice_profiles.append(self.profile.model_copy(deep=True))

    def revert(self, project: Project) -> None:
        profile = _find_profile(project, self.profile.id)
        project.voice_profiles.remove(profile)


class SetReferenceClip(Command):
    """Make ``path`` (inside ``media/voice/``) the profile's only reference clip."""

    def __init__(self, profile_id: str, path: str) -> None:
        try:
            _check_relative_posix(path)
        except ValueError as exc:
            raise CommandError(f"invalid reference path {path!r}: {exc}") from exc
        if not path.startswith(f"{VOICE_DIR}/"):
            raise CommandError(f"reference clips must live in {VOICE_DIR}/")
        self.profile_id = profile_id
        self.path = path
        self._old: list[str] | None = None

    @property
    def label(self) -> str:
        return "Set voice reference"

    def apply(self, project: Project) -> None:
        profile = _find_profile(project, self.profile_id)
        if profile.reference_clips == [self.path]:
            raise CommandError("that is already the reference clip")
        self._old = list(profile.reference_clips)
        profile.reference_clips = [self.path]

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        profile = _find_profile(project, self.profile_id)
        profile.reference_clips = list(self._old)
