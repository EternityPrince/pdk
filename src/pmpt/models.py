from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PromptName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PromptBody = str
TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
IsoTimestamp = str


class UsageAction(StrEnum):
    ADD = "add"
    BROWSE = "browse"
    EDIT = "edit"
    FEEDBACK = "feedback"
    REPLACE = "replace"
    SHOW = "show"
    TAG = "tag"
    VERSIONS = "versions"


class VersionReason(StrEnum):
    EDIT = "edit"
    REPLACE = "replace"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class Prompt(FrozenModel):
    name: PromptName
    body: PromptBody
    created_at: IsoTimestamp
    updated_at: IsoTimestamp
    project_id: int | None = None
    project_name: str | None = None
    tags: tuple[str, ...] = ()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Iterable[str] | None) -> tuple[str, ...]:
        return TagSet.from_values(value or ()).names


class PromptDraft(FrozenModel):
    name: PromptName
    body: PromptBody
    replace: bool = False
    project_id: int | None = None
    tags: tuple[str, ...] = ()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Iterable[str] | None) -> tuple[str, ...]:
        return TagSet.from_values(value or ()).names


class PromptSearch(FrozenModel):
    tags: tuple[str, ...] = ()
    query: str | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Iterable[str] | None) -> tuple[str, ...]:
        return TagSet.from_values(value or ()).names


class TagSet(FrozenModel):
    names: tuple[str, ...] = ()

    @classmethod
    def from_values(cls, values: Iterable[str]) -> TagSet:
        seen: set[str] = set()
        names: list[str] = []
        for value in values:
            for part in str(value).split(","):
                normalized = part.strip().lower()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    names.append(normalized)
        return cls(names=tuple(names))


class TagSummary(FrozenModel):
    name: str
    prompt_count: int = Field(ge=0)


class Project(FrozenModel):
    id: int = Field(ge=1)
    name: ProjectName
    description: str = ""
    created_at: IsoTimestamp
    updated_at: IsoTimestamp


class ProjectDraft(FrozenModel):
    name: ProjectName
    description: str = ""


class Note(FrozenModel):
    id: int = Field(ge=1)
    project_id: int | None = None
    project_name: str | None = None
    title: str | None = None
    body: str
    created_at: IsoTimestamp
    updated_at: IsoTimestamp


class NoteDraft(FrozenModel):
    project_id: int | None = None
    title: str | None = None
    body: str


class NoteVersion(FrozenModel):
    id: int = Field(ge=1)
    note_id: int = Field(ge=1)
    title: str | None = None
    body: str
    created_at: IsoTimestamp


class PromptStats(FrozenModel):
    name: str
    show_count: int = Field(ge=0)
    edit_count: int = Field(ge=0)
    feedback_count: int = Field(ge=0)
    last_used_at: str | None


class PromptVersion(FrozenModel):
    id: int = Field(ge=1)
    prompt_name: str
    body: PromptBody
    created_at: IsoTimestamp
    reason: VersionReason


class Feedback(FrozenModel):
    id: int = Field(ge=1)
    prompt_name: str
    body: str
    created_at: IsoTimestamp


class UsageEvent(FrozenModel):
    id: int = Field(ge=1)
    action: UsageAction
    used_at: IsoTimestamp
    detail: str | None
    prompt_names: tuple[str, ...] = ()
