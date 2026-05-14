from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import Prompt, PromptStats, TagSet
from .store import PromptStore
from .templating import find_variables
from .tokens import count_tokens


@dataclass(frozen=True)
class BrowserFilter:
    query: str | None = None
    tags: tuple[str, ...] = ()
    variable: str | None = None


class BrowserSort(StrEnum):
    NAME = "name"
    TOKENS = "tokens"
    USES = "uses"
    UPDATED = "updated"


@dataclass(frozen=True)
class PromptBrowserRow:
    prompt: Prompt
    show_count: int = 0
    edit_count: int = 0
    feedback_count: int = 0
    last_used_at: str | None = None
    token_count: int = 0
    variables: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.prompt.name

    @property
    def body(self) -> str:
        return self.prompt.body

    @property
    def tag_label(self) -> str:
        return " ".join(f"#{tag}" for tag in self.prompt.tags) or "-"

    @property
    def variable_label(self) -> str:
        return ", ".join(self.variables) or "-"

    @property
    def project_label(self) -> str:
        return self.prompt.project_name or "unbound"

    @property
    def last_used_label(self) -> str:
        return short_timestamp(self.last_used_at)


def short_timestamp(value: str | None) -> str:
    if value is None:
        return "-"
    return value[:16].replace("T", " ")


def preview_text(value: str, limit: int = 180) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "..."


def toggle_tag(tags: tuple[str, ...], tag: str) -> tuple[str, ...]:
    normalized = TagSet.from_values([tag]).names
    if not normalized:
        return tags
    name = normalized[0]
    if name in tags:
        return tuple(existing for existing in tags if existing != name)
    return (*tags, name)


def parse_tag_operations(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    add = [item[1:] for item in raw.split() if item.startswith("+") and len(item) > 1]
    remove = [item[1:] for item in raw.split() if item.startswith("-") and len(item) > 1]
    return TagSet.from_values(add).names, TagSet.from_values(remove).names


def build_browser_rows(
    store: PromptStore,
    browser_filter: BrowserFilter,
    *,
    project_id: int | None = None,
    project_filter: bool = False,
    sort: BrowserSort = BrowserSort.NAME,
) -> list[PromptBrowserRow]:
    prompts = store.list(
        tags=browser_filter.tags,
        query=browser_filter.query,
        project_id=project_id,
        project_filter=project_filter,
    )
    stats_by_name = {stats.name: stats for stats in store.stats(project_id=project_id, project_filter=project_filter)}
    rows = [row_from_prompt(prompt, stats_by_name.get(prompt.name)) for prompt in prompts]
    if browser_filter.variable:
        variable = browser_filter.variable.casefold()
        rows = [row for row in rows if any(variable in item.casefold() for item in row.variables)]
    return sort_browser_rows(rows, sort)


def sort_browser_rows(rows: list[PromptBrowserRow], sort: BrowserSort) -> list[PromptBrowserRow]:
    if sort == BrowserSort.TOKENS:
        return sorted(rows, key=lambda row: (-row.token_count, row.name.casefold()))
    if sort == BrowserSort.USES:
        return sorted(rows, key=lambda row: (-row.show_count, row.name.casefold()))
    if sort == BrowserSort.UPDATED:
        return sorted(rows, key=lambda row: (row.prompt.updated_at, row.name.casefold()), reverse=True)
    return sorted(rows, key=lambda row: row.name.casefold())


def row_from_prompt(prompt: Prompt, stats: PromptStats | None = None) -> PromptBrowserRow:
    return PromptBrowserRow(
        prompt=prompt,
        show_count=stats.show_count if stats else 0,
        edit_count=stats.edit_count if stats else 0,
        feedback_count=stats.feedback_count if stats else 0,
        last_used_at=stats.last_used_at if stats else None,
        token_count=count_tokens(prompt.body),
        variables=tuple(find_variables(prompt.body)),
    )
