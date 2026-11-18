# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for project files, merging, the glossary link and the CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auto_ontology.text_ontology import __main__ as cli
from auto_ontology.text_ontology import glossary
from auto_ontology.text_ontology.models import TextOntology, TextOntologyResult
from auto_ontology.text_ontology.project import (
    load_ontology,
    merge_ontologies,
    save_ontology,
)


def _one_class(name: str, description: str = "") -> TextOntology:
    return TextOntology.model_validate(
        {"classes": [{"name": name, "parent": None, "description": description}]}
    )


def test_save_then_load_round_trips_with_accents(tmp_path: Path) -> None:
    ontology = _one_class("Societe", "Société anonyme")
    target = tmp_path / "sub" / "projet.json"

    save_ontology(ontology, target)

    assert "Société anonyme" in target.read_text(encoding="utf-8")
    assert load_ontology(target) == ontology


def test_merge_reconciles_duplicates_and_keeps_the_first_spelling() -> None:
    merged, warnings = merge_ontologies(
        [_one_class("Personne", "Un humain"), _one_class("Personnes", "Des gens")]
    )

    assert [(c.name, c.description) for c in merged.classes] == [
        ("Personne", "Un humain")
    ]
    assert "Class 'Personnes' merged into Personne." in warnings


def test_glossary_terms_become_pascal_case_class_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_ontology.dal import terms

    monkeypatch.setattr(
        terms,
        "fetch_all_terms",
        lambda: [{"name": "Purchase Order"}, {"name": "purchase order"}, {"name": ""}],
    )

    assert glossary.glossary_class_names() == ["PurchaseOrder"]


class _StubBackend:
    description = "stub-model"
    notes: list[str] = []

    def __call__(self, system: str, user: str) -> TextOntology:
        return TextOntology()


@pytest.fixture(autouse=True)
def _no_model_lookup(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """CLI tests never resolve a real model; they record what was asked."""
    asked: dict[str, Any] = {}

    def fake_resolve(**kwargs: Any) -> _StubBackend:
        asked.update(kwargs)
        return _StubBackend()

    monkeypatch.setattr(cli, "resolve_backend", fake_resolve)
    return asked


def _run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(args)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["doc.txt"], ["extract", "doc.txt"]),
        ([], ["extract"]),
        (
            ["--log-level", "INFO", "doc.txt"],
            ["--log-level", "INFO", "extract", "doc.txt"],
        ),
        (
            ["--log-level", "INFO", "export", "a.json"],
            ["--log-level", "INFO", "export", "a.json"],
        ),
        (["merge", "a.json"], ["merge", "a.json"]),
        (["-o", "out.json", "doc.txt"], ["extract", "-o", "out.json", "doc.txt"]),
        (["--help"], ["--help"]),
    ],
)
def test_extract_is_the_default_command(args: list[str], expected: list[str]) -> None:
    assert cli._with_default_command(args) == expected


def test_cli_merge_then_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save_ontology(_one_class("Personne"), tmp_path / "a.json")
    save_ontology(_one_class("Personnes"), tmp_path / "b.json")
    project = tmp_path / "projet.json"

    code, _, err = _run(
        [
            "merge",
            str(tmp_path / "a.json"),
            str(tmp_path / "b.json"),
            "-o",
            str(project),
        ],
        capsys,
    )
    assert code == 0
    assert "merged into Personne" in err
    assert [c.name for c in load_ontology(project).classes] == ["Personne"]

    code, out, _ = _run(["export", str(project), "--format", "mermaid"], capsys)
    assert code == 0
    assert out.startswith("flowchart LR")


def test_cli_extract_grows_the_project_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "doc.txt"
    document.write_text("Alice est une personne.", encoding="utf-8")
    project = tmp_path / "projet.json"
    save_ontology(_one_class("Personne"), project)
    seen: dict[str, Any] = {}

    def fake_extract(text: str, **kwargs: Any) -> TextOntologyResult:
        seen.update(text=text, **kwargs)
        return TextOntologyResult(ontology=_one_class("Personne"), warnings=["w"])

    monkeypatch.setattr(cli, "extract_text_ontology", fake_extract)

    code, out, err = _run(
        ["--log-level", "ERROR", str(document), "--project", str(project)], capsys
    )

    assert code == 0
    assert out == ""  # the project file is the output
    assert "warning: w" in err
    assert seen["text"] == "Alice est une personne."
    assert seen["base"] == _one_class("Personne")
    assert json.loads(project.read_text(encoding="utf-8"))["classes"][0]["name"] == (
        "Personne"
    )


def test_cli_reports_a_missing_file_in_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(["export", "absent.json", "-f", "html"], capsys)

    assert code == 1
    assert out == ""
    assert err.startswith("error: ")


