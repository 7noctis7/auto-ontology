# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One command line: `ontology` and `python -m auto_ontology.text_ontology`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from auto_ontology.text_ontology import __main__ as text_cli
from auto_ontology.text_ontology import studio
from auto_ontology.text_ontology.store import ProjectStore


def test_the_text_entry_point_hands_studio_commands_over(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        studio, "ask_project", lambda question, home: f"réponse à {question}"
    )

    code = text_cli.main(["ask", "qui dirige ?", "--home", str(tmp_path)])

    assert code == 0
    assert "réponse à qui dirige ?" in capsys.readouterr().out


def test_the_studio_entry_point_hands_text_commands_over(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    document = tmp_path / "doc.txt"
    document.write_text(
        "#include <x.h>\nAlice works for ACME, a company in Paris.\n", "utf-8"
    )

    code = studio.main(["clean", str(document)])

    assert code == 0
    assert capsys.readouterr().out == "Alice works for ACME, a company in Paris.\n"


def test_a_bare_file_is_extracted_from_either_entry_point(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(text_cli, "_extract", lambda args: calls.append(args.inputs))
    document = tmp_path / "doc.txt"
    document.write_text("texte", "utf-8")

    assert studio.main([str(document)]) == 0
    assert text_cli.main([str(document)]) == 0
    assert calls == [[str(document)], [str(document)]]


def test_the_help_lists_both_groups(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        studio.main(["--help"])
    out = capsys.readouterr().out

    for command in (
        "extract",
        "eval",
        "merge",
        "export",
        "clean",
        "serve",
        "import",
        "ask",
        "mcp",
        "sdk",
    ):
        assert command in out


def test_serve_passes_its_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(studio, "serve", lambda **kwargs: seen.update(kwargs))

    code = studio.main(
        ["serve", "--port", "4300", "--no-browser", "--fake", "--home", str(tmp_path)]
    )

    assert code == 0
    assert (
        seen["port"] == 4300 and seen["open_browser"] is False and seen["fake"] is True
    )
    assert seen["home"] == tmp_path


def test_import_ask_and_sdk_work_on_one_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from auto_ontology.text_ontology.sample import SAMPLE_TEXT

    document = tmp_path / "bibliotheque.txt"
    document.write_text(SAMPLE_TEXT, encoding="utf-8")
    home = tmp_path / "home"

    assert studio.main(["import", str(document), "--fake", "--home", str(home)]) == 0
    project = ProjectStore(home).list_projects()[0]
    assert project.ontology.triplets

    assert studio.main(["ask", "qui dirige la bibliothèque", "--home", str(home)]) == 0
    assert "Camille Martin" in capsys.readouterr().out

    client = tmp_path / "client.py"
    assert studio.main(["sdk", "--out", str(client), "--home", str(home)]) == 0
    compile(client.read_text(encoding="utf-8"), str(client), "exec")
