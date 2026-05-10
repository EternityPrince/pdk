from __future__ import annotations

from pathlib import Path
import tempfile
from unittest import TestCase

from pdk.file_index import ChunkDraft, FileIndex, file_sha256
from pdk.privacy import PrivateFinding


class FileIndexTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.db = FileIndex(self.tmp_path / "index.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upserts_file_chunks_findings_entities_and_summary(self):
        path = self.tmp_path / "doc.txt"
        path.write_text("Email ivan@example.com", encoding="utf-8")
        file_id = self.db.upsert_file(
            path=path,
            kind="txt",
            sha256=file_sha256(path),
            token_count=5,
            line_count=1,
            char_count=22,
        )
        chunks = [ChunkDraft(0, "Email ivan@example.com", 0, 22, 5)]
        chunk_ids = self.db.add_chunks(file_id, chunks)
        finding = PrivateFinding(
            name="email",
            label="email address",
            start=6,
            end=22,
            text="ivan@example.com",
            score=0.9,
            detector="regex",
        )
        self.db.add_findings(file_id, [(0, finding)], chunk_ids)
        self.db.add_entities(file_id, [finding])
        self.db.add_summary(
            file_id,
            level="file",
            model="model",
            prompt_version="test",
            summary="Short summary",
            tags_json='["email"]',
        )

        [record] = self.db.files()
        self.assertEqual(record.path, str(path))
        self.assertEqual(record.finding_count, 1)
        self.assertEqual(record.summary, "Short summary")
        entities = self.db.entities(str(file_id))
        self.assertEqual(entities[0]["entity_type"], "email")
        self.assertEqual(entities[0]["count"], 1)

    def test_get_file_accepts_path_or_id(self):
        path = self.tmp_path / "doc.txt"
        path.write_text("Body", encoding="utf-8")
        file_id = self.db.upsert_file(
            path=path,
            kind="txt",
            sha256=file_sha256(path),
            token_count=1,
            line_count=1,
            char_count=4,
        )

        self.assertEqual(self.db.get_file(str(file_id)).path, str(path))
        self.assertEqual(self.db.get_file(str(path)).id, file_id)
