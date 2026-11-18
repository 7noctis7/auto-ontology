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
from pathlib import PurePosixPath

from auto_ontology.text_ontology.clean import clean_text as clean_pdf_noise
from auto_ontology.text_ontology.clean import rejoin_line_breaks

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".text", ".log"}
_HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
_PDF_SUFFIXES = {".pdf"}
_EPUB_SUFFIXES = {".epub"}
_DOCX_SUFFIXES = {".docx"}
_EMAIL_SUFFIXES = {".eml"}
_NOTE_SUFFIXES = {".md", ".markdown"}

# Every suffix the studio reads as a document (spreadsheets are tables, see
# ``tables.TABULAR_SUFFIXES``; ``.csv`` is both and is loaded as a table).
DOCUMENT_SUFFIXES = (
    _TEXT_SUFFIXES
    | _HTML_SUFFIXES
    | _PDF_SUFFIXES
    | _EPUB_SUFFIXES
    | _DOCX_SUFFIXES
    | _EMAIL_SUFFIXES
    | {".json"}
)

# An EPUB or DOCX is a zip. These bound what one may expand to, so a small
# crafted file cannot exhaust memory (a "zip bomb").
_MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
_MAX_MEMBER_RATIO = 200
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
    pages: int = 0
    # Hash of the text itself, so the same content saved as another file, or
    # pasted, is recognised as already in the project.
    text_sha256: str = ""


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
    text = rejoin_line_breaks(text)
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


def _check_archive(data: bytes, kind: str) -> None:
    """Refuse an archive whose content would expand far beyond its size."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise DocumentReadError(f"Ce {kind} n'est pas une archive lisible.") from exc
    total = sum(member.file_size for member in members)
    suspicious = any(
        member.file_size > 1024 * 1024
        and member.file_size > _MAX_MEMBER_RATIO * max(member.compress_size, 1)
        for member in members
    )
    if total > _MAX_ARCHIVE_BYTES or suspicious:
        raise DocumentReadError(
            f"Ce {kind} se décompresse en un volume anormal "
            f"({total // (1024 * 1024)} Mo) : il n'a pas été ouvert."
        )


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
    pages: int = 0,
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
        pages=pages or max(1, len(text) // 1800) if text.strip() else 0,
        text_sha256=text_hash(text),
    )


def text_hash(text: str) -> str:
    """Identity of a text, whatever its spacing or line breaks."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


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


def _pdf_text(data: bytes) -> tuple[str, list[str], int]:
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
        from auto_ontology.text_ontology.quality import ocr_hint

        warnings.append(
            "Ce PDF ne contient presque pas de texte. C'est probablement un scan."
            + ocr_hint()
        )
    return text, warnings, page_count


def _docx_text(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentReadError(
            "La lecture DOCX nécessite python-docx, qui n'est pas installé."
        ) from exc
    _check_archive(data, "DOCX")
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
    _check_archive(data, "EPUB")
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


# --- Notes exported from Obsidian or Notion --------------------------------

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_FRONT_TITLE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)
_EMBED = re.compile(r"!\[\[[^\]]*\]\]")
_WIKILINK_ALIAS = re.compile(r"\[\[[^\]|]*\|([^\]]+)\]\]")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]]*)?\]\]")
_CALLOUT = re.compile(r"^(>\s*)\[![\w-]+\][+-]?\s*", re.MULTILINE)
_NOTION_ID = re.compile(r"\s+[0-9a-f]{32}(?=(?:\.[A-Za-z0-9]+)?$)")


def note_text(text: str) -> tuple[str, list[str]]:
    """Markdown from a notes app, read as prose.

    The front matter is dropped (its ``title`` becomes the heading when the
    note has none), ``[[Page|alias]]`` reads as ``alias``, ``[[Page]]`` as
    ``Page``, embeds disappear and callout markers are removed.
    """
    notes: list[str] = []
    match = _FRONTMATTER.match(text)
    if match:
        text = text[match.end() :]
        title = _FRONT_TITLE.search(match.group(1))
        if title and not text.lstrip().startswith("#"):
            text = f"# {title.group(1)}\n\n{text}"
        notes.append("Propriétés de la note retirées.")
    if "[[" in text:
        text = _EMBED.sub("", text)
        text = _WIKILINK_ALIAS.sub(r"\1", text)
        text = _WIKILINK.sub(r"\1", text)
    text = _CALLOUT.sub(r"\1", text)
    return text, notes


def display_name(path: str) -> str:
    """A member path as a file name: no folders, no Notion page id."""
    name = PurePosixPath(path.replace("\\", "/")).name
    return _NOTION_ID.sub("", name)


# --- Email (.eml) ---------------------------------------------------------

