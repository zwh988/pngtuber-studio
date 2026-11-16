"""Errors shared by the export steps (M6)."""


class ExportError(Exception):
    """The export cannot go on; the message is for the user."""


class ExportCancelled(ExportError):
    """The user cancelled the export."""
