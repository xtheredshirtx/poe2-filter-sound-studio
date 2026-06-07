"""Typed exception hierarchy for the Economy Tier feature.

User-facing messages are carried on the exception so the UI can surface them
distinctly from internal tracebacks (A.8). Every exception this feature raises
on purpose derives from :class:`EconomyTierError`, so callers can catch the
whole family with one ``except`` and keep the rest of the app alive.
"""

from __future__ import annotations


class EconomyTierError(Exception):
    """Base class for every error raised by the Economy Tier feature."""


class TierDataError(EconomyTierError):
    """The economy tier data file is missing, unreadable, or schema-invalid."""


class TemplateError(EconomyTierError):
    """A visual template is missing, malformed, or emits invalid directives."""


class BackupError(EconomyTierError):
    """A backup could not be created or verified; the save must not proceed."""


class ValidationError(EconomyTierError):
    """Post-edit validation or the structural-diff guard rejected a change."""


class FileChangedError(EconomyTierError):
    """The source file changed on disk since it was loaded; abort and re-load."""


__all__ = [
    "EconomyTierError",
    "TierDataError",
    "TemplateError",
    "BackupError",
    "ValidationError",
    "FileChangedError",
]
