# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What an agent may write: a fact it was told, a rule the team holds.

Both go through the same steps as a correction made on the page: an undo
point first, then the change, then a line in the action log under the
agent's name. A remembered fact carries its source like an extracted one,
under the pseudo-document :data:`AGENT_FILENAME`, so the studio shows where
it came from and the lineage view can tell it from a read passage. The
preview functions never write; :mod:`confirm` binds a write to its preview.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from auto_ontology.text_ontology.models import (
    OntologyAttribute,
    OntologyTriplet,
    TextOntology,
)
from auto_ontology.text_ontology.mutations import absorb_provenance
from auto_ontology.text_ontology.normalize import (
    entity_key,
    normalize_ontology,
    normalize_predicate,
    to_snake_case,
)
from auto_ontology.text_ontology.store import ProjectStore, now_iso
from auto_ontology.text_ontology.studio_models import (
    ActionEntry,
    AttributeProv,
    BusinessRule,
    Project,
    SourceRef,
    TripletProv,
)

AGENT_DOCUMENT_ID = "agent"
AGENT_FILENAME = "Mémoire de l'agent"
_MAX_TEXT = 2000


class WriteError(ValueError):
    """The write is refused. The message says what to send instead."""


def _text(arguments: Mapping[str, object], name: str, *, required: bool = True) -> str:
    value = " ".join(str(arguments.get(name) or "").split())
    if required and not value:
        raise WriteError(f"Indiquez {name}.")
    if len(value) > _MAX_TEXT:
        raise WriteError(f"{name} dépasse {_MAX_TEXT} caractères.")
    return value


# --- Facts ---------------------------------------------------------------------


def _known_type(project: Project, name: str) -> str:
    key = entity_key(name)
    for triplet in project.ontology.triplets:
        if entity_key(triplet.subject) == key:
            return triplet.subject_type
        if entity_key(triplet.object) == key:
            return triplet.object_type
    for item in project.ontology.classes:
        if entity_key(item.name) == key:
            return item.name  # a class named as a subject: it types itself
    return ""


def _fact(project: Project, arguments: Mapping[str, object]) -> TextOntology:
    source = _text(arguments, "source")
    if len(source) < 3:
        raise WriteError(
            "Indiquez source : d'où vient ce fait (une réunion, un message, "
            "une personne). Un fait sans source ne peut pas être vérifié."
        )
    if arguments.get("entity") or arguments.get("key"):
        entity, key = _text(arguments, "entity"), _text(arguments, "key")
        value = _text(arguments, "value")
        return TextOntology(
            attributes=[OntologyAttribute(entity=entity, key=key, value=value)]
        )
    subject, obj = _text(arguments, "subject"), _text(arguments, "object")
    predicate = _text(arguments, "predicate")
    types = []
    for role, name in (("subject", subject), ("object", obj)):
        given = _text(arguments, f"{role}_type", required=False)
        found = given or _known_type(project, name)
        if not found:
            classes = ", ".join(sorted(c.name for c in project.ontology.classes)[:15])
            raise WriteError(
                f"{name} n'est pas encore dans le projet : indiquez {role}_type, "
                f"sa classe (classes existantes : {classes or 'aucune'})."
            )
        types.append(found)
    return TextOntology(
        triplets=[
            OntologyTriplet(
                subject=subject,
                subject_type=types[0],
                predicate=predicate,
                object=obj,
                object_type=types[1],
            )
        ]
    )


def _line(part: TextOntology) -> str:
    if part.triplets:
        t = part.triplets[0]
        return f"{t.subject} {t.predicate} {t.object}"
    a = part.attributes[0]
    return f"{a.entity}.{a.key} = {a.value}"


def _known(project: Project, part: TextOntology) -> bool:
    if part.triplets:
        t = part.triplets[0]
        key = (
            entity_key(t.subject),
            normalize_predicate(t.predicate),
            entity_key(t.object),
        )
        return any(
            (entity_key(x.subject), x.predicate, entity_key(x.object)) == key
            for x in project.ontology.triplets
        )
    a = part.attributes[0]
    key = (entity_key(a.entity), to_snake_case(a.key), a.value.strip())
    return any(
        (entity_key(x.entity), x.key, x.value.strip()) == key
        for x in project.ontology.attributes
    )


def preview_fact(
    project: Project, arguments: Mapping[str, object]
) -> dict[str, object]:
    """What :func:`remember_fact` would add. Writes nothing."""
    part = _fact(project, arguments)
    known = _known(project, part)
    line = _line(part)
    return {
        "summary": (
            f"Déjà dans le projet : {line}. Cette source y sera ajoutée."
            if known
            else f"Fait à ajouter : {line}."
        ),
        "fact": line,
        "already_known": known,
        "source": _text(arguments, "source"),
    }


