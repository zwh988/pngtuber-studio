"""Pure summary of a project for the project screen (M1-6)."""

from pydantic import BaseModel

from backend.project.schema import Project

NOT_CONFIGURED = "not configured"
PATH_SET = "path set"


class ProjectSummary(BaseModel):
    name: str
    folder: str
    schema_version: int
    source_count: int
    clip_count: int
    voice_status: str
    avatar_status: str


def voice_status(project: Project) -> str:
    """Simple status text; real validation arrives with M3-1."""
    if any(profile.reference_clips for profile in project.voice_profiles):
        return PATH_SET
    return NOT_CONFIGURED


def avatar_status(project: Project) -> str:
    """Simple status text; real validation arrives with M5-1."""
    return NOT_CONFIGURED if project.avatar.art_folder is None else PATH_SET


def summarize(folder: str, project: Project) -> ProjectSummary:
    return ProjectSummary(
        name=project.name,
        folder=folder,
        schema_version=project.schema_version,
        source_count=len(project.sources),
        clip_count=len(project.clips),
        voice_status=voice_status(project),
        avatar_status=avatar_status(project),
    )
