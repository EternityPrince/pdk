from __future__ import annotations

from pdk.file_index import FileIndex
from pdk.file_workflows import index_paths, summarize_source
from pdk.privacy import PrivateFinding
from pdk.sources import TextSource


def email_finding() -> PrivateFinding:
    return PrivateFinding(
        name="email",
        label="email address",
        start=6,
        end=22,
        text="ivan@example.com",
        score=0.9,
        detector="test",
    )


def test_summarize_source_builds_scan_table_row():
    source = TextSource("stdin", "Email ivan@example.com")
    summary = summarize_source(source, [email_finding()])

    assert summary.as_table_row() == ("stdin", 1, summary.token_count, 1, 22, "email")
    assert summary.token_count > 0


def test_index_paths_persists_chunks_findings_and_entities(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Email ivan@example.com", encoding="utf-8")
    index = FileIndex(tmp_path / "index.sqlite3")

    rows = index_paths(
        [str(path)],
        recursive=True,
        chunk_tokens=1200,
        detector=lambda text: [email_finding()] if "ivan@example.com" in text else [],
        index=index,
    )

    assert rows[0].source == str(path)
    assert rows[0].finding_count == 1
    [record] = index.files()
    assert record.path == str(path)
    assert record.finding_count == 1
    assert index.entities(str(record.id))[0]["entity_type"] == "email"
