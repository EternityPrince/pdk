from __future__ import annotations

from pdk.privacy import PrivateFinding
from pdk.text_analysis import (
    chunk_text,
    digest_tags,
    extractive_summary,
    finding_types,
    line_count,
    word_count,
)


def private_finding(name: str, text: str = "value") -> PrivateFinding:
    return PrivateFinding(
        name=name,
        label=name,
        start=0,
        end=len(text),
        text=text,
        score=1.0,
        detector="test",
    )


def test_text_metrics_handle_empty_and_unicode_text():
    assert line_count("") == 0
    assert line_count("one\nдва\n") == 2
    assert word_count("one два, три") == 3


def test_chunk_text_keeps_empty_input_representable():
    chunks = chunk_text("")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.text == ""
    assert chunk.char_start == 0
    assert chunk.char_end == 0
    assert chunk.token_count == 0


def test_extractive_summary_collapses_whitespace_and_truncates():
    assert extractive_summary("  one\n\n  two  ") == "one two"
    assert extractive_summary("abcdef", max_chars=4) == "abc..."


def test_finding_types_and_digest_tags_are_stable_and_deduplicated():
    findings = [private_finding("email"), private_finding("ru_phone"), private_finding("email")]

    assert finding_types(findings) == "email, ru_phone"
    assert digest_tags("Паспорт и договор", findings) == [
        "contract",
        "identity",
        "email",
        "ru_phone",
    ]
