# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What arrives in a project, and a journal of it.

One path for every way a file comes in (``ontology import``, the watched
folder): an email brings its attachments, a zip (a Notion export) brings its
notes, a spreadsheet becomes a table, anything else is extracted. Each arrival,
skipped duplicates and failures included, is written to ``activity.jsonl`` in
the project folder, which ``ontology brief`` reads back.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from auto_ontology.text_ontology.documents import (
    DOCUMENT_SUFFIXES,
    DocumentReadError,
    archive_members,
    email_attachments,
    load_bytes,
)
from auto_ontology.text_ontology.tables import TableError, import_tabular, is_tabular

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from auto_ontology.text_ontology.llm_settings import LlmConfig
    from auto_ontology.text_ontology.store import ProjectStore

logger = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = frozenset({".zip"})
JOURNAL_FILE = "activity.jsonl"
# The journal keeps the last entries only: it is a daily log, not an archive.
_JOURNAL_KEEP = 2000
# Folders a notes vault keeps for itself, never content.
_SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__", "_resources"})
_MAX_DEPTH = 6

Kind = Literal["document", "table", "duplicate", "skipped", "error"]
# Called once, when the first document needs a model: (config, llm, label),
# or ``None`` when no model is configured.
ModelSource = Callable[[], "tuple[LlmConfig, BaseChatModel, str] | None"]


@dataclass(frozen=True)
class Item:
    """One file to bring in, and the email or archive it came from."""

    filename: str
    data: bytes
    origin: str = ""


@dataclass(frozen=True)
class Outcome:
    """What happened to one item. ``detail`` is for the person."""

    filename: str
    kind: Kind
    detail: str
    facts: int = 0
    origin: str = ""
    at: str = ""

    def line(self) -> str:
        source = f" (de {self.origin})" if self.origin else ""
        return f"{self.filename}{source} → {self.detail}"


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def accepts(filename: str) -> bool:
    """A file the studio can bring in: document, table, email or archive."""
    suffix = _suffix(filename)
    return (
        is_tabular(filename)
        or suffix in DOCUMENT_SUFFIXES
        or suffix in ARCHIVE_SUFFIXES
    )


def unpack(filename: str, data: bytes) -> list[Item]:
    """*filename* and what it carries.

    A zip yields its supported members (not nested archives). An email yields
    itself, then each supported attachment named after the message.
    """
    suffix = _suffix(filename)
    if suffix in ARCHIVE_SUFFIXES:
        members = archive_members(
            data, lambda name: accepts(name) and _suffix(name) not in ARCHIVE_SUFFIXES
        )
        items: list[Item] = []
        for member in members:
            for item in unpack(member.filename, member.data):
                items.append(Item(item.filename, item.data, item.origin or filename))
        return items
    items = [Item(filename, data)]
    if suffix == ".eml":
        stem = filename[: -len(suffix)]
        for attachment in email_attachments(data):
            if accepts(attachment.filename) and not attachment.filename.endswith(
                tuple(ARCHIVE_SUFFIXES)
            ):
                items.append(
                    Item(f"{stem} — {attachment.filename}", attachment.data, filename)
                )
    return items


def walk(
    folder: Path, *, exclude: Path | None = None, max_depth: int = _MAX_DEPTH
) -> Iterator[Path]:
    """Supported files under *folder*, as in a notes vault.

    Hidden folders (``.obsidian``, ``.trash``, ``.git``) and tool folders are
    skipped; the walk stops *max_depth* levels down. *exclude* (the studio's
    own home) is never entered: a watched folder that contains it would
    otherwise import the studio's stored uploads again, forever.
    """
    skip = exclude.resolve() if exclude is not None else None
    base_depth = len(folder.parts)
    for root, dirs, files in os.walk(folder):
        here = Path(root)
        depth = len(here.parts) - base_depth
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and d not in _SKIPPED_FOLDERS
            and depth < max_depth
            and (skip is None or (here / d).resolve() != skip)
        )
        if skip is not None and here.resolve() == skip:
            continue
        for name in sorted(files):
            if not name.startswith(".") and accepts(name):
                yield here / name


