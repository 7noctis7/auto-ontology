# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Named corrections: preview, then apply, then a line in the log.

The log is what the next extraction reads, through the same alias and
rejection memory as a hand edit. Nothing is written during a preview.
"""

from __future__ import annotations

import uuid

from auto_ontology.text_ontology.learning import remember_edit
from auto_ontology.text_ontology.models import OntologyClass
from auto_ontology.text_ontology.mutations import EditError, apply_edit
from auto_ontology.text_ontology.schema_layer import sync_schema
from auto_ontology.text_ontology.store import ProjectStore, now_iso
from auto_ontology.text_ontology.studio_models import ActionEntry, Edit, Project

_NAMES = (
    "rename",
    "merge",
    "change_type",
    "reject_fact",
    "edit_property",
    "set_status",
)


def action_names() -> tuple[str, ...]:
    """The actions the page, the API and MCP can preview."""
    return _NAMES


def preview_action(
    project: Project, name: str, params: dict[str, str]
) -> dict[str, object]:
    """The diff of applying *name*, without touching *project*."""
    if name not in _NAMES:
        raise EditError(f"Action inconnue : {name}.")
    before = _snapshot(project)
    draft = project.model_copy(deep=True)
    summary = _apply(draft, name, params)
    after = _snapshot(draft)
    return {
        "ok": True,
        "name": name,
        "summary": summary,
        "added": sorted(after - before),
        "removed": sorted(before - after),
    }


def commit_action(
    store: ProjectStore,
    project: Project,
    name: str,
    params: dict[str, str],
    *,
    actor: str = "local",
) -> dict[str, object]:
    """Apply *name*, remember it for the next prompt, and append the log."""
    diff = preview_action(project, name, params)
    store.save(project, snapshot=True)
    summary = _apply(project, name, params)
    edit = _as_edit(name, params)
    if edit is not None:
        remember_edit(store, project, edit)
    project.action_log.append(
        ActionEntry(
            id=uuid.uuid4().hex[:12],
            at=now_iso(),
            actor=actor,
            name=name,
            params={key: str(value) for key, value in params.items() if value},
            summary=summary,
        )
    )
    store.save(project, snapshot=False)
    diff["summary"] = summary
    diff["applied"] = True
    return diff


def _apply(project: Project, name: str, params: dict[str, str]) -> str:
    if name == "set_status":
        return _set_status(project, params)
    if name == "change_type":
        _change_type(project, params.get("entity", ""), params.get("type", ""))
        return f"{params.get('entity', '')} est maintenant {params.get('type', '')}."
    if name == "edit_property":
        _edit_property(project, params)
        return (
            f"{params.get('entity', '')}.{params.get('key', '')} "
            f"= {params.get('value', '')}."
        )
    edit = _as_edit(name, params)
    if edit is None:
        raise EditError(f"Action inconnue : {name}.")
    apply_edit(project, edit)
    if name == "merge":
        return f"{params.get('source', '')} a été fusionné dans {params.get('target', '')}."
    if name == "rename":
        return f"{params.get('old', '')} s'écrit {params.get('new', '')}."
    if name == "reject_fact":
        return (
            f"Fait retiré : {params.get('subject', '')} "
            f"{params.get('predicate', '')} {params.get('object', '')}."
        )
    return name


def _as_edit(name: str, params: dict[str, str]) -> Edit | None:
    if name == "rename":
        kind = params.get("kind", "entity")
        op = "rename_class" if kind == "class" else "rename_entity"
        return Edit(op=op, old=params.get("old", ""), new=params.get("new", ""))
    if name == "merge":
        return Edit(
            op="merge_entities",
            source=params.get("source", ""),
            target=params.get("target", ""),
        )
    if name == "reject_fact":
        return Edit(
            op="delete_triplet",
            subject=params.get("subject", ""),
            predicate=params.get("predicate", ""),
            object=params.get("object", ""),
        )
    return None


def _change_type(project: Project, entity: str, type_name: str) -> None:
    if not entity.strip() or not type_name.strip():
        raise EditError("L'entité et le type sont requis.")
    found = False
    for triplet in project.ontology.triplets:
        if triplet.subject == entity:
            triplet.subject_type = type_name
            found = True
        if triplet.object == entity:
            triplet.object_type = type_name
            found = True
    if not found:
        raise EditError(f"Entité inconnue : {entity}.")
    if not any(cls.name == type_name for cls in project.ontology.classes):
        project.ontology.classes.append(OntologyClass(name=type_name, description=""))
    sync_schema(project)


def _edit_property(project: Project, params: dict[str, str]) -> None:
    entity = params.get("entity", "")
    key = params.get("key", "")
    value = params.get("value", "")
    if not entity or not key:
        raise EditError("L'entité et la propriété sont requises.")
    found = False
    for attribute in project.ontology.attributes:
        if attribute.entity == entity and attribute.key == key:
            attribute.value = value
            found = True
    for item in project.attributes:
        if item.entity == entity and item.key == key:
            item.value = value
    if not found:
        raise EditError(f"Propriété inconnue : {entity}.{key}.")
    sync_schema(project)


def _set_status(project: Project, params: dict[str, str]) -> str:
    target = params.get("id", "")
    status = params.get("status", "")
    if status not in {"experimental", "active", "deprecated"}:
        raise EditError("Le statut est experimental, active ou deprecated.")
    sync_schema(project)
    for item in (*project.catalog.object_types, *project.catalog.link_types):
        if item.id == target:
            item.status = status
            return f"{target} est {status}."
    raise EditError(f"Type inconnu : {target}.")


def _snapshot(project: Project) -> set[str]:
    facts = {
        f"{item.subject}|{item.predicate}|{item.object}"
        for item in project.ontology.triplets
    }
    facts.update(cls.name for cls in project.ontology.classes)
    return facts
