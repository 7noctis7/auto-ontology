# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read a dropped file into clean text.

Each format is an adapter behind :func:`load_bytes`. The rest of the studio
only ever sees a :class:`LoadedDocument`: the original bytes, the cleaned
text, and warnings (a scan with no text layer, a noisy extract, a removed
bibliography). Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".text", ".log"}
_HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
_PDF_SUFFIXES = {".pdf"}
_EPUB_SUFFIXES = {".epub"}
_DOCX_SUFFIXES = {".docx"}

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_PAGE_NUMBER = re.compile(
    r"^(?:page\s*)?\d{1,4}$|^(?:[-–—]\s*)?\d{1,4}\s*[-–—]?$",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^```")
_REFERENCE_HEADING = re.compile(
    r"^(?:r[ée]f[ée]rences|bibliographie|bibliography|works cited)\s*$",
    re.IGNORECASE,
)


class DocumentReadError(ValueError):
    """The file could not be turned into text. The message is for the user."""


@dataclass
class LoadedDocument:
    """One uploaded or pasted document, ready to extract."""

    filename: str
    media_type: str
    text: str
    sha256: str
    noise_ratio: float
    warnings: list[str] = field(default_factory=list)
    original: bytes = b""


def noise_ratio(text: str) -> float:
    """Share of characters that are not letters. High means a noisy extract."""
    if not text:
        return 1.0
    letters = sum(character.isalpha() for character in text)
    return round(1 - letters / len(text), 3)


def clean_text(text: str) -> tuple[str, list[str]]:
    """Drop page furniture, fenced code and a trailing bibliography.

    The rules are conservative: a line is removed only when it is a page
    number, a short line repeated many times, or a fenced block. A
    bibliography is removed only when its heading sits in the last part of
    the document.
    """
    notes: list[str] = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)

    lines = text.split("\n")
    kept: list[str] = []
    in_fence = False
    dropped_code = 0
    for line in lines:
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            dropped_code += 1
            continue
        if in_fence:
            dropped_code += 1
            continue
        kept.append(line)
    if dropped_code:
        notes.append("Blocs de code retirés.")
    lines = kept

    counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if 3 <= len(stripped) <= 80:
            counts[stripped] = counts.get(stripped, 0) + 1
    repeated = {line for line, count in counts.items() if count >= 4}
    if repeated:
        lines = [line for line in lines if line.strip() not in repeated]
        notes.append("En-têtes ou pieds de page répétés retirés.")

    body: list[str] = []
    dropped_pages = 0
    for line in lines:
        if _PAGE_NUMBER.match(line.strip()):
            dropped_pages += 1
            continue
        body.append(line)
    if dropped_pages:
        notes.append("Numéros de page retirés.")

    cut_at = int(len(body) * 0.6)
    cut: int | None = None
    for index, line in enumerate(body):
        if index >= cut_at and _REFERENCE_HEADING.match(line.strip()):
            cut = index
            break
    if cut is not None and cut < len(body) - 1:
        body = body[:cut]
        notes.append("Section de références retirée.")

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip()
    return cleaned, notes


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentReadError("Le fichier n'est pas un texte lisible.")


def _finish(
    filename: str,
    media_type: str,
    raw_text: str,
    warnings: list[str],
    original: bytes,
) -> LoadedDocument:
    text, notes = clean_text(raw_text)
    warnings = [*warnings, *notes]
    ratio = noise_ratio(text)
    if text and ratio > 0.55:
        warnings.append(
            "Le texte contient beaucoup de caractères qui ne sont pas des lettres. "
            "L'extraction peut être bruitée (schéma, formule, mauvaise couche de texte)."
        )
    return LoadedDocument(
        filename=filename,
        media_type=media_type,
        text=text,
        sha256=hashlib.sha256(original).hexdigest(),
        noise_ratio=ratio,
        warnings=warnings,
        original=original,
    )


class _HTMLText(HTMLParser):
    """Visible text of an HTML document, without scripts or styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag in {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "section"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_text(data: bytes) -> str:
    parser = _HTMLText()
    parser.feed(_decode(data))
    return parser.text()


def _pdf_text(data: bytes) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentReadError(
            "La lecture PDF nécessite pypdf, qui n'est pas installé."
        ) from exc
    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        page_count = len(reader.pages)
    except Exception as exc:
        raise DocumentReadError(f"Ce PDF n'a pas pu être ouvert : {exc}") from exc
    text = "\n\n".join(pages)
    if page_count and len(text.strip()) < 40:
        warnings.append(
            "Ce PDF ne contient presque pas de texte. C'est probablement un scan : "
            "un OCR serait nécessaire, et cette application ne l'inclut pas."
        )
    return text, warnings


def _docx_text(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentReadError(
            "La lecture DOCX nécessite python-docx, qui n'est pas installé."
        ) from exc
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentReadError(f"Ce DOCX n'a pas pu être ouvert : {exc}") from exc
    parts = [
        paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()
    ]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def _epub_text(data: bytes) -> str:
    """EPUB is a zip of HTML chapters. Navigation documents are skipped."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentReadError("Cet EPUB n'est pas une archive lisible.") from exc
    names = [
        name
        for name in archive.namelist()
        if name.lower().endswith((".xhtml", ".html", ".htm"))
        and not name.lower().endswith(
            ("nav.xhtml", "nav.html", "toc.xhtml", "toc.html")
        )
    ]
    parts: list[str] = []
    for name in names:
        parser = _HTMLText()
        parser.feed(archive.read(name).decode("utf-8", errors="replace"))
        text = parser.text().strip()
        if text:
            parts.append(text)
    archive.close()
    if not parts:
        raise DocumentReadError("Cet EPUB ne contient pas de chapitre lisible.")
    return "\n\n".join(parts)


def _suffix(filename: str) -> str:
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot:].lower()


def load_text(filename: str, text: str) -> LoadedDocument:
    """A pasted passage, treated as plain text."""
    name = filename.strip() or "colle.txt"
    original = text.encode("utf-8")
    return _finish(name, "text/plain", text, [], original)


def load_bytes(filename: str, data: bytes) -> LoadedDocument:
    """Read *data* according to the suffix of *filename*."""
    name = filename.strip() or "document.txt"
    suffix = _suffix(name)
    warnings: list[str] = []
    if suffix in _PDF_SUFFIXES:
        text, warnings = _pdf_text(data)
        return _finish(name, "application/pdf", text, warnings, data)
    if suffix in _EPUB_SUFFIXES:
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise DocumentReadError("Cet EPUB n'est pas une archive lisible.")
        text = _epub_text(data)
        return _finish(name, "application/epub+zip", text, warnings, data)
    if suffix in _DOCX_SUFFIXES:
        text = _docx_text(data)
        return _finish(
            name,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            text,
            warnings,
            data,
        )
    if suffix in _HTML_SUFFIXES:
        text = _html_text(data)
        return _finish(name, "text/html", text, warnings, data)
    if suffix in _TEXT_SUFFIXES or suffix == "":
        text = _decode(data)
        media = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
        return _finish(name, media, text, warnings, data)
    if suffix == ".json":
        text = _decode(data)
        return _finish(name, "application/json", text, warnings, data)
    try:
        text = _decode(data)
    except DocumentReadError as exc:
        raise DocumentReadError(
            "Format non pris en charge. Déposez un PDF, EPUB, DOCX, HTML, "
            "Markdown ou un fichier texte."
        ) from exc
    warnings.append(f"Format {suffix or 'inconnu'} lu comme du texte brut.")
    return _finish(name, "application/octet-stream", text, warnings, data)
