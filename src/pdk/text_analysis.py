from __future__ import annotations

from collections.abc import Iterable
import re

from .file_index import ChunkDraft
from .privacy import PrivateFinding
from .tokens import count_tokens

DEFAULT_CHUNK_TOKENS = 1200


def line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def finding_types(findings: Iterable[PrivateFinding]) -> str:
    labels = sorted({finding.name for finding in findings})
    return ", ".join(labels) if labels else "-"


def chunk_text(text: str, *, target_tokens: int = DEFAULT_CHUNK_TOKENS) -> list[ChunkDraft]:
    if not text:
        return [ChunkDraft(0, "", 0, 0, 0)]

    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[ChunkDraft] = []
    current: list[str] = []
    current_start: int | None = None
    position = 0
    for part in paragraphs:
        if not part:
            continue
        start = position
        position += len(part)
        candidate = "".join([*current, part])
        if current and count_tokens(candidate) > target_tokens:
            chunk_body = "".join(current).strip()
            chunks.append(
                ChunkDraft(
                    len(chunks),
                    chunk_body,
                    current_start or 0,
                    start,
                    count_tokens(chunk_body),
                )
            )
            current = [part]
            current_start = start
        else:
            if current_start is None and part.strip():
                current_start = start
            current.append(part)

    if current:
        chunk_body = "".join(current).strip()
        chunks.append(
            ChunkDraft(
                len(chunks),
                chunk_body,
                current_start or 0,
                len(text),
                count_tokens(chunk_body),
            )
        )
    return chunks or [ChunkDraft(0, text, 0, len(text), count_tokens(text))]


def extractive_summary(text: str, *, max_chars: int = 1200) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "..."


def digest_tags(text: str, findings: Iterable[PrivateFinding]) -> list[str]:
    tags = []
    lowered = text.casefold()
    for keyword, tag in (
        ("договор", "contract"),
        ("оплат", "payments"),
        ("персональ", "personal-data"),
        ("паспорт", "identity"),
        ("инн", "tax"),
    ):
        if keyword in lowered:
            tags.append(tag)
    for finding in findings:
        if finding.name not in tags:
            tags.append(finding.name)
    return tags[:12]
