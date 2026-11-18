# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render an extracted ontology in standard formats.

* ``mermaid``: a flowchart to paste into anything that renders Mermaid
  (mermaid.live, GitHub, Notion, Obsidian).
* ``turtle``: RDF/OWL in Turtle, for Protégé, a triple store or SPARQL.
* ``cypher``: an idempotent Neo4j script (``MERGE`` only), to replay with
  cypher-shell or the Neo4j Browser.
* ``html``: a standalone page that draws the graph and can be explored by
  clicking, opened straight from disk in a browser.

Every exporter reads the normalized ontology: class-level ``est_un`` triplets
already name their classes exactly, which is how a class is told from an
individual here.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum

from auto_ontology.text_ontology.models import OntologyTriplet, TextOntology
from auto_ontology.text_ontology.normalize import (
    HIERARCHY_PREDICATE,
    normalize_ontology,
)

DEFAULT_BASE_IRI = "http://example.org/auto-ontology#"


class ExportFormat(StrEnum):
    MERMAID = "mermaid"
    TURTLE = "turtle"
    CYPHER = "cypher"
    HTML = "html"


MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.MERMAID: "text/vnd.mermaid",
    ExportFormat.TURTLE: "text/turtle",
    ExportFormat.CYPHER: "application/x-cypher-query",
    ExportFormat.HTML: "text/html",
}

FILE_EXTENSIONS: dict[ExportFormat, str] = {
    ExportFormat.MERMAID: ".mmd",
    ExportFormat.TURTLE: ".ttl",
    ExportFormat.CYPHER: ".cypher",
    ExportFormat.HTML: ".html",
}


# ---------------------------------------------------------------------------
# A view of the ontology shared by every exporter
# ---------------------------------------------------------------------------


@dataclass
class _Entity:
    name: str
    types: list[str] = field(default_factory=list)
    attributes: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class _Graph:
    """Classes, individuals and the three kinds of link between them."""

    classes: dict[str, str | None]  # name -> parent
    descriptions: dict[str, str]
    entities: dict[str, _Entity]
    # (child class, parent class) beyond each class's own parent
    extra_parents: list[tuple[str, str]]
    # (individual, class) stated by an `est_un` triplet
    stated_types: list[tuple[str, str]]
    # triplets between individuals
    relations: list[OntologyTriplet]
    # attributes carried by a class rather than an individual
    class_attributes: dict[str, dict[str, list[str]]]


def _graph(ontology: TextOntology, *, normalized: bool = False) -> _Graph:
    # Normalized first: an export may read a file edited by hand, and every
    # exporter relies on declared classes and canonical names. A caller that
    # holds a stored project, normalized on every write, skips that pass.
    if not normalized:
        ontology, _ = normalize_ontology(ontology)
    classes = {c.name: c.parent for c in ontology.classes}
    descriptions = {c.name: c.description for c in ontology.classes if c.description}
    entities: dict[str, _Entity] = {}

    def entity(name: str) -> _Entity:
        return entities.setdefault(name, _Entity(name=name))

    def typed(name: str, type_name: str) -> None:
        found = entity(name)
        if type_name not in found.types:
            found.types.append(type_name)

    extra_parents: list[tuple[str, str]] = []
    stated_types: list[tuple[str, str]] = []
    relations: list[OntologyTriplet] = []
    for t in ontology.triplets:
        if t.predicate == HIERARCHY_PREDICATE and t.object in classes:
            if t.subject in classes:
                if classes[t.subject] != t.object:
                    extra_parents.append((t.subject, t.object))
                continue
            typed(t.subject, t.subject_type)
            if t.object != t.subject_type:
                stated_types.append((t.subject, t.object))
            continue
        typed(t.subject, t.subject_type)
        typed(t.object, t.object_type)
        relations.append(t)

    class_attributes: dict[str, dict[str, list[str]]] = {}
    for a in ontology.attributes:
        if a.entity in classes and a.entity not in entities:
            values = class_attributes.setdefault(a.entity, {}).setdefault(a.key, [])
        else:
            values = entity(a.entity).attributes.setdefault(a.key, [])
        if a.value not in values:
            values.append(a.value)

    return _Graph(
        classes=classes,
        descriptions=descriptions,
        entities=entities,
        extra_parents=extra_parents,
        stated_types=stated_types,
        relations=relations,
        class_attributes=class_attributes,
    )


# ---------------------------------------------------------------------------
# Literal values
# ---------------------------------------------------------------------------

