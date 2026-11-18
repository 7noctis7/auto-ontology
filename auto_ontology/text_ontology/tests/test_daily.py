# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""brief, diff and the clipboard: the daily commands."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import daily, studio
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.daily import (
    ClipboardError,
    brief,
    diff,
    parse_since,
    read_clipboard,
)
from auto_ontology.text_ontology.sample import SAMPLE_TEXT
from auto_ontology.text_ontology.store import ProjectStore

_NOW = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24h", _NOW - timedelta(hours=24)),
        ("7d", _NOW - timedelta(days=7)),
        ("7j", _NOW - timedelta(days=7)),
        ("2w", _NOW - timedelta(weeks=2)),
        ("30min", _NOW - timedelta(minutes=30)),
        ("today", datetime(2026, 11, 18, tzinfo=timezone.utc)),
        ("hier", datetime(2026, 11, 17, tzinfo=timezone.utc)),
        ("2026-11-01", datetime(2026, 11, 1, tzinfo=timezone.utc)),
    ],
)
def test_periods_are_read(text: str, expected: datetime) -> None:
    assert parse_since(text, now=_NOW) == expected


def test_an_unreadable_period_says_how_to_write_one() -> None:
    with pytest.raises(ValueError, match="24h, 7d"):
        parse_since("la semaine dernière")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home with the sample library imported through the demo model."""
    document = tmp_path / "bibliotheque.txt"
    document.write_text(SAMPLE_TEXT, encoding="utf-8")
    home = tmp_path / "home"
    assert studio.main(["import", str(document), "--fake", "--home", str(home)]) == 0
    return home


def test_brief_lists_what_came_in_and_what_to_check(home: Path) -> None:
    store = ProjectStore(home)
    project = store.current()
    project.documents[0].chunks_failed = [2]
    store.save(project)

    report = brief(store.current(), datetime.now(timezone.utc) - timedelta(hours=1))
    text = report.markdown()

    assert report.documents[0]["filename"] == "bibliotheque.txt"
    assert report.documents[0]["facts"] > 0 and report.new_facts > 0
    assert report.top_entities
    assert "1 morceau(x) sans réponse" in text
    assert "## À vérifier" in text


def test_brief_says_an_extraction_is_running_or_was_interrupted(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProjectStore(home)
    project = store.current()
    document = project.documents[0]
    document.status = "running"
    document.chunks_total = 310
    store.save(project)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    done = len(document.chunk_notes)

    running = brief(store.current(), since, extracting=True)
    stopped = brief(store.current(), since)

    assert running.documents[0]["status"] == "running"
    assert f"extraction en cours, {done}/310 morceaux lus" in running.markdown()
    assert stopped.documents[0]["status"] == "interrupted"
    assert f"extraction interrompue après {done}/310 morceaux" in stopped.markdown()
    with store.busy(project.id):  # what another process sees during a run
        assert studio.main(["brief", "--home", str(home)]) == 0
    assert "extraction en cours" in capsys.readouterr().out


def test_brief_since_later_reports_nothing_new(home: Path) -> None:
    report = brief(
        ProjectStore(home).current(), datetime.now(timezone.utc) + timedelta(hours=1)
    )

    assert report.documents == [] and "Rien de nouveau." in report.markdown()


def test_diff_compares_with_the_snapshot_before_the_moment(home: Path) -> None:
    store = ProjectStore(home)
    project = store.current()
    store.save(project, snapshot=True)  # the state "before"
    moment = datetime.now(timezone.utc)
    project = store.current()
    removed = project.ontology.triplets.pop(0)
    project.ontology.classes = [*project.ontology.classes]
    store.save(project, snapshot=True)

    result = diff(store.current(), store.project_dir(project.id), moment)

    assert (
        f"{removed.subject} {removed.predicate} {removed.object}"
        in result.removed["facts"]
    )
    assert result.note == ""
    assert "## Faits (+0 / -1)" in result.markdown()


def test_diff_without_snapshots_counts_what_new_documents_brought(home: Path) -> None:
    store = ProjectStore(home)
    project = store.current()
    for path in (store.project_dir(project.id) / "history").glob("*.json"):
        path.unlink()

    result = diff(
        project,
        store.project_dir(project.id),
        datetime.now(timezone.utc) - timedelta(hours=1),
    )

    assert "Aucun instantané" in result.note
    assert result.added["facts"]
    assert result.documents == ["bibliotheque.txt"]


def test_cli_brief_and_diff(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert studio.main(["brief", "--since", "1h", "--home", str(home)]) == 0
    assert "# Brief" in capsys.readouterr().out

    assert studio.main(["diff", "--since", "1h", "--json", "--home", str(home)]) == 0
    assert '"documents": [\n    "bibliotheque.txt"' in capsys.readouterr().out

    assert studio.main(["brief", "--since", "jamais", "--home", str(home)]) == 2


def test_api_brief_and_diff(home: Path) -> None:
    client = TestClient(
        create_app(home=home, fake=True), base_url="http://127.0.0.1:4173"
    )

    body = client.get("/api/v1/brief", params={"since": "1h"}).json()
    assert body["documents"] and body["markdown"].startswith("# Brief")
    assert client.get("/api/v1/diff", params={"since": "7d"}).status_code == 200
    assert client.get("/api/v1/brief", params={"since": "n'importe"}).status_code == 422


# --- Clipboard ---------------------------------------------------------------


def test_the_clipboard_is_read_with_the_system_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily.sys, "platform", "linux")
    monkeypatch.setattr(
        daily.shutil,
        "which",
        lambda name: "/usr/bin/xclip" if name == "xclip" else None,
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="Note copiée.".encode())

    monkeypatch.setattr(daily.subprocess, "run", fake_run)

    assert read_clipboard() == "Note copiée."
    assert calls == [["xclip", "-selection", "clipboard", "-o"]]


def test_no_clipboard_tool_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily.sys, "platform", "linux")
    monkeypatch.setattr(daily.shutil, "which", lambda name: None)

    with pytest.raises(ClipboardError, match="wl-clipboard ou xclip"):
        read_clipboard()


def test_import_paste_adds_the_clipboard_as_a_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daily, "read_clipboard", lambda: SAMPLE_TEXT)
    home = tmp_path / "home"

    assert studio.main(["import", "--paste", "--fake", "--home", str(home)]) == 0

    project = ProjectStore(home).current()
    assert project.documents[0].filename.startswith("presse-papiers ")
    assert project.ontology.triplets
    assert studio.main(["import", "--home", str(home)]) == 2  # nothing to import


def test_extract_paste_reads_the_clipboard_not_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from auto_ontology.text_ontology import __main__ as cli
    from auto_ontology.text_ontology.models import TextOntology, TextOntologyResult

    monkeypatch.setattr(daily, "read_clipboard", lambda: "Alice dirige ACME.")
    seen: dict[str, Any] = {}

    class Stub:
        description = "stub"
        notes: list[str] = []

    monkeypatch.setattr(cli, "resolve_backend", lambda **_: Stub())
    monkeypatch.setattr(
        cli,
        "extract_text_ontology",
        lambda text, **_: (
            seen.setdefault("text", text)
            and TextOntologyResult(ontology=TextOntology())
        ),
    )

    assert cli.main(["extract", "--paste"]) == 0
    assert seen["text"] == "Alice dirige ACME."