def remember_fact(
    store: ProjectStore,
    project: Project,
    arguments: Mapping[str, object],
    *,
    actor: str,
) -> dict[str, object]:
    """Add one fact with its source, as an undoable step."""
    preview = preview_fact(project, arguments)
    part = _fact(project, arguments)
    source = SourceRef(
        document_id=AGENT_DOCUMENT_ID,
        filename=AGENT_FILENAME,
        chunk_index=0,
        quote=str(preview["source"]),
    )
    store.save(project, snapshot=True)  # the undo point
    known_classes = [item.name for item in project.ontology.classes]
    union = project.ontology.model_copy(deep=True)
    union.triplets.extend(part.triplets)
    union.attributes.extend(part.attributes)
    project.ontology, _warnings = normalize_ontology(union, known_classes)
    absorb_provenance(
        project,
        [
            TripletProv(
                subject=t.subject,
                predicate=normalize_predicate(t.predicate),
                object=t.object,
                sources=[source],
            )
            for t in part.triplets
        ],
        [
            AttributeProv(
                entity=a.entity,
                key=to_snake_case(a.key),
                value=a.value.strip(),
                sources=[source],
            )
            for a in part.attributes
        ],
        [],
    )
    summary = f"Fait retenu : {preview['fact']} (source : {preview['source']})."
    _log(project, "remember_fact", arguments, summary, actor)
    store.save(project)
    return {**preview, "summary": summary, "applied": True}


# --- Rules -----------------------------------------------------------------------


def _rule(arguments: Mapping[str, object]) -> BusinessRule:
    text = _text(arguments, "text")
    if len(text) < 8:
        raise WriteError("Une règle tient en une phrase complète : précisez text.")
    tags = arguments.get("tags") or []
    if not isinstance(tags, list):
        raise WriteError("tags est une liste de mots.")
    return BusinessRule(
        id=uuid.uuid4().hex[:12],
        text=text,
        rationale=_text(arguments, "rationale", required=False),
        source=_text(arguments, "source", required=False),
        tags=sorted({" ".join(str(tag).split()) for tag in tags if str(tag).strip()}),
        created_at=now_iso(),
    )


def _same_rule(project: Project, rule: BusinessRule) -> BusinessRule | None:
    wanted = " ".join(rule.text.casefold().split())
    return next(
        (
            item
            for item in project.rules
            if item.status == "certified"
            and " ".join(item.text.casefold().split()) == wanted
        ),
        None,
    )


def preview_rule(
    project: Project, arguments: Mapping[str, object]
) -> dict[str, object]:
    """What :func:`certify_rule` would record. Writes nothing."""
    rule = _rule(arguments)
    same = _same_rule(project, rule)
    return {
        "summary": (
            f"Règle déjà certifiée le {same.created_at[:10]} : {same.text}"
            if same
            else f"Règle à certifier : {rule.text}"
        ),
        "rule": rule.text,
        "already_certified": same is not None,
    }


def certify_rule(
    store: ProjectStore,
    project: Project,
    arguments: Mapping[str, object],
    *,
    actor: str,
) -> dict[str, object]:
    """Record a rule or decision, as an undoable step."""
    preview = preview_rule(project, arguments)
    if preview["already_certified"]:
        return {**preview, "applied": False}
    rule = _rule(arguments)
    rule.actor = actor
    store.save(project, snapshot=True)
    project.rules.append(rule)
    summary = f"Règle certifiée : {rule.text}"
    _log(project, "certify_rule", arguments, summary, actor)
    store.save(project)
    return {**preview, "summary": summary, "applied": True, "id": rule.id}


def retire_rule(
    store: ProjectStore, project: Project, rule_id: str, *, actor: str
) -> BusinessRule:
    """Keep a rule for the record but stop applying it."""
    rule = next((item for item in project.rules if item.id == rule_id), None)
    if rule is None:
        raise WriteError(f"Règle inconnue : {rule_id}.")
    store.save(project, snapshot=True)
    rule.status = "retired"
    _log(project, "retire_rule", {"id": rule_id}, f"Règle retirée : {rule.text}", actor)
    store.save(project)
    return rule


def _log(
    project: Project,
    name: str,
    arguments: Mapping[str, object],
    summary: str,
    actor: str,
) -> None:
    project.action_log.append(
        ActionEntry(
            id=uuid.uuid4().hex[:12],
            at=now_iso(),
            actor=actor,
            name=name,
            params={
                key: str(value)
                for key, value in arguments.items()
                if value and key != "confirm_token"
            },
            summary=summary,
        )
    )