_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]+")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _literal_kind(value: str) -> str:
    """``integer``, ``decimal``, ``boolean``, ``date`` or ``string``.

    Only unambiguous forms are typed. A number with a leading zero (a postal
    code, an identifier) stays a string, so no digit is lost on the way.
    """
    if _INTEGER.fullmatch(value):
        return "integer"
    if _DECIMAL.fullmatch(value):
        return "decimal"
    if value in ("true", "false"):
        return "boolean"
    if _DATE.fullmatch(value):
        return "date"
    return "string"


# ---------------------------------------------------------------------------
# Mermaid
# ---------------------------------------------------------------------------

_MERMAID_ATTRIBUTES_SHOWN = 5


def _mermaid_text(text: str) -> str:
    """*text* safe inside a quoted Mermaid label."""
    return (
        text.replace("&", "#amp;")
        .replace('"', "#quot;")
        .replace("<", "#lt;")
        .replace(">", "#gt;")
        .replace("\n", " ")
    )


def to_mermaid(ontology: TextOntology) -> str:
    """A Mermaid flowchart: classes as hexagons, individuals as boxes.

    Solid arrows are relations between individuals; dotted ``est_un`` arrows are
    the hierarchy, and an individual's class is written under its name.
    """
    graph = _graph(ontology)
    ids: dict[tuple[str, str], str] = {}

    def node(kind: str, name: str) -> str:
        return ids.setdefault((kind, name), f"{kind}{len(ids)}")

    lines = ["flowchart LR"]
    for name in graph.classes:
        lines.append(f'    {node("c", name)}{{{{"{_mermaid_text(name)}"}}}}')
    for found in graph.entities.values():
        label = _mermaid_text(found.name)
        if found.types:
            label += "<br/><i>" + _mermaid_text(", ".join(found.types)) + "</i>"
        attributes = [
            f"{key}: {', '.join(values)}" for key, values in found.attributes.items()
        ]
        for text in attributes[:_MERMAID_ATTRIBUTES_SHOWN]:
            label += "<br/>" + _mermaid_text(text)
        if len(attributes) > _MERMAID_ATTRIBUTES_SHOWN:
            label += "<br/>…"
        lines.append(f'    {node("e", found.name)}["{label}"]')

    for name, parent in graph.classes.items():
        if parent is not None:
            lines.append(f"    {node('c', name)} -.->|est_un| {node('c', parent)}")
    for child, parent in graph.extra_parents:
        lines.append(f"    {node('c', child)} -.->|est_un| {node('c', parent)}")
    for individual, class_name in graph.stated_types:
        lines.append(
            f"    {node('e', individual)} -.->|est_un| {node('c', class_name)}"
        )
    for t in graph.relations:
        label = _mermaid_text(t.predicate)
        lines.append(f'    {node("e", t.subject)} -->|"{label}"| {node("e", t.object)}')

    lines.append("    classDef classe fill:#e8f0fe,stroke:#4a6fd1,color:#1a2b5f")
    class_ids = [ids[("c", name)] for name in graph.classes]
    if class_ids:
        lines.append(f"    class {','.join(class_ids)} classe")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# RDF / OWL (Turtle)
# ---------------------------------------------------------------------------


class _LocalNames:
    """One IRI local name per (kind, label), unique within the namespace.

    Classes and individuals never share an IRI, even when the text uses the
    same word for both. Fragments are CamelCase, without underscores.
    """

    def __init__(self) -> None:
        from auto_ontology.text_ontology.standards import local_name

        self._local = local_name
        self._by_name: dict[tuple[str, str], str] = {}
        self._used: set[str] = set()

    def __call__(self, name: str, kind: str = "individual") -> str:
        key = (kind, name)
        known = self._by_name.get(key)
        if known is not None:
            return known
        local = self._local(name, kind)
        candidate, suffix = local, 2
        while candidate in self._used:
            candidate = f"{local}{suffix}"
            suffix += 1
        self._used.add(candidate)
        self._by_name[key] = candidate
        return candidate