def ingest_item(
    store: ProjectStore,
    project_id: str,
    item: Item,
    *,
    model: ModelSource,
    force: bool = False,
) -> Outcome:
    """Bring *item* into the project and journal what happened."""
    outcome = _ingest(store, project_id, item, model=model, force=force)
    record(store.project_dir(project_id), outcome)
    return outcome


def _ingest(
    store: ProjectStore,
    project_id: str,
    item: Item,
    *,
    model: ModelSource,
    force: bool,
) -> Outcome:
    from auto_ontology.text_ontology.pipeline import IngestError, ingest_document

    def done(kind: Kind, detail: str, facts: int = 0) -> Outcome:
        return Outcome(item.filename, kind, detail, facts, item.origin, _now())

    project = store.load(project_id)
    if is_tabular(item.filename):
        known = {d.sha256 for d in project.datasets}
        try:
            records = import_tabular(store, project, item.filename, item.data)
        except TableError as exc:
            return done("error", str(exc))
        if records and all(r.sha256 in known for r in records):
            return done("duplicate", "déjà chargé, inchangé")
        tables = ", ".join(f"table {r.table} ({r.rows} lignes)" for r in records)
        return done("table", tables or "aucune table lisible")
    try:
        loaded = load_bytes(item.filename, item.data)
    except DocumentReadError as exc:
        return done("error", str(exc))
    if not loaded.text.strip():
        return done("skipped", "pas de texte exploitable")
    resolved = model()
    if resolved is None:
        return done("skipped", "aucun modèle configuré (réglages du studio)")
    config, llm, label = resolved
    before = len(project.ontology.triplets) + len(project.ontology.attributes)
    events: list[dict[str, object]] = []
    try:
        ingest_document(
            store,
            project,
            loaded,
            config=config,
            llm=llm,
            model_label=label,
            force=force,
            cancel_event=None,
            on_event=events.append,
        )
    except IngestError as exc:
        return done("error", str(exc))
    duplicate = next((e for e in events if e.get("type") == "duplicate"), None)
    if duplicate is not None:
        return done("duplicate", "déjà dans le projet, ignoré")
    project = store.load(project_id)
    facts = len(project.ontology.triplets) + len(project.ontology.attributes) - before
    return done("document", f"{max(facts, 0)} nouveaux faits", max(facts, 0))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unreadable(project_dir: Path, filename: str, reason: str) -> Outcome:
    """Journal a file that could not even be opened."""
    outcome = Outcome(filename, "error", reason, at=_now())
    record(project_dir, outcome)
    return outcome


# --- Journal -----------------------------------------------------------------


def record(project_dir: Path, outcome: Outcome) -> None:
    """Append *outcome* to the project's journal. Never fails the import."""
    path = project_dir / JOURNAL_FILE
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(outcome), ensure_ascii=False) + "\n")
        if path.stat().st_size > _JOURNAL_KEEP * 400:
            _trim(path)
    except OSError:
        logger.warning("The activity journal of %s could not be written", project_dir)


def _trim(path: Path) -> None:
    from auto_ontology.text_ontology.store import atomic_write_text

    lines = path.read_text(encoding="utf-8").splitlines()[-_JOURNAL_KEEP:]
    atomic_write_text(path, "\n".join(lines) + "\n")


def read_journal(project_dir: Path, since: datetime | None = None) -> list[Outcome]:
    """The journal's entries, oldest first, from *since* on when given."""
    path = project_dir / JOURNAL_FILE
    if not path.is_file():
        return []
    entries: list[Outcome] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
            entry = Outcome(**raw)
            moment = datetime.fromisoformat(entry.at)
        except (ValueError, TypeError):
            continue  # a line cut by a crash, or from a later version
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if since is None or moment >= since:
            entries.append(entry)
    return entries
