# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ontology engineering checks that stay inside this local app.

TBox (classes, properties) stays distinct from ABox (individuals). Suggested
links to FOAF, schema.org, Dublin Core or PROV are never applied alone.
"""

from __future__ import annotations

import re

from auto_ontology.text_ontology.normalize import ascii_fold
from auto_ontology.text_ontology.query import answer
from auto_ontology.text_ontology.studio_models import Project, StepNote

_TOKEN = re.compile(r"[A-Za-z0-9]+")

# Common vocabularies. The IRI is what an accepted mapping points at.
_ALIGN: dict[str, tuple[str, str]] = {
    "personne": ("foaf:Person", "http://xmlns.com/foaf/0.1/Person"),
    "person": ("foaf:Person", "http://xmlns.com/foaf/0.1/Person"),
    "organisation": ("schema:Organization", "https://schema.org/Organization"),
    "organization": ("schema:Organization", "https://schema.org/Organization"),
    "document": ("schema:CreativeWork", "https://schema.org/CreativeWork"),
    "livre": ("schema:Book", "https://schema.org/Book"),
    "lieu": ("schema:Place", "https://schema.org/Place"),
    "ville": ("schema:City", "https://schema.org/City"),
    "pays": ("schema:Country", "https://schema.org/Country"),
    "evenement": ("schema:Event", "https://schema.org/Event"),
    "date": ("dcterms:date", "http://purl.org/dc/terms/date"),
    "auteur": ("dcterms:creator", "http://purl.org/dc/terms/creator"),
    "titre": ("dcterms:title", "http://purl.org/dc/terms/title"),
}

_INVERSE = {
    "est_dirige_par": "dirige",
    "est_dirigee_par": "dirige",
    "a_ecrit": "a_pour_auteur",
    "a_pour_auteur": "a_ecrit",
    "se_trouve_dans": "contient",
    "contient": "se_trouve_dans",
}
_SYMMETRIC = {"collabore_avec", "est_synonyme", "proche_de"}
_TRANSITIVE = {"se_trouve_dans", "partie_de", "contient"}


def local_name(name: str, kind: str) -> str:
    """An IRI fragment: UpperCamelCase for classes and individuals.

    Properties are lowerCamelCase. Spaces and underscores disappear; the
    French wording stays in ``rdfs:label``.
    """
    parts = _TOKEN.findall(ascii_fold(name)) or ["x"]
    if kind == "property":
        head, *tail = parts
        local = head.lower() + "".join(part[:1].upper() + part[1:] for part in tail)
    else:
        local = "".join(part[:1].upper() + part[1:] for part in parts)
    if local[0].isdigit():
        local = "N" + local
    return local


def inverse_name(predicate: str) -> str:
    """A known inverse, or an empty string when none is declared."""
    return _INVERSE.get(predicate, "")


def is_symmetric(predicate: str) -> bool:
    """True when the relation reads the same in both directions."""
    return predicate in _SYMMETRIC


def is_transitive(predicate: str) -> bool:
    """True when the relation chains (places, parts)."""
    return predicate in _TRANSITIVE


def shacl_turtle(project: Project, base_iri: str) -> str:
    """Node shapes for the classes: a label, and a definition when one exists."""
    lines = [
        "@prefix sh: <http://www.w3.org/ns/shacl#> .",
        f"@prefix : <{base_iri}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
    ]
    for cls in project.ontology.classes:
        name = local_name(cls.name, "class")
        lines.append(
            f":{name}Shape a sh:NodeShape ;\n"
            f"    sh:targetClass :{name} ;\n"
            "    sh:property [ sh:path rdfs:label ; sh:minCount 1 ] ."
        )
    return "\n".join(lines) + ("\n" if lines else "")


def shacl_checks(project: Project) -> list[StepNote]:
    """Quality notes a person can read. Nothing is deleted."""
    notes: list[StepNote] = []
    classes = {item.name: item for item in project.ontology.classes}
    parents = {name: item.parent for name, item in classes.items() if item.parent}
    cycle = _class_cycle(parents)
    notes.append(
        StepNote(
            name="sous-classe",
            status="failed" if cycle else "ok",
            detail="Cycle de sous-classe." if cycle else "Pas de cycle de sous-classe.",
        )
    )
    used: set[str] = set()
    for triplet in project.ontology.triplets:
        used.add(triplet.subject_type)
        used.add(triplet.object_type)
        if triplet.predicate == "est_un" and triplet.object in classes:
            used.add(triplet.subject_type)
    children = {parent for parent in parents.values()}
    orphans = [
        name
        for name in classes
        if name not in parents and name not in children and name not in used
    ]
    notes.append(
        StepNote(
            name="classes-orphelines",
            status="failed" if orphans else "ok",
            detail=(
                "Classes sans lien : " + ", ".join(orphans[:6])
                if orphans
                else "Chaque classe a un parent, un enfant ou une instance."
            ),
        )
    )
    missing = [name for name, item in classes.items() if not item.description.strip()]
    notes.append(
        StepNote(
            name="definitions",
            status="failed" if missing else "ok",
            detail=(
                "Définition manquante : " + ", ".join(missing[:6])
                if missing
                else "Chaque classe a une définition."
            ),
        )
    )
    folded: dict[str, list[str]] = {}
    for name in classes:
        folded.setdefault(name.casefold(), []).append(name)
    dupes = [names for names in folded.values() if len(names) > 1]
    notes.append(
        StepNote(
            name="libellés",
            status="failed" if dupes else "ok",
            detail=(
                "Libellés en double."
                if dupes
                else "Les libellés de classes sont distincts."
            ),
        )
    )
    violations = _domain_violations(project)
    notes.append(
        StepNote(
            name="domaine",
            status="failed" if violations else "ok",
            detail=(
                "Domaine ou portée incohérent : " + "; ".join(violations[:4])
                if violations
                else "Les faits respectent le domaine et la portée connus."
            ),
        )
    )
    return notes


def alignment_suggestions(project: Project) -> list[dict[str, object]]:
    """Possible reuse of a public vocabulary. ``accepted`` is never implied."""
    accepted = {(item.source, item.iri) for item in project.mappings if item.accepted}
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for cls in project.ontology.classes:
        key = ascii_fold(cls.name).casefold()
        target = _ALIGN.get(key)
        if target is None or cls.name in seen:
            continue
        seen.add(cls.name)
        prefix, iri = target
        rows.append(
            {
                "source": cls.name,
                "prefix": prefix,
                "iri": iri,
                "predicate": "owl:equivalentClass",
                "accepted": (cls.name, iri) in accepted,
                "auto": False,
            }
        )
    return rows


def competency_rows(project: Project) -> list[dict[str, object]]:
    """Each saved question, and whether the current facts can answer it."""
    rows: list[dict[str, object]] = []
    for item in project.questions:
        found = answer(project, item.text)
        facts = found.get("facts")
        rows.append(
            {
                "id": item.id,
                "text": item.text,
                "answerable": bool(facts),
                "answer": found.get("answer") or "",
            }
        )
    return rows


def _class_cycle(parents: dict[str, str]) -> bool:
    for start in list(parents):
        seen: set[str] = set()
        current: str | None = start
        while current and current not in seen:
            seen.add(current)
            current = parents.get(current)
            if current == start:
                return True
    return False


def _domain_violations(project: Project) -> list[str]:
    classes = {item.name for item in project.ontology.classes}
    parents = {item.name: item.parent for item in project.ontology.classes}
    expected: dict[str, tuple[str, str]] = {}
    for link in project.catalog.link_types:
        if link.source_type or link.target_type:
            expected[link.id] = (link.source_type, link.target_type)
    lines: list[str] = []
    for triplet in project.ontology.triplets:
        if triplet.predicate == "est_un":
            if triplet.subject in classes and triplet.object not in classes:
                lines.append(f"{triplet.subject} est_un {triplet.object}")
            continue
        if triplet.subject in classes or triplet.object in classes:
            lines.append(
                f"{triplet.subject} {triplet.predicate} {triplet.object} mélange classe et individu"
            )
        source, target = expected.get(triplet.predicate, ("", ""))
        if source and not _fits(triplet.subject_type, source, parents):
            lines.append(f"{triplet.predicate} : {triplet.subject_type} hors {source}")
        if target and not _fits(triplet.object_type, target, parents):
            lines.append(f"{triplet.predicate} : {triplet.object_type} hors {target}")
    return lines


def _fits(found: str, expected: str, parents: dict[str, str | None]) -> bool:
    current: str | None = found
    seen: set[str] = set()
    while current and current not in seen:
        if current == expected:
            return True
        seen.add(current)
        current = parents.get(current)
    return False
