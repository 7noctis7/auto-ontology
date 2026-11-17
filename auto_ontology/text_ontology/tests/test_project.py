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
