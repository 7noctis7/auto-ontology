# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The schema of a project, kept apart from the extracted instances.

A class becomes an object type, a predicate a link type, an attribute key a
property. A status the person set is kept. Anything the model invents on a
later document starts as ``experimental``.
"""

from __future__ import annotations

import re

from auto_ontology.text_ontology.studio_models import (
    LinkTypeDef,
    ObjectTypeDef,
    Project,
    PropertyDef,
    SchemaCatalog,
)

_SHARED = {
    "date": "date",
    "date_publication": "date",
    "annee": "date",
    "titre": "titre",
    "title": "titre",
    "nom": "titre",
    "auteur": "auteur",
    "author": "auteur",
    "source": "source_document",
    "source_document": "source_document",
    "statut": "statut_revue",
    "statut_revue": "statut_revue",
    "confiance": "score_confiance",
    "score_confiance": "score_confiance",
}

_GROUPS = {
    "Personne": "Personnes",
    "Organisation": "Organisations",
    "Document": "Documents",
    "Lieu": "Lieux",
    "Evenement": "Événements",
}

_INTERFACES = (
    {"id": "Identifie", "needs": "a name"},
    {"id": "Date", "needs": "a date property"},
    {"id": "Source", "needs": "a document and a passage"},
    {"id": "Document", "needs": "a title"},
    {"id": "Quantifie", "needs": "a number"},
)

_INVERSE = {
    "est_un": "a_pour_specialisation",
    "est_dirigee_par": "dirige",
    "a_ecrit": "a_pour_auteur",
    "situe_a": "accueille",
    "se_trouve_dans": "contient",
}


def infer_base_type(value: str) -> str:
    """A small type for a literal. Unknown text stays a string."""
    cleaned = value.strip()
    if re.fullmatch(r"https?://\S+", cleaned):
        return "url"
    if cleaned.casefold() in {"true", "false", "oui", "non", "vrai", "faux"}:
        return "bool"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned) or re.fullmatch(
        r"(?:19|20)\d{2}", cleaned
    ):
        return "date"
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", cleaned):
        return "number"
    if re.search(r"\b(?:19|20)\d{2}\b", cleaned):
        return "date"
    return "string"


def sync_schema(project: Project) -> SchemaCatalog:
    """Fill the catalog from the ontology without dropping a status already set."""
    catalog = project.catalog
    types = {item.id: item for item in catalog.object_types}
    links = {item.id: item for item in catalog.link_types}
    properties = {item.id: item for item in catalog.properties}
    parents = {cls.name: cls.parent for cls in project.ontology.classes}
    for cls in project.ontology.classes:
        current = types.get(cls.name)
        group = _group(cls.name, parents)
        if current is None:
            types[cls.name] = ObjectTypeDef(
                id=cls.name,
                label=cls.name,
                description=cls.description,
                group=group,
            )
        elif cls.description and not current.description:
            current.description = cls.description
    for triplet in project.ontology.triplets:
        current = links.get(triplet.predicate)
        if current is None:
            links[triplet.predicate] = LinkTypeDef(
                id=triplet.predicate,
                label=triplet.predicate.replace("_", " "),
                inverse=_INVERSE.get(triplet.predicate, ""),
                source_type=triplet.subject_type,
                target_type=triplet.object_type,
            )
        else:
            current.source_type = current.source_type or triplet.subject_type
            current.target_type = current.target_type or triplet.object_type
    for attribute in project.ontology.attributes:
        base = infer_base_type(attribute.value)
        current = properties.get(attribute.key)
        shared = _SHARED.get(attribute.key, "")
        if current is None:
            properties[attribute.key] = PropertyDef(
                id=attribute.key,
                label=attribute.key.replace("_", " "),
                base_type=base,
                visibility="prominent"
                if shared or base in {"date", "number"}
                else "normal",
                shared=shared,
            )
        elif current.base_type == "string" and base != "string":
            current.base_type = base
    catalog.object_types = sorted(types.values(), key=lambda item: item.label)
    catalog.link_types = sorted(links.values(), key=lambda item: item.label)
    catalog.properties = sorted(properties.values(), key=lambda item: item.label)
    project.catalog = catalog
    return catalog


def interfaces_for(catalog: SchemaCatalog) -> list[dict[str, object]]:
    """Which fixed shapes the current properties can answer."""
    kinds = {item.base_type for item in catalog.properties}
    shared = {item.shared for item in catalog.properties}
    found = []
    for item in _INTERFACES:
        ok = True
        if item["id"] == "Date":
            ok = "date" in kinds or "date" in shared
        elif item["id"] == "Quantifie":
            ok = "number" in kinds
        elif item["id"] == "Document":
            ok = "titre" in shared or any(
                obj.group == "Documents" for obj in catalog.object_types
            )
        found.append(
            {**item, "implemented": ok or item["id"] in {"Identifie", "Source"}}
        )
    return found


def _group(name: str, parents: dict[str, str | None]) -> str:
    seen: set[str] = set()
    current: str | None = name
    while current and current not in seen:
        if current in _GROUPS:
            return _GROUPS[current]
        seen.add(current)
        current = parents.get(current)
    return "Concepts"
