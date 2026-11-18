# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Daily use: what is new (``brief``), what changed (``diff``), the clipboard.

``brief`` answers "what came in, and what needs a look?": documents and
tables added since a moment, the facts and entities they brought, then
alerts (files that could not be read or had no model, chunks that failed,
incomplete or cancelled extractions, classes with several parents, entities
linked to nothing). Skipped duplicates come from the activity journal.

``diff`` answers "what changed since then?" by comparing the project with
the snapshot the studio kept just before that moment (the same snapshots
undo uses). Only the last snapshots are kept, so a moment older than the
oldest one is compared with that one, and the result says so.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_ontology.text_ontology.normalize import entity_key, multi_parent_summary
from auto_ontology.text_ontology.studio_models import Project

if TYPE_CHECKING:
    from auto_ontology.text_ontology.inbox import Outcome

_PERIOD = re.compile(r"^\s*(\d+)\s*(m|min|h|d|j|w|s)\s*$", re.IGNORECASE)
_UNITS = {
    "m": timedelta(minutes=1),
    "min": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "j": timedelta(days=1),
    "w": timedelta(weeks=1),
    "s": timedelta(weeks=1),
}
_SHOWN = 10


def parse_since(text: str, now: datetime | None = None) -> datetime:
    """``24h``, ``7d`` (or ``7j``), ``2w``, ``today``, ``yesterday``, or a date.

    Raises ``ValueError`` with a usable message otherwise.
    """
    now = now or datetime.now(timezone.utc)
    value = text.strip().lower()
    if value in {"today", "aujourd'hui", "aujourdhui"}:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if value in {"yesterday", "hier"}:
        return (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    match = _PERIOD.match(value)
    if match:
        return now - int(match.group(1)) * _UNITS[match.group(2).lower()]
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(
            f"Période illisible : {text!r}. Exemples : 24h, 7d, 2w, today, 2026-11-01."
        ) from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _since_text(moment: datetime) -> str:
    return moment.astimezone().strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# brief
# ---------------------------------------------------------------------------


@dataclass
class Brief:
    project: str
    since: datetime
    documents: list[dict[str, object]] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    new_facts: int = 0
    top_entities: list[tuple[str, int]] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    # From the activity journal: files skipped as already known.
    duplicates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "since": self.since.isoformat(),
            "documents": self.documents,
            "tables": self.tables,
            "new_facts": self.new_facts,
            "top_entities": [{"name": n, "facts": c} for n, c in self.top_entities],
            "rules": self.rules,
            "alerts": self.alerts,
            "duplicates": self.duplicates,
        }

    def markdown(self) -> str:
        lines = [
            f"# Brief — {self.project}",
            "",
            f"Depuis le {_since_text(self.since)}.",
            "",
        ]
        lines.append("## Nouveautés")
        if not (self.documents or self.tables):
            lines.append("- Rien de nouveau.")
        for doc in self.documents:
            lines.append(f"- Document **{doc['filename']}** : {doc['facts']} faits")
        for table in self.tables:
            lines.append(
                f"- Table **{table['table']}** : {table['rows']} lignes ({table['source']})"
            )
        if self.new_facts:
            lines.append(f"- {self.new_facts} faits apportés au total.")
        if self.duplicates:
            shown = ", ".join(self.duplicates[:_SHOWN])
            more = " …" if len(self.duplicates) > _SHOWN else ""
            lines.append(
                f"- {len(self.duplicates)} fichier(s) déjà connu(s), ignoré(s) : "
                f"{shown}{more}."
            )
        if self.top_entities:
            names = ", ".join(f"{name} ({count})" for name, count in self.top_entities)
            lines.append(f"- Entités les plus citées : {names}.")
        if self.rules:
            lines += ["", "## Règles et décisions certifiées"]
            lines += [f"- {rule}" for rule in self.rules]
        lines += ["", "## À vérifier"]
        lines += [f"- {alert}" for alert in self.alerts] or ["- Rien à signaler."]
        return "\n".join(lines) + "\n"