def _turtle_string(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _turtle_literal(value: str) -> str:
    kind = _literal_kind(value)
    if kind == "string":
        return _turtle_string(value)
    return f"{_turtle_string(value)}^^xsd:{kind}"


def _turtle_iri(base_iri: str) -> str:
    if any(c in base_iri for c in '<>"{}|^`\\ '):
        raise ValueError(f"not a usable base IRI: {base_iri!r}")
    return f"<{base_iri}>"


def _lang_literal(text: str, lang: str) -> str:
    return f"{_turtle_string(text)}@{lang}"


def to_turtle(
    ontology: TextOntology,
    base_iri: str = DEFAULT_BASE_IRI,
    *,
    title: str = "",
    created: str = "",
    creator: str = "",
    language: str = "fr",
    aliases: dict[str, list[str]] | None = None,
) -> str:
    """OWL 2 / RDFS Turtle.

    Classes use ``rdfs:subClassOf``. Individuals use ``rdf:type`` (written
    ``a``). A class and an individual never share an IRI. Object and datatype
    properties carry a domain and a range when every use agrees. Labels stay
    in the source language; the IRI fragment is CamelCase.
    """
    from auto_ontology.text_ontology.standards import (
        inverse_name,
        is_symmetric,
        is_transitive,
    )

    graph = _graph(ontology)
    local = _LocalNames()
    aliases = aliases or {}

    def ref(name: str, kind: str) -> str:
        return f":{local(name, kind)}"

    lines = [
        f"@prefix : {_turtle_iri(base_iri)} .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "",
        f"{_turtle_iri(base_iri.rstrip('#/'))} a owl:Ontology ;",
        '    owl:versionInfo "1" ;',
        f"    dcterms:title {_turtle_string(title or 'Ontologie')} .",
        "",
        "# Classes",
    ]
    if created:
        lines.insert(-3, f"    dcterms:created {_turtle_string(created)} ;")
    if creator:
        lines.insert(-3, f"    dcterms:creator {_turtle_string(creator)} ;")
    parents: dict[str, list[str]] = {name: [] for name in graph.classes}
    for name, parent in graph.classes.items():
        if parent is not None:
            parents[name].append(parent)
    for child, parent in graph.extra_parents:
        parents[child].append(parent)
    for name in graph.classes:
        facts = [
            "a owl:Class",
            f"rdfs:label {_turtle_string(name)}",
            f"skos:prefLabel {_lang_literal(name, language)}",
        ]
        for alt in aliases.get(name, []):
            facts.append(f"skos:altLabel {_lang_literal(alt, language)}")
        if name in graph.descriptions:
            comment = _turtle_string(graph.descriptions[name])
            facts.append(f"rdfs:comment {comment}")
            facts.append(f"skos:definition {comment}")
        facts.extend(
            f"rdfs:subClassOf {ref(parent, 'class')}" for parent in parents[name]
        )
        lines.append(f"{ref(name, 'class')} " + " ;\n    ".join(facts) + " .")

    domains: dict[str, set[str]] = {}
    ranges: dict[str, set[str]] = {}
    for triplet in graph.relations:
        domains.setdefault(triplet.predicate, set()).add(triplet.subject_type)
        ranges.setdefault(triplet.predicate, set()).add(triplet.object_type)
    data_domain: dict[str, set[str]] = {}
    data_range: dict[str, set[str]] = {}
    for found in graph.entities.values():
        for key, values in found.attributes.items():
            data_domain.setdefault(key, set()).update(found.types)
            data_range.setdefault(key, set()).update(_literal_kind(v) for v in values)

    object_properties = list(dict.fromkeys(t.predicate for t in graph.relations))
    datatype_properties = list(
        dict.fromkeys(
            [
                *(k for e in graph.entities.values() for k in e.attributes),
                *(k for attrs in graph.class_attributes.values() for k in attrs),
            ]
        )
    )
    if object_properties or datatype_properties:
        lines += ["", "# Properties"]
    for name in object_properties:
        facts = [
            "a owl:ObjectProperty",
            f"rdfs:label {_turtle_string(name)}",
            f"skos:prefLabel {_lang_literal(name, language)}",
        ]
        domain = domains.get(name, set())
        span = ranges.get(name, set())
        if len(domain) == 1 and "" not in domain:
            facts.append(f"rdfs:domain {ref(next(iter(domain)), 'class')}")
        if len(span) == 1 and "" not in span:
            facts.append(f"rdfs:range {ref(next(iter(span)), 'class')}")
        inverse = inverse_name(name)
        if inverse:
            facts.append(f"owl:inverseOf {ref(inverse, 'property')}")
        if is_symmetric(name):
            facts.append("a owl:SymmetricProperty")
        if is_transitive(name):
            facts.append("a owl:TransitiveProperty")
        lines.append(f"{ref(name, 'property')} " + " ;\n    ".join(facts) + " .")
    for name in datatype_properties:
        facts = [
            "a owl:DatatypeProperty",
            f"rdfs:label {_turtle_string(name)}",
            f"skos:prefLabel {_lang_literal(name, language)}",
        ]
        domain = data_domain.get(name, set())
        kinds = data_range.get(name, set())
        if len(domain) == 1:
            facts.append(f"rdfs:domain {ref(next(iter(domain)), 'class')}")
        if len(kinds) == 1 and "string" not in kinds:
            facts.append(f"rdfs:range xsd:{next(iter(kinds))}")
        lines.append(f"{ref(name, 'property')} " + " ;\n    ".join(facts) + " .")

    stated: dict[str, list[str]] = {}
    for individual, class_name in graph.stated_types:
        stated.setdefault(individual, []).append(class_name)
    outgoing: dict[str, list[OntologyTriplet]] = {}
    for triplet in graph.relations:
        outgoing.setdefault(triplet.subject, []).append(triplet)

    if graph.entities:
        lines += ["", "# Individuals"]
    for found in graph.entities.values():
        types = list(dict.fromkeys([*found.types, *stated.get(found.name, [])]))
        typed = "".join(f" , {ref(type_name, 'class')}" for type_name in types)
        facts = ["a owl:NamedIndividual" + typed]
        facts.append(f"rdfs:label {_turtle_string(found.name)}")
        facts.append(f"skos:prefLabel {_lang_literal(found.name, language)}")
        for alt in aliases.get(found.name, []):
            facts.append(f"skos:altLabel {_lang_literal(alt, language)}")
        facts.extend(
            f"{ref(item.predicate, 'property')} {ref(item.object, 'individual')}"
            for item in outgoing.get(found.name, [])
        )
        for key, values in found.attributes.items():
            facts.extend(
                f"{ref(key, 'property')} {_turtle_literal(value)}" for value in values
            )
        lines.append(
            f"{ref(found.name, 'individual')} " + " ;\n    ".join(facts) + " ."
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Neo4j (Cypher)
# ---------------------------------------------------------------------------


def _cypher_string(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _cypher_name(name: str) -> str:
    """A label, relationship type or property key, always backtick-quoted."""
    return "`" + name.replace("`", "``") + "`"


def _cypher_value(value: str) -> str:
    kind = _literal_kind(value)
    if kind in ("integer", "decimal", "boolean"):
        return value
    if kind == "date":
        return f"date({_cypher_string(value)})"
    return _cypher_string(value)


def _cypher_values(values: list[str]) -> str:
    if len(values) == 1:
        return _cypher_value(values[0])
    return "[" + ", ".join(_cypher_value(v) for v in values) + "]"


def _relation_type(predicate: str) -> str:
    return _cypher_name(predicate.upper())


def to_cypher(ontology: TextOntology) -> str:
    """An idempotent Neo4j script: run it twice and the graph is unchanged.

    Classes are ``:Classe`` nodes linked by ``EST_UN``; individuals are
    ``:Entite`` nodes carrying their classes as labels, an ``A_POUR_TYPE``
    link to each class node, their attributes as properties, and one
    relationship per triplet.
    """
    graph = _graph(ontology)

    def match_class(var: str, name: str) -> str:
        return f"({var}:Classe {{name: {_cypher_string(name)}}})"

    def match_entity(var: str, name: str) -> str:
        return f"({var}:Entite {{name: {_cypher_string(name)}}})"

    lines = [
        "// Generated by auto_ontology.text_ontology. Safe to run more than once.",
        "CREATE CONSTRAINT classe_name IF NOT EXISTS "
        "FOR (c:Classe) REQUIRE c.name IS UNIQUE;",
        "CREATE CONSTRAINT entite_name IF NOT EXISTS "
        "FOR (e:Entite) REQUIRE e.name IS UNIQUE;",
        "",
        "// Classes",
    ]
    for name in graph.classes:
        sets = []
        if name in graph.descriptions:
            sets.append(f"c.description = {_cypher_string(graph.descriptions[name])}")
        for key, values in graph.class_attributes.get(name, {}).items():
            sets.append(f"c.{_cypher_name(key)} = {_cypher_values(values)}")
        statement = f"MERGE {match_class('c', name)}"
        if sets:
            statement += " SET " + ", ".join(sets)
        lines.append(statement + ";")
    links = [(n, p) for n, p in graph.classes.items() if p is not None]
    for child, parent in [*links, *graph.extra_parents]:
        lines.append(
            f"MATCH {match_class('c', child)}, {match_class('p', parent)} "
            "MERGE (c)-[:EST_UN]->(p);"
        )

    stated: dict[str, list[str]] = {}
    for individual, class_name in graph.stated_types:
        stated.setdefault(individual, []).append(class_name)

    if graph.entities:
        lines += ["", "// Individuals"]
    for found in graph.entities.values():
        types = list(dict.fromkeys([*found.types, *stated.get(found.name, [])]))
        sets = [f"e:{_cypher_name(t)}" for t in types]
        sets += [
            f"e.{_cypher_name(key)} = {_cypher_values(values)}"
            for key, values in found.attributes.items()
        ]
        statement = f"MERGE {match_entity('e', found.name)}"
        if sets:
            statement += " SET " + ", ".join(sets)
        lines.append(statement + ";")
        for type_name in types:
            lines.append(
                f"MATCH {match_entity('e', found.name)}, {match_class('c', type_name)} "
                "MERGE (e)-[:A_POUR_TYPE]->(c);"
            )

    if graph.relations:
        lines += ["", "// Relations"]
    for t in graph.relations:
        lines.append(
            f"MATCH {match_entity('a', t.subject)}, {match_entity('b', t.object)} "
            f"MERGE (a)-[:{_relation_type(t.predicate)}]->(b);"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Interactive HTML page
# ---------------------------------------------------------------------------

# Pinned, and loaded from a CDN: the page is a single file to open from disk.
_VIS_NETWORK_URL = (
    "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"
)


def _html_payload(ontology: TextOntology) -> dict[str, object]:
    graph = _graph(ontology)
    parents_of: dict[str, list[str]] = {
        name: [parent] if parent is not None else []
        for name, parent in graph.classes.items()
    }
    for child, parent in graph.extra_parents:
        if parent not in parents_of[child]:
            parents_of[child].append(parent)
    stated: dict[str, list[str]] = {}
    for individual, class_name in graph.stated_types:
        stated.setdefault(individual, []).append(class_name)

    ids: dict[tuple[str, str], str] = {}

    def node_id(kind: str, name: str) -> str:
        return ids.setdefault((kind, name), f"{kind}{len(ids)}")

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for name in graph.classes:
        nodes.append(
            {
                "id": node_id("c", name),
                "label": name,
                "kind": "classe",
                "description": graph.descriptions.get(name, ""),
                "parents": parents_of[name],
                "attributes": graph.class_attributes.get(name, {}),
            }
        )
    for found in graph.entities.values():
        types = list(dict.fromkeys([*found.types, *stated.get(found.name, [])]))
        nodes.append(
            {
                "id": node_id("e", found.name),
                "label": found.name,
                "kind": "entite",
                "types": types,
                "attributes": found.attributes,
            }
        )
        for type_name in types:
            if type_name in graph.classes:
                edges.append(
                    {
                        "from": node_id("e", found.name),
                        "to": node_id("c", type_name),
                        "kind": "type",
                    }
                )
    for name, parents in parents_of.items():
        for parent in parents:
            edges.append(
                {
                    "from": node_id("c", name),
                    "to": node_id("c", parent),
                    "kind": "est_un",
                }
            )
    for t in graph.relations:
        edges.append(
            {
                "from": node_id("e", t.subject),
                "to": node_id("e", t.object),
                "kind": "relation",
                "label": t.predicate,
            }
        )
    return {"nodes": nodes, "edges": edges}


def _script_json(value: object) -> str:
    """JSON that cannot close or comment out the ``<script>`` holding it."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def to_html(ontology: TextOntology, title: str = "Ontologie") -> str:
    """A standalone page drawing the ontology as an interactive graph.

    Labels and details are set as text, never as markup, so names taken from
    a document cannot inject anything into the page.
    """
    values = {
        "TITLE": html.escape(title),
        "VIS_NETWORK_URL": _VIS_NETWORK_URL,
        "DATA": _script_json(_html_payload(ontology)),
    }
    # One pass, so a title that happens to read "__DATA__" stays a title.
    return _PLACEHOLDER.sub(lambda m: values[m[1]], _html_template())


_PLACEHOLDER = re.compile(r"__(TITLE|VIS_NETWORK_URL|DATA)__")


def _html_template() -> str:
    """The page, from ``templates/graph.html``, without its license comment.

    Read on each call (a few kilobytes): export is not a hot path, and an
    edited template shows up without a restart.
    """
    from importlib.resources import files

    text = (
        files("auto_ontology.text_ontology")
        .joinpath("templates", "graph.html")
        .read_text(encoding="utf-8")
    )
    if text.startswith("<!--"):
        text = text[text.index("-->\n") + 4 :]
    return text


def export_ontology(
    ontology: TextOntology,
    export_format: ExportFormat,
    *,
    base_iri: str = DEFAULT_BASE_IRI,
    title: str = "Ontologie",
) -> str:
    """Render *ontology* in *export_format*."""
    match export_format:
        case ExportFormat.MERMAID:
            return to_mermaid(ontology)
        case ExportFormat.TURTLE:
            return to_turtle(ontology, base_iri=base_iri)
        case ExportFormat.CYPHER:
            return to_cypher(ontology)
        case ExportFormat.HTML:
            return to_html(ontology, title=title)
    raise ValueError(f"unknown export format: {export_format!r}")
