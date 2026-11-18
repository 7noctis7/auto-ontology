# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Watch v2: emails, note exports, duplicate content and the activity journal."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest

from auto_ontology.text_ontology import studio
from auto_ontology.text_ontology.daily import brief
from auto_ontology.text_ontology.documents import (
    DocumentReadError,
    display_name,
    load_bytes,
    load_text,
    note_text,
    read_document_text,
)
from auto_ontology.text_ontology.inbox import (
    Item,
    ingest_item,
    read_journal,
    unpack,
    walk,
)
from auto_ontology.text_ontology.llm_settings import resolve_llm_config
from auto_ontology.text_ontology.pipeline import ingest_document
from auto_ontology.text_ontology.sample import SAMPLE_TEXT, FakeLLM
from auto_ontology.text_ontology.store import ProjectStore

_HOUR_AGO = datetime.now(timezone.utc) - timedelta(hours=1)


def _email(
    body: str = "Bonjour,\n\nLe contrat ACME est renouvelé jusqu'en 2027.\n",
    *,
    html: str | None = None,
    attachments: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    message = EmailMessage()
    message["Subject"] = "Renouvellement ACME"
    message["From"] = "Alice Martin <alice@example.com>"
    message["To"] = "equipe@example.com"
    message["Date"] = "Tue, 17 Nov 2026 09:30:00 +0100"
    if html is not None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(body)
    for name, data in attachments:
        message.add_attachment(
            data, maintype="application", subtype="octet-stream", filename=name
        )
    return message.as_bytes()


# --- Email --------------------------------------------------------------------


def test_an_email_reads_as_its_headers_and_new_text() -> None:
    raw = _email(
        "Merci, c'est validé.\n\nLe 16 nov. 2026, Bob a écrit :\n> Peux-tu valider ?\n",
        attachments=(("Contrat ACME.pdf", b"%PDF-1.4"),),
    )

    loaded = load_bytes("renouvellement.eml", raw)

    assert loaded.media_type == "message/rfc822"
    assert "Objet : Renouvellement ACME" in loaded.text
    assert "De : Alice Martin <alice@example.com>" in loaded.text
    assert "Pièces jointes : Contrat ACME.pdf" in loaded.text
    assert "Merci, c'est validé." in loaded.text
    assert "Peux-tu valider" not in loaded.text
    assert "Citations des messages précédents retirées." in loaded.warnings


def test_an_html_only_email_is_read_as_text() -> None:
    loaded = load_bytes(
        "note.eml",
        _email(html="<p>Le budget <b>2027</b> est gelé.</p><script>x</script>"),
    )

    assert "Le budget 2027 est gelé." in loaded.text
    assert "<b>" not in loaded.text and "script" not in loaded.text


def test_the_command_line_reads_an_email_through_its_reader() -> None:
    text, _ = read_document_text("mail.eml", _email())

    assert text.startswith("Objet : Renouvellement ACME")


def test_an_email_brings_its_supported_attachments() -> None:
    raw = _email(
        attachments=(
            ("plafonds.csv", b"client,plafond\nACME,50000\n"),
            ("compte-rendu.md", b"# CR\n\nACME signe."),
            ("photo.jpg", b"\xff\xd8\xff"),
            ("archive.zip", b"PK"),
        )
    )

    items = unpack("mail.eml", raw)

    assert [i.filename for i in items] == [
        "mail.eml",
        "mail — plafonds.csv",
        "mail — compte-rendu.md",
    ]
    assert all(i.origin == "mail.eml" for i in items[1:])


# --- Notes --------------------------------------------------------------------


def test_obsidian_markup_reads_as_prose() -> None:
    text, notes = note_text(
        "---\ntitle: Réunion ACME\ntags: [client]\n---\n"
        "Avec [[Alice Martin|Alice]] et [[Bob]], voir [[Contrats#2027]].\n"
        "![[schema.png]]\n> [!warning] Le budget est gelé.\n"
    )

    assert text.startswith("# Réunion ACME")
    assert "Avec Alice et Bob, voir Contrats." in text
    assert "schema.png" not in text and "[!warning]" not in text
    assert "> Le budget est gelé." in text
    assert notes == ["Propriétés de la note retirées."]


def test_a_markdown_file_goes_through_the_note_reader() -> None:
    loaded = load_bytes("Alice.md", b"Elle dirige [[ACME]].")

    assert loaded.text == "Elle dirige ACME." and loaded.media_type == "text/markdown"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Export/Réunion ACME 0123456789abcdef0123456789abcdef.md", "Réunion ACME.md"),
        ("Clients 0123456789abcdef0123456789abcdef.csv", "Clients.csv"),
        ("dossier\\note.md", "note.md"),
        ("plain.md", "plain.md"),
    ],
)
def test_member_names_lose_folders_and_notion_ids(path: str, expected: str) -> None:
    assert display_name(path) == expected


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_notion_export_zip_yields_its_notes_and_tables() -> None:
    raw = _zip(
        {
            "Workspace/Projet 0123456789abcdef0123456789abcdef.md": b"# Projet",
            "Workspace/Clients 0123456789abcdef0123456789abcdef.csv": b"a,b\n1,2\n",
            "Workspace/image.png": b"\x89PNG",
            "__MACOSX/Workspace/._Projet.md": b"junk",
            "Workspace/.hidden.md": b"secret",
            "Workspace/inner.zip": _zip({"x.md": b"x"}),
        }
    )

    items = unpack("Export.zip", raw)

    assert [(i.filename, i.origin) for i in items] == [
        ("Projet.md", "Export.zip"),
        ("Clients.csv", "Export.zip"),
    ]