def brief(
    project: Project,
    since: datetime,
    journal: Sequence[Outcome] = (),
    extra_alerts: Sequence[str] = (),
) -> Brief:
    """What *project* gained since *since*, and what deserves a look.

    *journal* is the activity journal from *since* on (see
    :func:`inbox.read_journal`): it adds what was skipped or failed, which
    the project itself does not remember. *extra_alerts* come first (the
    playbook's findings, see :func:`playbooks.playbook_alerts`).
    """
    new_documents = [
        d for d in project.documents if (_moment(d.added_at) or since) >= since
    ]
    new_ids = {d.id for d in new_documents}
    facts_per_document: Counter[str] = Counter()
    entity_mentions: Counter[str] = Counter()
    spelled: dict[str, str] = {}
    new_facts = 0
    for item in (*project.triplets, *project.attributes):
        from_new = {s.document_id for s in item.sources} & new_ids
        if not from_new:
            continue
        new_facts += 1
        for document_id in from_new:
            facts_per_document[document_id] += 1
        names = (
            (item.subject, item.object) if hasattr(item, "subject") else (item.entity,)
        )  # type: ignore[attr-defined]
        for name in names:
            key = entity_key(name)
            spelled.setdefault(key, name)
            entity_mentions[key] += 1
    result = Brief(project=project.name, since=since, new_facts=new_facts)
    result.documents = [
        {
            "filename": d.filename,
            "added_at": d.added_at,
            "facts": facts_per_document[d.id],
        }
        for d in new_documents
    ]
    result.tables = [
        {"table": t.table, "rows": t.rows, "source": t.source, "added_at": t.added_at}
        for t in project.datasets
        if (_moment(t.added_at) or since) >= since
    ]
    result.top_entities = [
        (spelled[key], count) for key, count in entity_mentions.most_common(5)
    ]
    result.rules = [
        rule.text + (f" — {rule.source}" if rule.source else "")
        for rule in project.rules
        if rule.status == "certified" and (_moment(rule.created_at) or since) >= since
    ]
    result.alerts = [
        *(
            f"{entry.filename} : {entry.detail}"
            + (f" (reçu de {entry.origin})" if entry.origin else "")
            for entry in journal
            if entry.kind in {"error", "skipped"}
        ),
        *extra_alerts,
        *_alerts(project),
    ]
    result.duplicates = list(
        dict.fromkeys(e.filename for e in journal if e.kind == "duplicate")
    )
    return result


def _alerts(project: Project) -> list[str]:
    alerts = []
    for document in project.documents:
        if document.chunks_failed:
            alerts.append(
                f"{document.filename} : {len(document.chunks_failed)} morceau(x) sans "
                "réponse du modèle, faits manquants (relancez l'import)."
            )
        for warning in document.warnings:
            if warning.startswith(("INCOMPLETE", "CANCELLED")):
                alerts.append(f"{document.filename} : extraction incomplète.")
                break
    summary = multi_parent_summary(project.ontology)
    if summary:
        alerts.append(summary)
    linked = {entity_key(t.subject) for t in project.ontology.triplets} | {
        entity_key(t.object) for t in project.ontology.triplets
    }
    orphans = sorted(
        {
            a.entity
            for a in project.ontology.attributes
            if entity_key(a.entity) not in linked
        }
    )
    if orphans:
        shown = ", ".join(orphans[:_SHOWN]) + (" …" if len(orphans) > _SHOWN else "")
        alerts.append(f"{len(orphans)} entité(s) reliée(s) à rien : {shown}.")
    return alerts


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@dataclass
class Diff:
    project: str
    since: datetime
    baseline_at: datetime | None
    note: str = ""
    added: dict[str, list[str]] = field(default_factory=dict)
    removed: dict[str, list[str]] = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            any(self.added.values())
            or any(self.removed.values())
            or self.documents
            or self.tables
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "since": self.since.isoformat(),
            "baseline_at": self.baseline_at.isoformat() if self.baseline_at else None,
            "note": self.note,
            "added": self.added,
            "removed": self.removed,
            "documents": self.documents,
            "tables": self.tables,
        }

    def markdown(self) -> str:
        lines = [
            f"# Ce qui a changé — {self.project}",
            "",
            f"Depuis le {_since_text(self.since)}.",
        ]
        if self.note:
            lines += ["", f"_{self.note}_"]
        if self.documents or self.tables:
            lines += ["", "## Sources ajoutées"]
            lines += [f"- {name}" for name in self.documents]
            lines += [f"- table {name}" for name in self.tables]
        labels = {"classes": "Classes", "facts": "Faits", "attributes": "Attributs"}
        for kind, label in labels.items():
            added, removed = self.added.get(kind, []), self.removed.get(kind, [])
            if not (added or removed):
                continue
            lines += ["", f"## {label} (+{len(added)} / -{len(removed)})"]
            lines += [f"- + {item}" for item in added[: _SHOWN * 3]]
            lines += [f"- − {item}" for item in removed[: _SHOWN * 3]]
        if self.empty:
            lines += ["", "Aucun changement."]
        return "\n".join(lines) + "\n"


