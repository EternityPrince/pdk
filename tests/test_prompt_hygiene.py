from __future__ import annotations

from datetime import UTC, datetime

from pdk.models import Prompt, PromptStats
from pdk.prompt_hygiene import duplicate_groups, normalized_body, parse_timestamp, stale_prompts


def prompt(name: str, body: str, updated_at: str = "2026-01-01T00:00:00+00:00") -> Prompt:
    return Prompt(
        name=name,
        body=body,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at=updated_at,
    )


def stats(name: str, last_used_at: str | None) -> PromptStats:
    return PromptStats(
        name=name,
        show_count=1 if last_used_at else 0,
        edit_count=0,
        feedback_count=0,
        last_used_at=last_used_at,
    )


def test_duplicate_groups_fold_whitespace_and_case():
    groups = duplicate_groups(
        [
            prompt("b", " Same\nbody "),
            prompt("a", "same body"),
            prompt("fresh", "different"),
        ]
    )

    assert normalized_body(" Same\nbody ") == "same body"
    assert [[item.name for item in group] for group in groups] == [["a", "b"]]


def test_parse_timestamp_normalizes_naive_datetimes_to_utc():
    assert parse_timestamp("not a date") is None
    parsed = parse_timestamp("2026-01-01T00:00:00")
    assert parsed is not None
    assert parsed.tzinfo == UTC


def test_stale_prompts_prefers_last_use_then_updated_time():
    prompts = [
        prompt("never-used-old", "body", updated_at="2026-01-01T00:00:00+00:00"),
        prompt("used-old", "body 2", updated_at="2026-02-01T00:00:00+00:00"),
        prompt("fresh", "body 3", updated_at="2026-05-08T00:00:00+00:00"),
    ]
    stats_by_name = {
        "used-old": stats("used-old", "2026-01-02T00:00:00+00:00"),
        "fresh": stats("fresh", "2026-05-08T12:00:00+00:00"),
    }

    stale = stale_prompts(
        prompts,
        stats_by_name,
        days=30,
        now=datetime(2026, 5, 9, tzinfo=UTC),
    )

    assert [item.name for item in stale] == ["never-used-old", "used-old"]
