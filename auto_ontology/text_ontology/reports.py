# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reports built from the facts alone, with no model call.

``meeting``: one document's facts sorted into participants, decisions,
actions, figures and dates, each with the passage it came from: the skeleton
of a meeting summary that an assistant can then phrase. ``comparison``: a
table of what the project knows about a few entities, side by side.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from auto_ontology.text_ontology.normalize import entity_key
from auto_ontology.text_ontology.profile import GENRE_LABELS_FR
from auto_ontology.text_ontology.studio_models import DocumentRecord, Project

_PERSON = re.compile(
    r"personne|person|participant|employ|membre|member|people|humain|human"
    r"|collaborat|salari|contact|client|responsable|manager|directeur|director",
    re.IGNORECASE,
)
_DECISION = re.compile(
    r"d[ée]cid|valid|approuv|approv|choisi|chose|adopt|retien|accept|refus|reject"
    r"|rejet|sign|renouvel|renew|g[eè]le|freez|arr[eê]t|fix[ea]|vot|conclu|agree",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"doit|devra|must|charg|responsab|assign|livr|deliver|pr[ée]par|envo|send"
    r"|organis|planifi|schedul|relanc|follow|contact|r[ée]dig|draft|pr[ée]sent",
    re.IGNORECASE,
)
_FIGURE = re.compile(r"\d")
_SHOWN = 40


class ReportError(ValueError):
    """The report cannot be built. The message says what is missing."""


@dataclass
class Report:
    title: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    data: dict[str, object] = field(default_factory=dict)
    table: str = ""
    # Said before the sections: why the report may say little.
    note: str = ""

    def markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        if self.note:
            lines += [f"> {self.note}", ""]
        if self.table:
            lines += [self.table, ""]
        for heading, items in self.sections:
            lines.append(f"## {heading}")
            lines += [f"- {item}" for item in items] or ["- (rien)"]
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "note": self.note,
            **self.data,
            "markdown": self.markdown(),
        }


def _document(project: Project, wanted: str | None) -> DocumentRecord:
    if not project.documents:
        raise ReportError("Le projet n'a encore aucun document.")
    if not wanted:
        return max(project.documents, key=lambda d: d.added_at)
    needle = wanted.casefold()
    matches = [
        d
        for d in project.documents
        if d.id == wanted or needle in d.filename.casefold()
    ]
    if not matches:
        names = ", ".join(d.filename for d in project.documents[-10:])
        raise ReportError(f"Aucun document ne correspond à « {wanted} » ({names}).")
    return max(matches, key=lambda d: d.added_at)


def _quote(sources: list, document_id: str) -> str:
    for source in sources:
        if source.document_id == document_id and source.quote:
            quote = " ".join(source.quote.split())
            return f" — « {quote[:160]}{'…' if len(quote) > 160 else ''} »"
    return ""


def meeting(project: Project, document: str | None = None) -> Report:
    """Facts of one document (the latest by default), sorted for a summary."""
    record = _document(project, document)
    types = {
        entity_key(t.subject): t.subject_type for t in project.ontology.triplets
    } | {entity_key(t.object): t.object_type for t in project.ontology.triplets}
    parents = {c.name: c.parent for c in project.ontology.classes}

    def is_person(name: str) -> bool:
        kind: str | None = types.get(entity_key(name), "")
        for _ in range(8):  # up the hierarchy: Employé → Personne
            if not kind:
                return False
            if _PERSON.search(kind):
                return True
            kind = parents.get(kind)
        return False

    participants: Counter[str] = Counter()
    decisions: list[str] = []
    actions: list[str] = []
    others: list[str] = []
    for item in project.triplets:
        if not any(s.document_id == record.id for s in item.sources):
            continue
        for name in (item.subject, item.object):
            if is_person(name):
                participants[name] += 1
        line = f"{item.subject} {item.predicate} {item.object}"
        line += _quote(item.sources, record.id)
        if item.predicate in {"est_un", "is_a"}:
            continue
        if _DECISION.search(item.predicate):
            decisions.append(line)
        elif _ACTION.search(item.predicate):
            actions.append(line)
        else:
            others.append(line)
    figures = [
        f"{a.entity} · {a.key.replace('_', ' ')} : {a.value}"
        + _quote(a.sources, record.id)
        for a in project.attributes
        if any(s.document_id == record.id for s in a.sources)
        and _FIGURE.search(a.value)
    ]
    rules = [
        f"{rule.text} (règle certifiée)"
        for rule in project.rules
        if rule.status == "certified"
        and record.filename.casefold() in rule.source.casefold()
    ]
    report = Report(title=f"Compte rendu — {record.filename}")
    report.sections = [
        ("Participants", [name for name, _ in participants.most_common()]),
        ("Décisions", [*rules, *decisions][:_SHOWN]),
        ("Actions", actions[:_SHOWN]),
        ("Chiffres et dates", figures[:_SHOWN]),
        ("Autres faits", others[:_SHOWN]),
    ]
    report.data = {
        "document": record.filename,
        "added_at": record.added_at,
        "participants": list(participants),
        "decisions": [*rules, *decisions],
        "actions": actions,
        "figures": figures,
        "other_facts": others,
    }
    if record.date:
        report.sections.insert(0, ("Date", [record.date]))
    report.note = _meeting_note(record)
    return report


