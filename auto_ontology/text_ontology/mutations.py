# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Corrections a person makes on the ontology, then normalization again.

Rename, merge and delete change the strings in place and run the same
normalizer as an extraction, so a hand edit cannot break the rules the
model is held to. Provenance strings follow the new names.
"""

from __future__ import annotations

from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.normalize import normalize_ontology, to_snake_case
from auto_ontology.text_ontology.provenance import entity_key, merge_provenance
from auto_ontology.text_ontology.studio_models import (
    AttributeProv,
    ClassProv,
    Edit,
    Project,
    TripletProv,
)


class EditError(ValueError):
    """The correction cannot be applied. The message is for the user."""


def _rename_token(value: str, old: str, new: str) -> str:
    return new if value == old else value


def apply_edit(project: Project, edit: Edit) -> None:
    """Apply *edit* to *project* and realign its provenance."""
    ontology = project.ontology
    if edit.op == "rename_class":
        _require(edit.old, edit.new)
        _rename_class(ontology, edit.old, edit.new)
        _rename_provenance_class(project, edit.old, edit.new)
    elif edit.op == "rename_entity":
        _require(edit.old, edit.new)
        _rename_entity(ontology, edit.old, edit.new)
        _rename_provenance_entity(project, edit.old, edit.new)
    elif edit.op == "merge_entities":
        _require(edit.source, edit.target)
        if edit.source == edit.target:
            return
        _rename_entity(ontology, edit.source, edit.target)
        _rename_provenance_entity(project, edit.source, edit.target)
    elif edit.op == "delete_triplet":
        _delete_triplet(project, edit.subject, edit.predicate, edit.object)
    elif edit.op == "delete_attribute":
        _delete_attribute(project, edit.entity, edit.key, edit.value)
    elif edit.op == "delete_class":
        _delete_class(project, edit.old)
    elif edit.op == "update_description":
        _update_description(ontology, edit.old, edit.description)
    elif edit.op == "set_genre":
        _set_document_field(project, edit.document_id, "genre", edit.new)
    elif edit.op == "set_domain":
        _set_document_field(project, edit.document_id, "domain", edit.new)
    else:
        raise EditError(f"Opération inconnue : {edit.op}.")

    project.ontology, _warnings = normalize_ontology(project.ontology)
    _realign(project)


def _set_document_field(
    project: Project, document_id: str, field: str, value: str
) -> None:
    cleaned = value.strip()
    if not document_id or not cleaned:
        raise EditError("Le document et la valeur sont requis.")
    for document in project.documents:
        if document.id == document_id:
            setattr(document, field, cleaned)
            if field == "genre":
                document.genre_source = "user"
                document.genre_confidence = 1.0
            if field == "domain":
                document.domain_confidence = 1.0
            return
    raise EditError("Document introuvable.")


def _require(old: str, new: str) -> None:
    if not old.strip() or not new.strip():
        raise EditError("Les deux noms sont requis.")


def _rename_class(ontology: TextOntology, old: str, new: str) -> None:
    if not any(cls.name == old for cls in ontology.classes):
        raise EditError(f"Classe inconnue : {old}.")
    for cls in ontology.classes:
        if cls.name == old:
            cls.name = new
        elif cls.parent == old:
            cls.parent = new
    for triplet in ontology.triplets:
        triplet.subject = _rename_token(triplet.subject, old, new)
        triplet.object = _rename_token(triplet.object, old, new)
        triplet.subject_type = _rename_token(triplet.subject_type, old, new)
        triplet.object_type = _rename_token(triplet.object_type, old, new)
    for attribute in ontology.attributes:
        attribute.entity = _rename_token(attribute.entity, old, new)


def _rename_entity(ontology: TextOntology, old: str, new: str) -> None:
    seen = False
    for triplet in ontology.triplets:
        if triplet.subject == old:
            triplet.subject = new
            seen = True
        if triplet.object == old:
            triplet.object = new
            seen = True
    for attribute in ontology.attributes:
        if attribute.entity == old:
            attribute.entity = new
            seen = True
    if not seen:
        raise EditError(f"Entité inconnue : {old}.")


def _rename_provenance_class(project: Project, old: str, new: str) -> None:
    for item in project.classes:
        if item.name == old:
            item.name = new
    for item in project.triplets:
        item.subject = _rename_token(item.subject, old, new)
        item.object = _rename_token(item.object, old, new)
    for item in project.attributes:
        item.entity = _rename_token(item.entity, old, new)


def _rename_provenance_entity(project: Project, old: str, new: str) -> None:
    for item in project.triplets:
        item.subject = _rename_token(item.subject, old, new)
        item.object = _rename_token(item.object, old, new)
    for item in project.attributes:
        item.entity = _rename_token(item.entity, old, new)


def _delete_triplet(project: Project, subject: str, predicate: str, obj: str) -> None:
    predicate = to_snake_case(predicate)
    before = len(project.ontology.triplets)
    project.ontology.triplets = [
        triplet
        for triplet in project.ontology.triplets
        if not (
            triplet.subject == subject
            and to_snake_case(triplet.predicate) == predicate
            and triplet.object == obj
        )
    ]
    if len(project.ontology.triplets) == before:
        raise EditError("Ce fait est introuvable.")
    project.triplets = [
        item
        for item in project.triplets
        if not (
            item.subject == subject
            and to_snake_case(item.predicate) == predicate
            and item.object == obj
        )
    ]


def _delete_attribute(project: Project, entity: str, key: str, value: str) -> None:
    key = to_snake_case(key)
    before = len(project.ontology.attributes)
    project.ontology.attributes = [
        attribute
        for attribute in project.ontology.attributes
        if not (
            attribute.entity == entity
            and to_snake_case(attribute.key) == key
            and attribute.value == value
        )
    ]
    if len(project.ontology.attributes) == before:
        raise EditError("Cet attribut est introuvable.")
    project.attributes = [
        item
        for item in project.attributes
        if not (
            item.entity == entity
            and to_snake_case(item.key) == key
            and item.value == value
        )
    ]


def _delete_class(project: Project, name: str) -> None:
    classes = {cls.name: cls for cls in project.ontology.classes}
    if name not in classes:
        raise EditError(f"Classe inconnue : {name}.")
    parent = classes[name].parent
    used = any(
        name
        in {triplet.subject, triplet.object, triplet.subject_type, triplet.object_type}
        for triplet in project.ontology.triplets
    ) or any(attribute.entity == name for attribute in project.ontology.attributes)
    if used and parent is None:
        raise EditError(
            f"{name} est encore utilisée et n'a pas de classe parente. "
            "Retirez ses faits, ou fusionnez-la avec une autre classe."
        )
    if parent is not None:
        for triplet in project.ontology.triplets:
            triplet.subject = _rename_token(triplet.subject, name, parent)
            triplet.object = _rename_token(triplet.object, name, parent)
            triplet.subject_type = _rename_token(triplet.subject_type, name, parent)
            triplet.object_type = _rename_token(triplet.object_type, name, parent)
        for attribute in project.ontology.attributes:
            attribute.entity = _rename_token(attribute.entity, name, parent)
        _rename_provenance_class(project, name, parent)
    for cls in project.ontology.classes:
        if cls.parent == name:
            cls.parent = parent
    project.ontology.classes = [
        cls for cls in project.ontology.classes if cls.name != name
    ]
    project.classes = [item for item in project.classes if item.name != name]


def _update_description(ontology: TextOntology, name: str, description: str) -> None:
    for cls in ontology.classes:
        if cls.name == name:
            cls.description = description.strip()
            return
    raise EditError(f"Classe inconnue : {name}.")


def _realign(project: Project) -> None:
    """Drop provenance that no longer matches, and use the normalized spelling."""
    ontology = project.ontology
    class_by_fold = {cls.name.casefold(): cls.name for cls in ontology.classes}
    nodes: dict[str, str] = {}
    for triplet in ontology.triplets:
        nodes.setdefault(entity_key(triplet.subject), triplet.subject)
        nodes.setdefault(entity_key(triplet.object), triplet.object)
    for attribute in ontology.attributes:
        nodes.setdefault(entity_key(attribute.entity), attribute.entity)

    def node(name: str) -> str | None:
        folded = class_by_fold.get(name.casefold())
        if folded is not None and entity_key(name) == entity_key(folded):
            return folded
        return nodes.get(entity_key(name))

    triplet_keys = {
        (
            entity_key(item.subject),
            to_snake_case(item.predicate),
            entity_key(item.object),
        )
        for item in ontology.triplets
    }
    kept_triplets: list[TripletProv] = []
    for item in project.triplets:
        subject = node(item.subject)
        obj = node(item.object)
        predicate = to_snake_case(item.predicate)
        if subject is None or obj is None:
            continue
        if (entity_key(subject), predicate, entity_key(obj)) not in triplet_keys:
            continue
        item.subject, item.predicate, item.object = subject, predicate, obj
        kept_triplets.append(item)

    attribute_keys = {
        (entity_key(item.entity), item.key, item.value) for item in ontology.attributes
    }
    kept_attributes: list[AttributeProv] = []
    for item in project.attributes:
        owner = node(item.entity)
        key = to_snake_case(item.key)
        if owner is None:
            continue
        if (entity_key(owner), key, item.value) not in attribute_keys:
            continue
        item.entity, item.key = owner, key
        kept_attributes.append(item)

    kept_classes: list[ClassProv] = []
    for item in project.classes:
        name = class_by_fold.get(item.name.casefold())
        if name is None:
            continue
        item.name = name
        kept_classes.append(item)

    project.triplets, project.attributes, project.classes = merge_provenance(
        kept_triplets, kept_attributes, kept_classes, [], [], []
    )


def absorb_provenance(
    project: Project,
    triplets: list[TripletProv],
    attributes: list[AttributeProv],
    classes: list[ClassProv],
) -> None:
    """Add *provenance* onto the project, without duplicating a passage."""
    project.triplets, project.attributes, project.classes = merge_provenance(
        project.triplets,
        project.attributes,
        project.classes,
        triplets,
        attributes,
        classes,
    )
