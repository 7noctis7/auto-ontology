# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Playbooks: one kind of work, described once.

A playbook is a YAML file that says what a project is for (auditing
contracts, following figures, keeping a project's knowledge) and therefore:

- what the extraction should look for (``focus``, ``classes``,
  ``predicates``), added to every prompt of a project that uses it;
- which checks to run on the result (``checks``): an entity of a class
  without a required attribute or relation, a date coming up or past, an
  amount over a threshold, or any read-only SQL on tables and facts;
- which questions the project must answer (``questions``).

Three come with the studio; a file in ``<home>/playbooks/`` adds one or
replaces a bundled one of the same ``id``. Checks call no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from auto_ontology.text_ontology.normalize import ascii_fold, entity_key
from auto_ontology.text_ontology.studio_models import Project

BUNDLED = Path(__file__).with_name("playbooks")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
Severity = Literal["haute", "moyenne", "basse"]
_ORDER = {"haute": 0, "moyenne": 1, "basse": 2}


class PlaybookError(ValueError):
    """A playbook is missing or malformed. The message names the file."""


class Check(BaseModel):
    """One rule a project of this kind should satisfy."""

    id: str
    title: str
    kind: Literal[
        "missing_attribute",
        "missing_relation",
        "date_within",
        "date_past",
        "value_above",
        "sql",
    ]
    severity: Severity = "moyenne"
    classes: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    predicates: list[str] = Field(default_factory=list)
    days: int = Field(default=90, ge=1, le=3650)
    threshold: float | None = None
    sql: str = ""
    message: str = ""
    advice: str = ""


class Playbook(BaseModel):
    id: str
    name: str
    description: str = ""
    focus: str = ""
    classes: list[str] = Field(default_factory=list)
    predicates: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    origin: str = ""  # set when read: "intégré" or the file's path

    def guidance(self) -> str:
        """What the extraction prompt is told for a project of this kind."""
        lines = [f"Contexte du projet : {self.name}. {self.description}".strip()]
        if self.focus:
            lines.append(self.focus.strip())
        if self.predicates:
            lines.append(
                "Relations utiles, à réutiliser quand le texte les exprime : "
                + ", ".join(self.predicates)
                + "."
            )
        return "\n".join(lines)


def _read(path: Path, origin: str) -> Playbook:
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        playbook = Playbook.model_validate({**(raw or {}), "origin": origin})
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise PlaybookError(
            f"{path.name} n'est pas un playbook valable : {exc}"
        ) from exc
    if not _ID.match(playbook.id):
        raise PlaybookError(
            f"{path.name} : id « {playbook.id} » (lettres minuscules, chiffres, tirets)."
        )
    return playbook


def available(home: Path | None = None) -> dict[str, Playbook]:
    """Bundled playbooks, then the person's, which win on the same id.

    A malformed personal file is skipped, not fatal: the others still load.
    """
    found: dict[str, Playbook] = {}
    for path in sorted(BUNDLED.glob("*.yaml")):
        playbook = _read(path, "intégré")
        found[playbook.id] = playbook
    folder = home / "playbooks" if home is not None else None
    if folder is not None and folder.is_dir():
        for path in sorted(folder.glob("*.y*ml")):
            try:
                playbook = _read(path, str(path))
            except PlaybookError:
                continue
            found[playbook.id] = playbook
    return found


def get(playbook_id: str, home: Path | None = None) -> Playbook:
    found = available(home)
    if playbook_id not in found:
        names = ", ".join(sorted(found))
        raise PlaybookError(
            f"Playbook inconnu : {playbook_id} (disponibles : {names})."
        )
    return found[playbook_id]


def active(project: Project, home: Path | None = None) -> Playbook | None:
    """The playbook *project* uses, or ``None`` (also if it was removed)."""
    if not project.playbook:
        return None
    try:
        return get(project.playbook, home)
    except PlaybookError:
        return None


# --- Reading values ---------------------------------------------------------------

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}  # fmt: skip
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_WORDS = re.compile(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})\b")
_AMOUNT = re.compile(
    r"(-?\d[\d\s  .,]*)\s*(k|m|md|mds|millions?|milliards?|mille|bn|b)?\b"
)


def parse_date(value: str) -> date | None:
    """A day in *value*: 2027-03-31, 31/03/2027, 31 mars 2027, 1er April 2027."""
    text = ascii_fold(value).casefold()
    try:
        if match := _ISO.search(text):
            return date(int(match[1]), int(match[2]), int(match[3]))
        if match := _DMY.search(text):
            return date(int(match[3]), int(match[2]), int(match[1]))
        if (match := _WORDS.search(text)) and match[2] in _MONTHS:
            return date(int(match[3]), _MONTHS[match[2]], int(match[1]))
    except ValueError:
        return None  # 31/02/2027
    return None


