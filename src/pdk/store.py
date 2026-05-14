from __future__ import annotations

from .store_base import (
    NamedProjectNotFoundError,
    NoteNotFoundError,
    ProjectExistsError,
    PromptExistsError,
    PromptNotFoundError,
    PromptStoreBase,
)
from .store_history import HistoryStoreMixin
from .store_notes import NoteStoreMixin
from .store_projects import ProjectStoreMixin
from .store_prompts import PromptStoreMixin
from .store_tags import TagStatsStoreMixin

__all__ = [
    "NamedProjectNotFoundError",
    "NoteNotFoundError",
    "ProjectExistsError",
    "PromptExistsError",
    "PromptNotFoundError",
    "PromptStore",
]


class PromptStore(
    ProjectStoreMixin,
    PromptStoreMixin,
    TagStatsStoreMixin,
    HistoryStoreMixin,
    NoteStoreMixin,
    PromptStoreBase,
):
    pass