def test_cli_glossary_failure_is_reported_not_raised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> list[str]:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(glossary, "glossary_class_names", broken)
    document = tmp_path / "doc.txt"
    document.write_text("texte", encoding="utf-8")

    code, _, err = _run([str(document), "--glossary"], capsys)

    assert code == 1
    assert "cannot read the Auto-Ontology glossary" in err


def test_cli_passes_the_local_model_options(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_ontology.utils import llm_invoke

    document = tmp_path / "doc.txt"
    document.write_text("texte", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_extract(text: str, **kwargs: Any) -> TextOntologyResult:
        seen.update(kwargs)
        seen["timeout"] = llm_invoke.LLM_INVOKE_TIMEOUT_S
        return TextOntologyResult(ontology=TextOntology())

    monkeypatch.setattr(cli, "extract_text_ontology", fake_extract)
    monkeypatch.setattr(llm_invoke, "LLM_INVOKE_TIMEOUT_S", 120)

    code, _, _ = _run(
        [
            str(document),
            "--timeout",
            "600",
            "--max-tokens",
            "4096",
            "--skip-failed-chunks",
        ],
        capsys,
    )

    assert code == 0
    assert seen["timeout"] == 600
    assert seen["max_tokens"] == 4096
    assert seen["skip_failed_chunks"] is True


def test_cli_passes_provider_model_and_clean(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    _no_model_lookup: dict[str, Any],
) -> None:
    document = tmp_path / "doc.txt"
    document.write_text("texte", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_extract(text: str, **kwargs: Any) -> TextOntologyResult:
        seen.update(kwargs)
        return TextOntologyResult(ontology=TextOntology())

    monkeypatch.setattr(cli, "extract_text_ontology", fake_extract)

    code, _, err = _run(
        [str(document), "--provider", "local", "--model", "auto", "--clean"], capsys
    )

    assert code == 0
    assert "model: stub-model" in err
    assert _no_model_lookup == {
        "provider": "local",
        "model": "auto",
        "max_tokens": 8192,
    }
    assert seen["clean"] is True
    assert isinstance(seen["backend"], _StubBackend)
    assert seen["lang"] == "auto"
    assert seen["overlap_chars"] == 600


def test_cli_clean_previews_the_cleaned_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = tmp_path / "doc.txt"
    document.write_text(
        "Alice works for ACME, a company that builds very reliable rockets.\n"
        "#include <math.h>\n"
        "int i, k;\n",
        encoding="utf-8",
    )

    code, out, err = _run(["clean", str(document)], capsys)

    assert code == 0
    assert out == "Alice works for ACME, a company that builds very reliable rockets.\n"
    assert "2 code lines" in err


def _docx_bytes(paragraphs: list[str]) -> bytes:
    import io

    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_cli_reads_a_docx_and_an_html_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "note.docx").write_bytes(
        _docx_bytes(["Alice dirige la bibliothèque municipale de Lyon depuis 2019."])
    )
    (tmp_path / "page.html").write_text(
        "<html><body><h1>Titre</h1><p>Bob travaille pour ACME à Paris.</p>"
        "<script>alert(1)</script></body></html>",
        encoding="utf-8",
    )

    code, out, _ = _run(
        ["clean", str(tmp_path / "note.docx"), str(tmp_path / "page.html")], capsys
    )

    assert code == 0
    assert "Alice dirige la bibliothèque municipale de Lyon" in out
    assert "Bob travaille pour ACME à Paris." in out
    assert "alert(1)" not in out


def test_cli_reports_an_unreadable_pdf_in_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "abime.pdf").write_bytes(b"%PDF-1.4\n\xff\xfe pas un vrai PDF")

    code, out, err = _run(["clean", str(tmp_path / "abime.pdf")], capsys)

    assert code == 1
    assert out == ""
    assert err.startswith("error: ") and "PDF" in err
    assert "codec" not in err


def test_cli_reads_a_latin1_text_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "ancien.txt").write_bytes(
        "Le château de Versailles est situé en Île-de-France.".encode("cp1252")
    )

    code, out, _ = _run(["clean", str(tmp_path / "ancien.txt")], capsys)

    assert code == 0
    assert "château" in out and "Île-de-France" in out


def _pdf_bytes(line: str) -> bytes:
    """A minimal valid one-page PDF showing *line* (ASCII), offsets computed."""
    stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_cli_reads_a_pdf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "papier.pdf").write_bytes(
        _pdf_bytes("Satoshi Nakamoto proposed a peer-to-peer electronic cash system.")
    )

    code, out, _ = _run(["clean", str(tmp_path / "papier.pdf")], capsys)

    assert code == 0
    assert "Satoshi Nakamoto proposed a peer-to-peer electronic cash system." in out
