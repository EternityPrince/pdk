from __future__ import annotations

from pathlib import Path
import tempfile
from unittest import TestCase
import zipfile

from pdk.sources import SourceError, extract_text, read_sources


class SourcesTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extracts_docx_text_without_external_dependencies(self):
        path = self.tmp_path / "sample.docx"
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>ФИО: Иван Петров</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", xml)

        self.assertIn("ФИО: Иван Петров", extract_text(path))

    def test_extracts_epub_html_text_without_external_dependencies(self):
        path = self.tmp_path / "sample.epub"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("OEBPS/chapter.xhtml", "<html><body><p>Email ivan@example.com</p></body></html>")

        try:
            text = extract_text(path)
        except SourceError as exc:
            self.assertIn("EPUB scanning requires installing", str(exc))
        else:
            self.assertIn("Email ivan@example.com", text)

    def test_read_sources_expands_supported_files_in_directory(self):
        docs = self.tmp_path / "docs"
        docs.mkdir()
        (docs / "a.txt").write_text("A", encoding="utf-8")
        (docs / "b.md").write_text("B", encoding="utf-8")
        (docs / "ignore.bin").write_bytes(b"C")

        sources = read_sources([str(docs)])

        self.assertEqual([Path(source.label).name for source in sources], ["a.txt", "b.md"])