_MAX_ATTACHMENTS = 20
_MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_QUOTE_INTRO = re.compile(
    r"^(?:le .{4,120} a écrit\s*:|on .{4,120} wrote\s*:|-{2,}\s*original message"
    r"\s*-{2,}|-{2,}\s*message d'origine\s*-{2,})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Attachment:
    """A file carried by an email or an archive."""

    filename: str
    data: bytes


def _message(data: bytes) -> object:
    from email import policy
    from email.parser import BytesParser

    try:
        return BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:  # the parser is lenient; this is a safety net
        raise DocumentReadError(f"Ce message n'a pas pu être lu : {exc}") from exc


def _part_text(part: object) -> str:
    try:
        content = part.get_content()  # type: ignore[attr-defined]
    except (LookupError, ValueError, AssertionError):
        payload = part.get_payload(decode=True) or b""  # type: ignore[attr-defined]
        content = _decode(payload) if isinstance(payload, bytes) else str(payload)
    if not isinstance(content, str):
        content = _decode(bytes(content))
    if part.get_content_type() == "text/html":  # type: ignore[attr-defined]
        parser = _HTMLText()
        parser.feed(content)
        content = parser.text()
    return content


def _without_quotes(body: str) -> tuple[str, bool]:
    """The new part of a reply: quoted earlier messages are cut."""
    kept: list[str] = []
    cut = False
    for line in body.splitlines():
        stripped = line.strip()
        if _QUOTE_INTRO.match(stripped):
            cut = True
            break
        if stripped.startswith(">"):
            cut = True
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    # A message that is only a quote keeps its quote: it is all there is.
    return (text, cut) if text else (body, False)


def _email_text(data: bytes) -> tuple[str, list[str]]:
    message = _message(data)
    warnings: list[str] = []
    lines = []
    for label, header in (
        ("Objet", "subject"),
        ("De", "from"),
        ("À", "to"),
        ("Cc", "cc"),
        ("Date", "date"),
    ):
        value = message.get(header)  # type: ignore[attr-defined]
        if value:
            lines.append(f"{label} : {' '.join(str(value).split())}")
    body_part = message.get_body(preferencelist=("plain", "html"))  # type: ignore[attr-defined]
    body = _part_text(body_part) if body_part is not None else ""
    body, quoted = _without_quotes(body)
    if quoted:
        warnings.append("Citations des messages précédents retirées.")
    names = [a.filename for a in _attachments(message)]
    if names:
        lines.append("Pièces jointes : " + ", ".join(names))
    if not body.strip():
        warnings.append("Ce message n'a pas de corps de texte.")
    return "\n".join(lines) + "\n\n" + body, warnings


def _attachments(message: object) -> list[Attachment]:
    found: list[Attachment] = []
    for part in message.iter_attachments():  # type: ignore[attr-defined]
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or len(payload) > _MAX_ATTACHMENT_BYTES:
            continue
        found.append(Attachment(display_name(name), payload))
        if len(found) >= _MAX_ATTACHMENTS:
            break
    return found


def email_attachments(data: bytes) -> list[Attachment]:
    """The files attached to an email, at most twenty, each under 50 MB."""
    return _attachments(_message(data))


# --- Archives (a Notion export is a zip) ------------------------------------

_MAX_ARCHIVE_MEMBERS = 500


def archive_members(data: bytes, accepts: object) -> list[Attachment]:
    """The files of a zip whose name *accepts* returns true for.

    Folders, hidden files and macOS resource forks are skipped, and the
    archive is checked for an abnormal expansion before anything is read.
    """
    _check_archive(data, "ZIP")
    members: list[Attachment] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if (
                info.is_dir()
                or not parts
                or any(part.startswith((".", "__MACOSX")) for part in parts)
            ):
                continue
            name = display_name(info.filename)
            if not accepts(name):  # type: ignore[operator]
                continue
            members.append(Attachment(name, archive.read(info)))
            if len(members) >= _MAX_ARCHIVE_MEMBERS:
                break
    return members


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


# Formats whose text is not the file's bytes: they go through their reader.
_STRUCTURED_SUFFIXES = (
    _PDF_SUFFIXES | _EPUB_SUFFIXES | _DOCX_SUFFIXES | _HTML_SUFFIXES | _EMAIL_SUFFIXES
)


def read_document_text(filename: str, data: bytes) -> tuple[str, list[str]]:
    """The text of a file for the command line, and what reading it noted.

    PDF, EPUB, DOCX, HTML and email go through the studio's readers (and
    their cleaning). Anything else is decoded as it is, so a plain text file reaches
    the extractor untouched unless ``--clean`` is asked for.
    """
    if _suffix(filename) in _STRUCTURED_SUFFIXES:
        loaded = load_bytes(filename, data)
        return loaded.text, list(loaded.warnings)
    return _decode(data), []


def load_bytes(filename: str, data: bytes) -> LoadedDocument:
    """Read *data* according to the suffix of *filename*."""
    name = filename.strip() or "document.txt"
    suffix = _suffix(name)
    warnings: list[str] = []
    if suffix in _PDF_SUFFIXES:
        text, warnings, pages = _pdf_text(data)
        # PDF text also carries diagram labels, code and formulas: drop them.
        pdf = clean_pdf_noise(text)
        if (note := pdf.summary_fr()) is not None:
            warnings = [*warnings, note]
        return _finish(name, "application/pdf", pdf.text, warnings, data, pages)
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
    if suffix in _EMAIL_SUFFIXES:
        text, warnings = _email_text(data)
        return _finish(name, "message/rfc822", text, warnings, data)
    if suffix in _NOTE_SUFFIXES:
        text, warnings = note_text(_decode(data))
        return _finish(name, "text/markdown", text, warnings, data)
    if suffix in _TEXT_SUFFIXES or suffix == "":
        text = _decode(data)
        return _finish(name, "text/plain", text, warnings, data)
    if suffix == ".json":
        text = _decode(data)
        return _finish(name, "application/json", text, warnings, data)
    if suffix == ".zip":
        raise DocumentReadError(
            "Une archive contient plusieurs fichiers : importez-la avec "
            "`ontology import export.zip`, ou déposez-la dans le dossier surveillé."
        )
    try:
        text = _decode(data)
    except DocumentReadError as exc:
        raise DocumentReadError(
            "Format non pris en charge. Déposez un PDF, EPUB, DOCX, HTML, "
            "un e-mail (.eml), du Markdown ou un fichier texte."
        ) from exc
    warnings.append(f"Format {suffix or 'inconnu'} lu comme du texte brut.")
    return _finish(name, "application/octet-stream", text, warnings, data)
