from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .models import Prompt, PromptStats


def normalized_body(value: str) -> str:
    return " ".join(value.split()).casefold()


def duplicate_groups(prompts: list[Prompt]) -> list[list[Prompt]]:
    groups: dict[str, list[Prompt]] = defaultdict(list)
    for prompt in prompts:
        key = normalized_body(prompt.body)
        if key:
            groups[key].append(prompt)
    return [sorted(group, key=lambda prompt: prompt.name.casefold()) for group in groups.values() if len(group) > 1]


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def is_stale(prompt: Prompt, stats: PromptStats | None, *, cutoff: datetime) -> bool:
    last_used = parse_timestamp(stats.last_used_at if stats else None)
    updated = parse_timestamp(prompt.updated_at)
    if last_used is not None:
        return last_used < cutoff
    return updated is not None and updated < cutoff


def stale_prompts(
    prompts: list[Prompt],
    stats_by_name: dict[str, PromptStats],
    *,
    days: int,
    now: datetime | None = None,
) -> list[Prompt]:
    timestamp = (now or datetime.now(UTC)).replace(microsecond=0)
    cutoff = timestamp - timedelta(days=days)
    stale = [prompt for prompt in prompts if is_stale(prompt, stats_by_name.get(prompt.name), cutoff=cutoff)]
    return sorted(
        stale,
        key=lambda prompt: (
            (stats_by_name.get(prompt.name).last_used_at if stats_by_name.get(prompt.name) else None)
            or prompt.updated_at
        ),
    )