# Kinds of document that are not a meeting: the report fits them poorly.
_NOT_MEETINGS = {"book_chapter", "scientific_paper", "contract", "financial_statement"}


def _meeting_note(record: DocumentRecord) -> str:
    if record.status == "running":
        return (
            "Extraction en cours : les faits de ce document n'y figurent qu'une "
            "fois l'extraction terminée."
        )
    if record.status == "failed":
        return "L'extraction de ce document a échoué : relancez son import."
    if record.genre in _NOT_MEETINGS:
        kind = GENRE_LABELS_FR.get(record.genre, record.genre).lower()
        return (
            f"Ce document ressemble à un(e) {kind}, pas à une réunion : "
            "`ontology ask` et `ontology brief` lui conviennent mieux."
        )
    return ""


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def comparison(project: Project, names: list[str]) -> Report:
    """What the project says about each of *names*, one column each."""
    wanted = [name.strip() for name in names if name.strip()]
    if len(wanted) < 2:
        raise ReportError("Comparez au moins deux noms.")
    spelled: dict[str, str] = {}
    for t in project.ontology.triplets:
        spelled.setdefault(entity_key(t.subject), t.subject)
        spelled.setdefault(entity_key(t.object), t.object)
    for a in project.ontology.attributes:
        spelled.setdefault(entity_key(a.entity), a.entity)
    columns = [spelled.get(entity_key(name), "") for name in wanted]
    missing = [name for name, found in zip(wanted, columns) if not found]
    columns = [found for found in columns if found]
    if len(columns) < 2:
        raise ReportError(
            "Pas assez de noms connus du projet pour comparer : "
            + ", ".join(missing)
            + "."
        )
    keys = [entity_key(name) for name in columns]
    rows: dict[str, dict[str, list[str]]] = {}
    for a in project.ontology.attributes:
        key = entity_key(a.entity)
        if key in keys:
            row = rows.setdefault(a.key.replace("_", " "), {})
            row.setdefault(key, []).append(a.value)
    for t in project.ontology.triplets:
        key = entity_key(t.subject)
        if key in keys:
            label = "type" if t.predicate in {"est_un", "is_a"} else t.predicate
            row = rows.setdefault(label.replace("_", " "), {})
            row.setdefault(key, []).append(t.object)
    # Rows that several entities share first: that is where they compare.
    order = sorted(rows, key=lambda label: (-len(rows[label]), label))
    header = "| | " + " | ".join(_cell(name) for name in columns) + " |"
    lines = [header, "|---" * (len(columns) + 1) + "|"]
    for label in order:
        values = [
            _cell(", ".join(dict.fromkeys(rows[label].get(key, []))) or "—")
            for key in keys
        ]
        lines.append(f"| {_cell(label)} | " + " | ".join(values) + " |")
    report = Report(title="Comparaison — " + ", ".join(columns), table="\n".join(lines))
    if missing:
        report.sections.append(("Inconnus du projet", missing))
    report.data = {
        "entities": columns,
        "missing": missing,
        "rows": [
            {
                "key": label,
                "values": {
                    name: list(dict.fromkeys(rows[label].get(key, [])))
                    for name, key in zip(columns, keys)
                },
            }
            for label in order
        ],
    }
    return report
