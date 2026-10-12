"""Pure summaries of a project for the project screen (M1-6)."""

from pydantic import BaseModel, Field

from backend.project.schema import Project, Source

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
    # Set when the last automatic save failed; None when saving works.
    save_error: str | None = None
    # Broken references found by check_references (0 when the project is sound).
    problem_count: int = 0


class FootageItem(BaseModel):
    id: str
    path: str
    external: bool
    exists: bool
    width: int
    height: int
    fps: float
    duration_ms: int
    audio_tracks: int


class FootageReport(BaseModel):
    items: list[FootageItem] = Field(default_factory=list)
    added: int = 0
    errors: list[str] = Field(default_factory=list)


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


def describe_source(source: Source, exists: bool) -> FootageItem:
    return FootageItem(
        id=source.id,
        path=source.path,
        external=source.external,
        exists=exists,
        width=source.width,
        height=source.height,
        fps=source.fps,
        duration_ms=source.duration_ms,
        audio_tracks=source.audio_tracks,
    )
