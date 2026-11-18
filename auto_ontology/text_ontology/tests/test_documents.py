# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Readers and the text cleaner."""

from __future__ import annotations

import io

from auto_ontology.text_ontology.documents import clean_text, load_bytes, load_text


def test_clean_text_drops_furniture_and_rejoins_hyphens() -> None:
    raw = "La compu-\ntation du serveur.\n\n12\n\nPage 3\n\n" + "En-tête\n" * 4
    raw += "Le fait reste.\n\nRéférences\n[1] Un article.\n"
    cleaned, notes = clean_text(raw)

    assert "computation" in cleaned
    assert "Le fait reste." in cleaned
    assert "12" not in cleaned.split()
    assert "Un article" not in cleaned
    assert notes


def test_html_strips_scripts() -> None:
    loaded = load_bytes(
        "page.html",
        b"<html><script>alert(1)</script><p>Camille Martin dirige Lyon.</p></html>",
    )

    assert "Camille Martin" in loaded.text
    assert "alert" not in loaded.text


def test_markdown_keeps_link_text() -> None:
    loaded = load_text(
        "note.md", "Voir [Ada Lovelace](https://example.test) et le code.\n"
    )

    assert "Ada Lovelace" in loaded.text
    assert "https://example.test" not in loaded.text


def test_pdf_epub_and_docx_round_trip() -> None:
    text = "Camille Martin dirige la bibliothèque municipale de Lyon."

    assert "Camille Martin" in load_bytes("note.pdf", _pdf(text)).text
    assert "Camille Martin" in load_bytes("note.epub", _epub(text)).text
    assert "Camille Martin" in load_bytes("note.docx", _docx(text)).text


def test_scanned_pdf_warns_instead_of_pretending() -> None:
    loaded = load_bytes("scan.pdf", _pdf(""))

    assert any("OCR" in warning for warning in loaded.warnings)


def _pdf(text: str) -> bytes:
    """A one-page PDF whose text a reader can extract. Latin-1 covers French."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\n", " ")
    )
    stream = f"BT /F1 11 Tf 72 700 Td ({escaped}) Tj ET".encode(
        "latin-1", errors="replace"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode()
        output += body + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(output)


def _epub(text: str) -> bytes:
    import zipfile

    root = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{text}</p></body></html>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<manifest><item id="chap" href="chap.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="chap"/></spine>
</package>""",
        )
        archive.writestr("OEBPS/chap.xhtml", root)
    return buffer.getvalue()


def _docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