def parse_amount(value: str) -> float | None:
    """A number in *value*: "50 000 €", "1,2 M€", "120k", "3 millions"."""
    text = ascii_fold(value).casefold().replace("€", " ").replace("$", " ")
    match = _AMOUNT.search(text)
    if not match:
        return None
    digits = re.sub(r"[\s  ]", "", match[1])
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")  # 1.200,50
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = f"{head}.{tail}" if len(tail) != 3 else head + tail
    elif digits.count(".") > 1 or re.search(r"\.\d{3}$", digits):
        digits = digits.replace(".", "")  # 1.200.000
    try:
        number = float(digits)
    except ValueError:
        return None
    scale = {"k": 1e3, "mille": 1e3, "m": 1e6, "million": 1e6, "millions": 1e6}
    scale |= {"md": 1e9, "mds": 1e9, "milliard": 1e9, "milliards": 1e9}
    scale |= {"bn": 1e9, "b": 1e9}
    return number * scale.get(match[2] or "", 1)


# --- Checks -------------------------------------------------------------------------


@dataclass
class Finding:
    check: str
    title: str
    severity: str
    entity: str
    detail: str
    advice: str = ""
    document: str = ""
    quote: str = ""


@dataclass
class CheckReport:
    playbook: str
    findings: list[Finding] = field(default_factory=list)
    checks: int = 0
    errors: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        found = {"haute": 0, "moyenne": 0, "basse": 0}
        for item in self.findings:
            found[item.severity] = found.get(item.severity, 0) + 1
        return found

    def summary(self) -> str:
        if not self.findings:
            return f"Playbook « {self.playbook} » : rien à signaler ({self.checks} contrôles)."
        high = self.counts()["haute"]
        return (
            f"Playbook « {self.playbook} » : {len(self.findings)} point(s) à vérifier"
            + (f", dont {high} de priorité haute" if high else "")
            + " — ontology check."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "checks": self.checks,
            "counts": self.counts(),
            "findings": [item.__dict__ for item in self.findings],
            "errors": self.errors,
            "summary": self.summary(),
        }

    def markdown(self) -> str:
        lines = [f"# Contrôles — {self.playbook}", "", self.summary(), ""]
        for severity in ("haute", "moyenne", "basse"):
            items = [f for f in self.findings if f.severity == severity]
            if not items:
                continue
            lines.append(f"## Priorité {severity} ({len(items)})")
            for item in items:
                line = f"- **{item.title}** — {item.entity} : {item.detail}"
                if item.document:
                    line += f" ({item.document})"
                lines.append(line)
                if item.advice:
                    lines.append(f"  - {item.advice}")
            lines.append("")
        if self.errors:
            lines += ["## Contrôles non exécutés", *[f"- {e}" for e in self.errors]]
        return "\n".join(lines).rstrip() + "\n"


def _members(project: Project, classes: list[str]) -> dict[str, str]:
    """Entities typed with one of *classes* or a subclass: key → spelling."""
    if not classes:
        return {}
    children: dict[str, list[str]] = {}
    for cls in project.ontology.classes:
        if cls.parent:
            children.setdefault(entity_key(cls.parent), []).append(cls.name)
    wanted: set[str] = set()
    pending = [entity_key(name) for name in classes]
    while pending:
        key = pending.pop()
        if key in wanted:
            continue
        wanted.add(key)
        pending += [entity_key(child) for child in children.get(key, [])]
    members: dict[str, str] = {}
    for t in project.ontology.triplets:
        for name, kind in ((t.subject, t.subject_type), (t.object, t.object_type)):
            if entity_key(kind) in wanted and entity_key(name) not in wanted:
                members.setdefault(entity_key(name), name)
    return members


def _source(project: Project, entity: str, key: str = "") -> tuple[str, str]:
    wanted = entity_key(entity)
    for item in project.attributes:
        if entity_key(item.entity) == wanted and (not key or item.key == key):
            if item.sources:
                return item.sources[0].filename, item.sources[0].quote
    for item in project.triplets:
        if entity_key(item.subject) == wanted and item.sources:
            return item.sources[0].filename, item.sources[0].quote
    return "", ""


def _attribute_values(project: Project, keys: list[str]) -> list[tuple[str, str, str]]:
    wanted = {k.casefold() for k in keys}
    return [
        (a.entity, a.key, a.value)
        for a in project.ontology.attributes
        if a.key.casefold() in wanted
    ]