def test_a_broken_zip_says_so() -> None:
    with pytest.raises(DocumentReadError, match="archive"):
        unpack("export.zip", b"not a zip")


def test_a_zip_is_not_read_as_one_text() -> None:
    with pytest.raises(DocumentReadError, match="ontology import"):
        load_bytes("export.zip", _zip({"a.md": b"a"}))


def test_a_vault_walk_skips_hidden_and_tool_folders(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    for name in (
        "Clients/ACME.md",
        "Clients/budget.xlsx",
        ".obsidian/workspace.json",
        ".trash/old.md",
        "node_modules/pkg/readme.md",
        "image.png",
        ".DS_Store",
        "Inbox.md",
    ):
        path = vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    home = vault / "studio-home"
    (home / "projects" / "p1").mkdir(parents=True)
    (home / "projects" / "p1" / "upload.md").write_bytes(b"x")

    found = [p.relative_to(vault).as_posix() for p in walk(vault, exclude=home)]

    assert found == ["Inbox.md", "Clients/ACME.md", "Clients/budget.xlsx"]


# --- Duplicate content ------------------------------------------------------------


def _ingest(store: ProjectStore, loaded: object, *, label: str, force: bool = False):
    events: list[dict[str, object]] = []
    project = store.current() or store.create("Test")
    ingest_document(
        store,
        project,
        loaded,  # type: ignore[arg-type]
        config=resolve_llm_config(store),
        llm=FakeLLM(),
        model_label=label,
        force=force,
        cancel_event=None,
        on_event=events.append,
    )
    return store.current(), events


def test_the_chunk_count_is_saved_before_the_first_answer(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Livre")
    seen: list[tuple[str, int]] = []

    def on_event(event: dict[str, object]) -> None:
        if event["type"] == "chunk" and event["status"] == "started":
            saved = store.load(project.id).documents[-1]
            seen.append((saved.status, saved.chunks_total))

    ingest_document(
        store,
        project,
        load_bytes("livre.txt", SAMPLE_TEXT.encode()),
        config=resolve_llm_config(store),
        llm=FakeLLM(),
        model_label="démonstration",
        force=False,
        cancel_event=None,
        on_event=on_event,
    )

    assert seen and seen[0] == ("running", 1)


def test_the_same_text_under_another_name_is_not_extracted_twice(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    _ingest(store, load_bytes("biblio.txt", SAMPLE_TEXT.encode()), label="a")

    # Same text, reflowed, pasted, and read by another model.
    reflowed = "\n\n".join(" ".join(p.split()) for p in SAMPLE_TEXT.split("\n\n"))
    project, events = _ingest(store, load_text("colle.txt", reflowed), label="b")

    assert [d.filename for d in project.documents] == ["biblio.txt"]
    assert events[-1]["type"] == "duplicate"
    assert "biblio.txt" in str(events[-1]["message"])

    project, _ = _ingest(store, load_text("colle.txt", reflowed), label="b", force=True)
    assert [d.filename for d in project.documents] == ["colle.txt"]


def test_an_incomplete_extraction_is_run_again_without_forcing(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    loaded = load_bytes("biblio.txt", SAMPLE_TEXT.encode())
    project, _ = _ingest(store, loaded, label="a")
    project.documents[0].status = "incomplete"
    project.documents[0].chunks_failed = [1]
    store.save(project)

    project, events = _ingest(store, loaded, label="a")

    assert not any(e["type"] == "duplicate" for e in events)
    assert len(project.documents) == 1 and project.documents[0].status == "ok"


# --- Journal and brief ----------------------------------------------------------


def _source(store: ProjectStore):
    return lambda: (resolve_llm_config(store), FakeLLM(), "démonstration")


def test_each_arrival_is_journaled_and_reaches_the_brief(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Suivi")
    model = _source(store)
    item = Item("biblio.txt", SAMPLE_TEXT.encode())

    first = ingest_item(store, project.id, item, model=model)
    again = ingest_item(store, project.id, Item("copie.txt", item.data), model=model)
    table = ingest_item(store, project.id, Item("t.csv", b"a,b\n1,2\n"), model=model)
    broken = ingest_item(store, project.id, Item("abime.xlsx", b"nope"), model=model)
    no_model = ingest_item(
        store, project.id, Item("n.txt", b"Texte."), model=lambda: None
    )

    assert first.kind == "document" and first.facts > 0
    assert again.kind == "duplicate"
    assert table.kind == "table" and "table t (1 lignes)" in table.detail
    assert broken.kind == "error"
    assert no_model.kind == "skipped"
    folder = store.project_dir(project.id)
    assert [e.kind for e in read_journal(folder)] == [
        "document",
        "duplicate",
        "table",
        "error",
        "skipped",
    ]

    report = brief(store.load(project.id), _HOUR_AGO, read_journal(folder, _HOUR_AGO))
    text = report.markdown()
    assert report.duplicates == ["copie.txt"]
    assert "1 fichier(s) déjà connu(s), ignoré(s) : copie.txt." in text
    assert any(a.startswith("abime.xlsx : ") for a in report.alerts)
    assert any("aucun modèle configuré" in a for a in report.alerts)
    assert read_journal(folder, datetime.now(timezone.utc) + timedelta(hours=1)) == []


def test_a_torn_journal_line_is_ignored(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Suivi")
    ingest_item(store, project.id, Item("t.csv", b"a\n1\n"), model=lambda: None)
    journal = store.project_dir(project.id) / "activity.jsonl"
    journal.write_text(journal.read_text() + '{"filename": "cut', encoding="utf-8")

    assert len(read_journal(store.project_dir(project.id))) == 1


def test_import_reads_a_vault_an_email_and_reports_duplicates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "app.json").write_text("{}")
    (vault / "Bibliothèque.md").write_text(SAMPLE_TEXT, encoding="utf-8")
    mail = tmp_path / "relance.eml"
    mail.write_bytes(
        _email(attachments=(("plafonds.csv", b"client,plafond\nACME,1\n"),))
    )
    home = tmp_path / "home"

    assert (
        studio.main(["import", str(vault), str(mail), "--fake", "--home", str(home)])
        == 0
    )
    out = capsys.readouterr().out
    assert "Bibliothèque.md → " in out and "nouveaux faits" in out
    assert "relance — plafonds.csv (de relance.eml) → table" in out

    assert studio.main(["import", str(vault), "--fake", "--home", str(home)]) == 0
    assert "déjà dans le projet, ignoré" in capsys.readouterr().out

    assert studio.main(["brief", "--since", "1h", "--home", str(home)]) == 0
    assert "déjà connu(s), ignoré(s) : Bibliothèque.md" in capsys.readouterr().out


def test_import_of_only_unreadable_files_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "export.zip"
    broken.write_bytes(b"not a zip")

    assert studio.main(["import", str(broken), "--home", str(tmp_path / "h")]) == 1
    assert "export.zip → " in capsys.readouterr().err


def test_the_watcher_reads_sub_folders_and_journals(tmp_path: Path) -> None:
    from auto_ontology.text_ontology import watch

    home = tmp_path / "home"
    inbox = tmp_path / "Inbox"
    (inbox / "Clients").mkdir(parents=True)
    (inbox / "Clients" / "acme.eml").write_bytes(_email())

    class Studio:
        store = ProjectStore(home)
        fake = True

    Studio.store.save_settings(
        Studio.store.settings().model_copy(update={"watch_dir": str(inbox)})
    )
    seen: set[tuple[str, int]] = set()

    watch._scan(Studio(), seen)
    watch._scan(Studio(), seen)  # unchanged: not read again

    project = Studio.store.current()
    assert [d.filename for d in project.documents] == ["acme.eml"]
    journal = read_journal(Studio.store.project_dir(project.id))
    assert [(e.filename, e.kind) for e in journal] == [("acme.eml", "document")]