def _facts_of(project: Project | None) -> dict[str, set[str]]:
    if project is None:
        return {"classes": set(), "facts": set(), "attributes": set()}
    ontology = project.ontology
    return {
        "classes": {c.name for c in ontology.classes},
        "facts": {f"{t.subject} {t.predicate} {t.object}" for t in ontology.triplets},
        "attributes": {f"{a.entity}.{a.key} = {a.value}" for a in ontology.attributes},
    }


def snapshot_before(
    project_dir: Path, moment: datetime
) -> tuple[Project | None, datetime | None, bool]:
    """The newest snapshot taken at or before *moment*.

    Returns (project, taken_at, exact): when every snapshot is newer than
    *moment*, the oldest one is returned with ``exact`` False.
    """
    files = sorted((Path(project_dir) / "history").glob("*.json"))
    dated = []
    for path in files:
        try:
            taken = datetime.fromtimestamp(int(path.stem) / 1e9, tz=timezone.utc)
        except ValueError:
            continue
        dated.append((taken, path))
    if not dated:
        return None, None, False
    before = [(t, p) for t, p in dated if t <= moment]
    taken, path, exact = (*before[-1], True) if before else (*dated[0], False)
    try:
        return (
            Project.model_validate(json.loads(path.read_text(encoding="utf-8"))),
            taken,
            exact,
        )
    except (OSError, ValueError):
        return None, None, False


def diff(project: Project, project_dir: Path, since: datetime) -> Diff:
    """What changed in *project* since *since*, against the snapshot then."""
    baseline, taken, exact = snapshot_before(project_dir, since)
    result = Diff(project=project.name, since=since, baseline_at=taken)
    if baseline is None:
        # No snapshot: everything brought by the documents added since counts.
        result.note = (
            "Aucun instantané plus ancien : est compté comme ajouté ce qu'ont "
            "apporté les documents ajoutés depuis."
        )
        new_ids = {
            d.id for d in project.documents if (_moment(d.added_at) or since) >= since
        }
        result.added = {
            "classes": sorted(
                c.name
                for c in project.classes
                if {s.document_id for s in c.sources} & new_ids
            ),
            "facts": sorted(
                f"{t.subject} {t.predicate} {t.object}"
                for t in project.triplets
                if {s.document_id for s in t.sources} <= new_ids and t.sources
            ),
            "attributes": sorted(
                f"{a.entity}.{a.key} = {a.value}"
                for a in project.attributes
                if {s.document_id for s in a.sources} <= new_ids and a.sources
            ),
        }
        result.removed = {"classes": [], "facts": [], "attributes": []}
    else:
        if not exact and taken is not None:
            result.note = (
                f"L'historique conservé commence le {_since_text(taken)} : "
                "la comparaison part de là."
            )
        before, after = _facts_of(baseline), _facts_of(project)
        result.added = {kind: sorted(after[kind] - before[kind]) for kind in before}
        result.removed = {kind: sorted(before[kind] - after[kind]) for kind in before}
    result.documents = [
        d.filename for d in project.documents if (_moment(d.added_at) or since) >= since
    ]
    result.tables = [
        t.table for t in project.datasets if (_moment(t.added_at) or since) >= since
    ]
    return result


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------


class ClipboardError(RuntimeError):
    """No clipboard tool is available, or it failed."""


def _clipboard_commands() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbpaste"]]
    if sys.platform.startswith("win"):
        return [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    return [
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ]


def read_clipboard() -> str:
    """The clipboard's text, through the system's own tool (no dependency).

    macOS ``pbpaste``; Windows PowerShell ``Get-Clipboard``; Linux
    ``wl-paste``, ``xclip`` or ``xsel``, the first one installed.
    """
    tried = []
    for command in _clipboard_commands():
        if shutil.which(command[0]) is None:
            tried.append(command[0])
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argument lists
                command, capture_output=True, timeout=5, check=True
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ClipboardError(
                f"Le presse-papiers n'a pas pu être lu ({command[0]}) : {exc}"
            ) from exc
        text = completed.stdout.decode("utf-8", errors="replace")
        if not text.strip():
            raise ClipboardError("Le presse-papiers est vide.")
        return text
    raise ClipboardError(
        "Aucun outil de presse-papiers trouvé (" + ", ".join(tried) + "). "
        "Sous Linux, installez wl-clipboard ou xclip."
    )


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
