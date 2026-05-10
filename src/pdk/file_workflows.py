from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .file_index import FileIndex, file_sha256
from .privacy import PrivateFinding
from .sources import TextSource, read_sources
from .text_analysis import chunk_text, finding_types, line_count
from .tokens import count_tokens

FindingDetector = Callable[[str], Sequence[PrivateFinding]]


@dataclass(frozen=True)
class ScanSummary:
    source: str
    finding_count: int
    token_count: int
    line_count: int
    char_count: int
    finding_types: str

    def as_table_row(self) -> tuple[str, int, int, int, int, str]:
        return (
            self.source,
            self.finding_count,
            self.token_count,
            self.line_count,
            self.char_count,
            self.finding_types,
        )


def summarize_source(source: TextSource, findings: Sequence[PrivateFinding]) -> ScanSummary:
    return ScanSummary(
        source=source.label,
        finding_count=len(findings),
        token_count=count_tokens(source.text),
        line_count=line_count(source.text),
        char_count=len(source.text),
        finding_types=finding_types(findings),
    )


def index_paths(
    paths: list[str],
    *,
    recursive: bool,
    chunk_tokens: int,
    detector: FindingDetector,
    index: FileIndex | None = None,
) -> list[ScanSummary]:
    file_index = index or FileIndex()
    rows: list[ScanSummary] = []
    for source in read_sources(paths, recursive=recursive):
        path = Path(source.label)
        chunks = chunk_text(source.text, target_tokens=chunk_tokens)
        findings_by_chunk = []
        flat_findings = []
        for chunk in chunks:
            findings = detector(chunk.text)
            findings_by_chunk.extend((chunk.chunk_index, finding) for finding in findings)
            flat_findings.extend(findings)

        file_id = file_index.upsert_file(
            path=path,
            kind=path.suffix.lower().lstrip(".") or "text",
            sha256=file_sha256(path),
            token_count=count_tokens(source.text),
            line_count=line_count(source.text),
            char_count=len(source.text),
        )
        chunk_ids = file_index.add_chunks(file_id, chunks)
        file_index.add_findings(file_id, findings_by_chunk, chunk_ids)
        file_index.add_entities(file_id, flat_findings)
        rows.append(summarize_source(source, flat_findings))
    return rows
