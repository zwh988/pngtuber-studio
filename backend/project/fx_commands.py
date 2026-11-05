"""Voice chain commands (M4-1, S3c). Pure: they mutate the in-memory Project only.

Follow the command contract in ``commands.py``. A command that would change
nothing raises ``NoChange`` so batch callers can skip it without an empty undo step.
``SetFxChain`` replaces the whole chain in one command; the UI commits one edit per
slider release (or after a short rest), not one per tick.
"""

from backend.audio.chainspec import FxChainError, validate_chain
from backend.audio.gamemix import clean_game_audio_db
from backend.project.commands import Command, CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import FxChain, Project


class SetFxChain(Command):
    def __init__(self, chain: FxChain) -> None:
        self.chain = chain.model_copy(deep=True)  # later edits never alias the command
        self._old: FxChain | None = None

    @property
    def label(self) -> str:
        return "Set voice chain"

    def apply(self, project: Project) -> None:
        try:
            validate_chain(self.chain)
        except FxChainError as exc:
            raise CommandError(str(exc)) from exc
        if project.fx_chain == self.chain:
            raise NoChange("the voice chain is already set to this")
        self._old = project.fx_chain.model_copy(deep=True)
        project.fx_chain = self.chain.model_copy(deep=True)

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        project.fx_chain = self._old.model_copy(deep=True)


class SetGameAudioDb(Command):
    def __init__(self, db: float) -> None:
        try:
            self.db = clean_game_audio_db(db)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self._old: float | None = None

    @property
    def label(self) -> str:
        return "Set game audio level"

    def apply(self, project: Project) -> None:
        if project.game_audio_db == self.db:
            raise NoChange(f"the game audio level is already {self.db} dB")
        self._old = project.game_audio_db
        project.game_audio_db = self.db

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        project.game_audio_db = self._old