def run_checks(
    project: Project,
    playbook: Playbook,
    project_dir: Path | None = None,
    *,
    today: date | None = None,
) -> CheckReport:
    """Every check of *playbook* on *project*. A failing SQL check is reported."""
    today = today or datetime.now(timezone.utc).date()
    report = CheckReport(playbook=playbook.name, checks=len(playbook.checks))
    for check in playbook.checks:
        try:
            report.findings += _run(project, check, project_dir, today)
        except Exception as exc:  # noqa: BLE001 - one bad check must not hide others
            report.errors.append(f"{check.title} : {exc}")
    report.findings.sort(key=lambda f: (_ORDER.get(f.severity, 3), f.check, f.entity))
    return report


def _finding(
    project: Project, check: Check, entity: str, detail: str, key: str = ""
) -> Finding:
    document, quote = _source(project, entity, key)
    return Finding(
        check=check.id,
        title=check.title,
        severity=check.severity,
        entity=entity,
        detail=detail,
        advice=check.advice,
        document=document,
        quote=quote,
    )


def _missing(names: list[str], *, relation: bool = False) -> str:
    """ "aucune valeur « date echeance » ni équivalente": one name speaks for all."""
    first = names[0].replace("_", " ") if names else "?"
    kind = "aucune relation" if relation else "aucune valeur"
    return f"{kind} « {first} »" + (" ni équivalente" if len(names) > 1 else "")


def _run(
    project: Project, check: Check, project_dir: Path | None, today: date
) -> list[Finding]:
    if check.kind == "missing_attribute":
        have = {
            entity_key(a.entity)
            for a in project.ontology.attributes
            if a.key.casefold() in {k.casefold() for k in check.attributes}
        }
        return [
            _finding(
                project,
                check,
                name,
                check.message or _missing(check.attributes),
            )
            for key, name in sorted(_members(project, check.classes).items())
            if key not in have
        ]
    if check.kind == "missing_relation":
        have = {
            entity_key(t.subject)
            for t in project.ontology.triplets
            if t.predicate in check.predicates
        } | {
            entity_key(t.object)
            for t in project.ontology.triplets
            if t.predicate in check.predicates
        }
        return [
            _finding(
                project,
                check,
                name,
                check.message or _missing(check.predicates, relation=True),
            )
            for key, name in sorted(_members(project, check.classes).items())
            if key not in have
        ]
    if check.kind in {"date_within", "date_past"}:
        found = []
        limit = today + timedelta(days=check.days)
        for entity, key, value in _attribute_values(project, check.attributes):
            day = parse_date(value)
            if day is None:
                continue
            due = today <= day <= limit if check.kind == "date_within" else day < today
            if due:
                delta = (day - today).days
                when = (
                    f"dans {delta} jour(s)"
                    if delta >= 0
                    else f"il y a {-delta} jour(s)"
                )
                detail = (check.message or "{key} le {value} ({when})").format(
                    entity=entity, key=key.replace("_", " "), value=value, when=when
                )
                found.append(_finding(project, check, entity, detail, key))
        return found
    if check.kind == "value_above":
        if check.threshold is None:
            raise PlaybookError("value_above demande un seuil (threshold).")
        found = []
        for entity, key, value in _attribute_values(project, check.attributes):
            amount = parse_amount(value)
            if amount is not None and amount > check.threshold:
                detail = (check.message or "{key} = {value}").format(
                    entity=entity, key=key.replace("_", " "), value=value
                )
                found.append(_finding(project, check, entity, detail, key))
        return found
    # sql: each row is a finding; the first column names the entity.
    from auto_ontology.text_ontology.bridge import run_bridge_sql

    if project_dir is None:
        raise PlaybookError("contrôle SQL sans dossier de projet.")
    result = run_bridge_sql(project_dir, project, check.sql, limit=200)
    found = []
    for row in result.rows:
        values = {column: value for column, value in zip(result.columns, row)}
        entity = str(row[0]) if row else ""
        detail = (
            check.message.format(**values)
            if check.message
            else ", ".join(f"{c} = {v}" for c, v in values.items())
        )
        found.append(_finding(project, check, entity, detail))
    return found


def playbook_alerts(project: Project, home: Path, project_dir: Path) -> list[str]:
    """One line for the brief when the project's playbook finds something."""
    playbook = active(project, home)
    if playbook is None or not playbook.checks:
        return []
    report = run_checks(project, playbook, project_dir)
    return [report.summary()] if report.findings or report.errors else []
