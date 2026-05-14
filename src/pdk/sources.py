from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class TextSource:
    label: str
    text: str


TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".htm",
    ".cjs",
    ".js",
    ".jsx",
    ".json",
    ".log",
    ".mjs",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".toml",
    ".ts",
    ".tsx",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".docx", ".epub", ".pdf"}


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise SourceError(f"could not read DOCX text from {path}") from exc

    root = ET.fromstring(document)
    parts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
        elif node.tag.endswith("}p"):
            parts.append("\n")
    return "".join(parts).strip()


def _extract_epub_zip_html(path: Path, parser) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith((".html", ".htm", ".xhtml"))
            )
            parts = []
            for name in names:
                soup = parser(archive.read(name), "html.parser")
                text = soup.get_text("\n", strip=True)
                if text:
                    parts.append(text)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceError(f"could not read EPUB text from {path}") from exc
    return "\n\n".join(parts).strip()


def _extract_epub(path: Path) -> str:
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub
    except ModuleNotFoundError as exc:
        raise SourceError("EPUB scanning requires installing the `files` extra") from exc
    try:
        book = epub.read_epub(str(path))
        parts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text("\n", strip=True)
            if text:
                parts.append(text)
    except Exception as exc:
        fallback = _extract_epub_zip_html(path, BeautifulSoup)
        if fallback:
            return fallback
        raise SourceError(f"could not read EPUB text from {path}") from exc
    return "\n\n".join(part for part in parts if part.strip()).strip()


def _extract_pdf(path: Path) -> str:
    try:
        import pymupdf
    except ModuleNotFoundError as exc:
        raise SourceError("PDF scanning requires installing the `files` extra") from exc
    try:
        with pymupdf.open(path) as document:
            return "\n".join(page.get_text() for page in document).strip()
    except Exception as exc:
        raise SourceError(f"could not read PDF text from {path}") from exc


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or not suffix:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".epub":
        return _extract_epub(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    raise SourceError(f"unsupported file type: {path}")


def iter_paths(paths: list[str], *, recursive: bool = True) -> list[Path]:
    result: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            result.extend(
                sorted(item for item in iterator if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES)
            )
        else:
            result.append(path)
    return result


def read_sources(paths: list[str], *, recursive: bool = True) -> list[TextSource]:
    sources = []
    for path in iter_paths(paths, recursive=recursive):
        if not path.exists():
            raise SourceError(f"file not found: {path}")
        sources.append(TextSource(str(path), extract_text(path)))
    return sources
