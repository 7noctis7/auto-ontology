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
    ascii_fold,
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

_LOCAL_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


class _LocalNames:
    """One IRI local name per distinct name, unique within the namespace."""

    def __init__(self) -> None:
        self._by_name: dict[str, str] = {}
        self._used: set[str] = set()

    def __call__(self, name: str) -> str:
        known = self._by_name.get(name)
        if known is not None:
            return known
        local = _LOCAL_UNSAFE.sub("_", ascii_fold(name)).strip("_") or "x"
        if local[0] == "-":
            local = "n" + local
        candidate, suffix = local, 2
        while candidate in self._used:
            candidate, suffix = f"{local}_{suffix}", suffix + 1
        self._used.add(candidate)
        self._by_name[name] = candidate
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


def to_turtle(ontology: TextOntology, base_iri: str = DEFAULT_BASE_IRI) -> str:
    """RDF/OWL in Turtle: classes, properties and named individuals.

    Classes become ``owl:Class`` with ``rdfs:subClassOf``; relation predicates
    become ``owl:ObjectProperty`` and attribute keys ``owl:DatatypeProperty``.
    No domain or range is stated: the text gives examples, not a schema.
    """
    graph = _graph(ontology)
    local = _LocalNames()

    def ref(name: str) -> str:
        return f":{local(name)}"

    lines = [
        f"@prefix : {_turtle_iri(base_iri)} .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"{_turtle_iri(base_iri.rstrip('#/'))} a owl:Ontology .",
        "",
        "# Classes",
    ]
    parents: dict[str, list[str]] = {name: [] for name in graph.classes}
    for name, parent in graph.classes.items():
        if parent is not None:
            parents[name].append(parent)
    for child, parent in graph.extra_parents:
        parents[child].append(parent)
    for name in graph.classes:
        facts = ["a owl:Class", f"rdfs:label {_turtle_string(name)}"]
        if name in graph.descriptions:
            facts.append(f"rdfs:comment {_turtle_string(graph.descriptions[name])}")
        facts.extend(f"rdfs:subClassOf {ref(p)}" for p in parents[name])
        for key, values in graph.class_attributes.get(name, {}).items():
            facts.extend(f"{ref(key)} {_turtle_literal(v)}" for v in values)
        lines.append(f"{ref(name)} " + " ;\n    ".join(facts) + " .")

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
        lines.append(
            f"{ref(name)} a owl:ObjectProperty ; rdfs:label {_turtle_string(name)} ."
        )
    for name in datatype_properties:
        lines.append(
            f"{ref(name)} a owl:DatatypeProperty ; rdfs:label {_turtle_string(name)} ."
        )

    stated: dict[str, list[str]] = {}
    for individual, class_name in graph.stated_types:
        stated.setdefault(individual, []).append(class_name)
    outgoing: dict[str, list[OntologyTriplet]] = {}
    for t in graph.relations:
        outgoing.setdefault(t.subject, []).append(t)

    if graph.entities:
        lines += ["", "# Individuals"]
    for found in graph.entities.values():
        types = list(dict.fromkeys([*found.types, *stated.get(found.name, [])]))
        facts = ["a owl:NamedIndividual" + "".join(f" , {ref(t)}" for t in types)]
        facts.append(f"rdfs:label {_turtle_string(found.name)}")
        facts.extend(
            f"{ref(t.predicate)} {ref(t.object)}" for t in outgoing.get(found.name, [])
        )
        for key, values in found.attributes.items():
            facts.extend(f"{ref(key)} {_turtle_literal(v)}" for v in values)
        lines.append(f"{ref(found.name)} " + " ;\n    ".join(facts) + " .")
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
    return _PLACEHOLDER.sub(lambda m: values[m[1]], _HTML_TEMPLATE)


_PLACEHOLDER = re.compile(r"__(TITLE|VIS_NETWORK_URL|DATA)__")


_HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --text: #0b0b0b; --text-2: #52514e;
    --muted: #898781; --hairline: #e1e0d9; --border: rgba(11, 11, 11, 0.10);
    --wash: rgba(11, 11, 11, 0.05); --class: #2a78d6; --entity: #eb6834;
    --edge: #898781; --on-fill: #ffffff; --warning: #fab219;
    --font: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --text: #f0efec; --text-2: #c3c2b7;
      --hairline: #2c2c2a; --border: rgba(255, 255, 255, 0.10);
      --wash: rgba(255, 255, 255, 0.06); --class: #3987e5; --entity: #d95926;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --text: #f0efec; --text-2: #c3c2b7;
    --hairline: #2c2c2a; --border: rgba(255, 255, 255, 0.10);
    --wash: rgba(255, 255, 255, 0.06); --class: #3987e5; --entity: #d95926;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    background: var(--page); color: var(--text); font: 14px/1.45 var(--font);
    display: grid; grid-template-rows: auto auto 1fr; grid-template-columns: 1fr 360px;
    grid-template-areas: "head head" "controls controls" "graph side";
  }
  header {
    grid-area: head; display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: baseline;
    padding: 12px 16px 8px; background: var(--surface); border-bottom: 1px solid var(--hairline);
  }
  header h1 { font-size: 17px; margin: 0; word-break: break-word; }
  .stats { display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--text-2); margin: 0; padding: 0; list-style: none; }
  .stats b { color: var(--text); font-variant-numeric: tabular-nums; }
  .controls {
    grid-area: controls; display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
    padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--hairline);
  }
  .group { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
  .group > span { color: var(--muted); font-size: 12px; }
  input[type=search] {
    font: inherit; padding: 6px 10px; min-width: 220px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--page); color: var(--text);
  }
  label.toggle { display: inline-flex; gap: 6px; align-items: center; color: var(--text-2); cursor: pointer; }
  button {
    font: inherit; color: var(--text); background: transparent; cursor: pointer;
    border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px;
  }
  button:hover { background: var(--wash); }
  button[aria-pressed="true"] { background: var(--wash); border-color: var(--text-2); }
  button:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--class); outline-offset: 1px; }
  .graph-wrap { grid-area: graph; position: relative; min-height: 0; min-width: 0; background: var(--surface); }
  #graph { position: absolute; inset: 0; }
  .graph-wrap .notice { position: absolute; inset: 0; display: grid; place-items: center; padding: 24px; color: var(--text-2); text-align: center; }
  .legend {
    position: absolute; left: 12px; bottom: 12px; display: flex; flex-wrap: wrap; gap: 4px 14px;
    padding: 6px 10px; border-radius: 6px; background: var(--surface); border: 1px solid var(--border);
    color: var(--text-2); font-size: 12px; max-width: calc(100% - 24px); pointer-events: none;
  }
  .legend i { display: inline-block; vertical-align: middle; margin-right: 5px; }
  .sw-class { width: 14px; height: 10px; border-radius: 2px; background: var(--class); }
  .sw-entity { width: 10px; height: 10px; border-radius: 50%; background: var(--entity); }
  .sw-multi { width: 14px; height: 10px; border-radius: 2px; background: var(--class); outline: 2px dashed var(--text); outline-offset: -1px; }
  .sw-line { width: 18px; border-top: 2px solid var(--edge); }
  .sw-dash { width: 18px; border-top: 2px dashed var(--edge); }
  .sw-dot { width: 18px; border-top: 2px dotted var(--edge); }
  aside {
    grid-area: side; display: flex; flex-direction: column; min-height: 0;
    background: var(--surface); border-left: 1px solid var(--hairline);
  }
  [role=tablist] { display: flex; gap: 4px; padding: 8px 12px 0; border-bottom: 1px solid var(--hairline); }
  [role=tab] { border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 6px 10px; color: var(--text-2); }
  [role=tab][aria-selected="true"] { color: var(--text); border-bottom-color: var(--text); font-weight: 600; }
  [role=tabpanel] { padding: 14px 16px; overflow: auto; flex: 1; min-height: 0; }
  [role=tabpanel][hidden] { display: none; }
  h2 { font-size: 16px; margin: 0 0 2px; word-break: break-word; }
  h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 16px 0 6px; }
  .kind { color: var(--text-2); }
  .empty { color: var(--text-2); }
  .warn { margin: 10px 0 0; padding: 8px 10px; border-radius: 6px; background: var(--wash); color: var(--text); }
  .warn::before { content: "⚠ "; color: var(--warning); font-weight: 700; }
  ul.plain { margin: 0; padding: 0; list-style: none; }
  ul.plain li { padding: 3px 0; border-bottom: 1px solid var(--hairline); word-break: break-word; }
  .link { border: 0; padding: 0; background: none; color: var(--class); text-decoration: underline; text-underline-offset: 2px; }
  .link:hover { background: none; }
  .arrow { color: var(--muted); padding: 0 4px; }
  .tree ul { list-style: none; margin: 0; padding-left: 16px; border-left: 1px solid var(--hairline); }
  .tree > ul { padding-left: 0; border: 0; }
  .tree li { margin: 2px 0; }
  .tree .row { display: flex; align-items: baseline; gap: 6px; }
  .tree .count { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12px; }
  .tree .flag { color: var(--text); font-size: 12px; }
  .tree .flag::before { content: "⚠ "; color: var(--warning); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
  th, td { padding: 5px 6px; border-bottom: 1px solid var(--hairline); vertical-align: top; word-break: break-word; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--wash); }
  .filter { width: 100%; margin-bottom: 8px; }
  @media (max-width: 860px) {
    body { grid-template-columns: 1fr; grid-template-rows: auto auto 60vh auto; grid-template-areas: "head" "controls" "graph" "side"; }
    aside { border-left: 0; border-top: 1px solid var(--hairline); min-height: 50vh; }
    input[type=search] { min-width: 0; width: 100%; }
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <ul class="stats" id="stats"></ul>
</header>
<div class="controls" role="toolbar" aria-label="Affichage du graphe">
  <input type="search" id="search" placeholder="Rechercher un nœud…" list="names" aria-label="Rechercher">
  <datalist id="names"></datalist>
  <div class="group">
    <span>Afficher</span>
    <label class="toggle"><input type="checkbox" id="show-classes" checked> Classes</label>
    <label class="toggle"><input type="checkbox" id="show-entities" checked> Entités</label>
    <label class="toggle"><input type="checkbox" id="show-types"> Liens de type</label>
    <label class="toggle"><input type="checkbox" id="show-labels" checked> Noms des relations</label>
  </div>
  <div class="group">
    <span>Disposition</span>
    <button type="button" id="layout-network" aria-pressed="true">Réseau</button>
    <button type="button" id="layout-tree" aria-pressed="false">Hiérarchie</button>
  </div>
  <div class="group">
    <button type="button" id="fit">Ajuster</button>
    <button type="button" id="physics" aria-pressed="false">Animer</button>
    <button type="button" id="png">PNG</button>
    <button type="button" id="theme" title="Thème : automatique, clair ou sombre">Thème : auto</button>
  </div>
</div>
<div class="graph-wrap">
  <div id="graph"></div>
  <div class="legend" aria-hidden="true">
    <span><i class="sw-class"></i>Classe</span>
    <span><i class="sw-entity"></i>Entité</span>
    <span><i class="sw-multi"></i>⚠ Plusieurs parents</span>
    <span><i class="sw-line"></i>Relation</span>
    <span><i class="sw-dash"></i>est_un</span>
    <span><i class="sw-dot"></i>Type</span>
  </div>
</div>
<aside>
  <div role="tablist" aria-label="Panneaux">
    <button type="button" role="tab" id="tab-details" aria-controls="panel-details" aria-selected="true">Détails</button>
    <button type="button" role="tab" id="tab-classes" aria-controls="panel-classes" aria-selected="false">Classes</button>
    <button type="button" role="tab" id="tab-table" aria-controls="panel-table" aria-selected="false">Tableau</button>
  </div>
  <div role="tabpanel" id="panel-details" aria-labelledby="tab-details">
    <p class="empty">Cliquez sur un nœud, une classe ou une ligne du tableau. Échap annule la sélection.</p>
  </div>
  <div role="tabpanel" id="panel-classes" aria-labelledby="tab-classes" hidden>
    <p class="empty">Cliquez sur une classe pour mettre en évidence sa famille : ses sous-classes et leurs entités.</p>
    <div class="tree" id="tree"></div>
  </div>
  <div role="tabpanel" id="panel-table" aria-labelledby="tab-table" hidden>
    <input type="search" class="filter" id="table-filter" placeholder="Filtrer le tableau…" aria-label="Filtrer le tableau">
    <h3>Relations</h3>
    <table><thead><tr><th>Sujet</th><th>Relation</th><th>Objet</th></tr></thead><tbody id="rows-relations"></tbody></table>
    <h3>Attributs</h3>
    <table><thead><tr><th>Entité</th><th>Attribut</th><th>Valeur</th></tr></thead><tbody id="rows-attributes"></tbody></table>
  </div>
</aside>
<script type="application/json" id="ontology-data">__DATA__</script>
<script src="__VIS_NETWORK_URL__"></script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("ontology-data").textContent);
  var root = document.documentElement;
  function $(id) { return document.getElementById(id); }
  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) { node.textContent = text; }
    if (cls) { node.className = cls; }
    return node;
  }

  // --- Model ---------------------------------------------------------------
  var byId = {}, classByName = {}, entityByName = {};
  data.nodes.forEach(function (n) {
    byId[n.id] = n;
    n.parents = n.parents || [];
    n.types = n.types || [];
    n.attributes = n.attributes || {};
    if (n.kind === "classe") { classByName[n.label] = n; } else { entityByName[n.label] = n; }
  });
  var children = {};
  data.nodes.forEach(function (n) {
    n.parents.forEach(function (p) { (children[p] = children[p] || []).push(n.label); });
  });
  function descendants(name) {
    var found = {}, pending = [name];
    while (pending.length) {
      var current = pending.pop();
      if (found[current]) { continue; }
      found[current] = true;
      (children[current] || []).forEach(function (c) { pending.push(c); });
    }
    return found;
  }
  data.nodes.forEach(function (n) {
    if (n.kind !== "classe") { return; }
    var family = descendants(n.label), count = 0;
    data.nodes.forEach(function (m) {
      if (m.kind === "entite" && m.types.some(function (t) { return family[t]; })) { count += 1; }
    });
    n.instances = count;
  });
  var relations = data.edges.filter(function (e) { return e.kind === "relation"; });
  var attributeRows = [];
  data.nodes.forEach(function (n) {
    Object.keys(n.attributes).forEach(function (k) {
      n.attributes[k].forEach(function (v) { attributeRows.push([n, k, v]); });
    });
  });

  // --- Header --------------------------------------------------------------
  [["Classes", Object.keys(classByName).length], ["Entités", Object.keys(entityByName).length],
   ["Relations", relations.length], ["Attributs", attributeRows.length]].forEach(function (s) {
    var li = el("li");
    li.appendChild(el("b", String(s[1])));
    li.appendChild(document.createTextNode(" " + s[0].toLowerCase()));
    $("stats").appendChild(li);
  });
  data.nodes.forEach(function (n) { $("names").appendChild(el("option")).value = n.label; });

  // --- Theme ---------------------------------------------------------------
  var THEMES = ["auto", "light", "dark"], LABELS = { auto: "auto", light: "clair", dark: "sombre" };
  function readTheme() { try { return localStorage.getItem("ontology-theme") || "auto"; } catch (e) { return "auto"; } }
  function applyTheme(theme) {
    if (theme === "auto") { delete root.dataset.theme; } else { root.dataset.theme = theme; }
    $("theme").textContent = "Thème : " + LABELS[theme];
    try { localStorage.setItem("ontology-theme", theme); } catch (e) { /* private mode */ }
    if (network) { restyle(); }
  }
  $("theme").addEventListener("click", function () {
    var next = THEMES[(THEMES.indexOf(readTheme()) + 1) % THEMES.length];
    applyTheme(next);
  });
  applyTheme(readTheme());
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if (network) { restyle(); }
    });
  }

  // --- Tabs ----------------------------------------------------------------
  var tabs = ["details", "classes", "table"];
  function showTab(name) {
    tabs.forEach(function (t) {
      $("tab-" + t).setAttribute("aria-selected", String(t === name));
      $("panel-" + t).hidden = t !== name;
    });
  }
  tabs.forEach(function (t) { $("tab-" + t).addEventListener("click", function () { showTab(t); }); });

  // --- Details -------------------------------------------------------------
  function linkTo(node) {
    var b = el("button", node.label, "link");
    b.type = "button";
    b.addEventListener("click", function () { select(node.id, true); });
    return b;
  }
  function section(panel, title, items) {
    if (!items.length) { return; }
    panel.appendChild(el("h3", title));
    var ul = el("ul", null, "plain");
    items.forEach(function (parts) {
      var li = el("li");
      parts.forEach(function (p) { li.appendChild(typeof p === "string" ? el("span", p, p === "→" ? "arrow" : null) : p); });
      ul.appendChild(li);
    });
    panel.appendChild(ul);
  }
  function showDetails(id) {
    var n = byId[id], panel = $("panel-details");
    panel.replaceChildren();
    panel.appendChild(el("h2", n.label));
    panel.appendChild(el("div", n.kind === "classe"
      ? "Classe · " + n.instances + " entité" + (n.instances > 1 ? "s" : "")
      : "Entité", "kind"));
    if (n.description) { panel.appendChild(el("p", n.description)); }
    if (n.parents.length > 1) {
      panel.appendChild(el("p", "Plusieurs parents : vérifiez lesquels sont justes.", "warn"));
    }
    var named = function (names, lookup) {
      return names.map(function (name) { return [lookup[name] ? linkTo(lookup[name]) : name]; });
    };
    section(panel, n.parents.length > 1 ? "Parents" : "Parent", named(n.parents, classByName));
    section(panel, "Sous-classes", named(children[n.label] || [], classByName));
    section(panel, "Types", named(n.types, classByName));
    section(panel, "Attributs", Object.keys(n.attributes).map(function (k) {
      return [k + " : " + n.attributes[k].join(", ")];
    }));
    var out = [], inc = [];
    relations.forEach(function (e) {
      if (e.from === id) { out.push([e.label, "→", linkTo(byId[e.to])]); }
      if (e.to === id) { inc.push([linkTo(byId[e.from]), "→", e.label]); }
    });
    section(panel, "Relations sortantes", out);
    section(panel, "Relations entrantes", inc);
    if (n.kind === "classe") {
      var members = data.nodes.filter(function (m) {
        return m.kind === "entite" && m.types.indexOf(n.label) >= 0;
      });
      section(panel, "Entités de cette classe", members.map(function (m) { return [linkTo(m)]; }));
    }
  }

  // --- Class tree ----------------------------------------------------------
  function treeItem(name, path) {
    var n = classByName[name], li = el("li"), row = el("div", null, "row");
    var b = el("button", name, "link");
    b.type = "button";
    b.addEventListener("click", function () { showDetails(n.id); highlightFamily(name); });
    row.appendChild(b);
    row.appendChild(el("span", String(n.instances), "count"));
    if (n.parents.length > 1) { row.appendChild(el("span", "plusieurs parents", "flag")); }
    li.appendChild(row);
    var kids = (children[name] || []).filter(function (c) { return path.indexOf(c) < 0; });
    if (kids.length) {
      var ul = el("ul");
      kids.sort().forEach(function (c) { ul.appendChild(treeItem(c, path.concat([c]))); });
      li.appendChild(ul);
    }
    return li;
  }
  var treeRoot = el("ul");
  Object.keys(classByName).filter(function (name) { return !classByName[name].parents.length; })
    .sort().forEach(function (name) { treeRoot.appendChild(treeItem(name, [name])); });
  $("tree").appendChild(treeRoot);

  // --- Table ---------------------------------------------------------------
  function fillTable(filter) {
    var needle = (filter || "").trim().toLowerCase();
    var keep = function (cells) {
      return !needle || cells.some(function (c) { return c.toLowerCase().indexOf(needle) >= 0; });
    };
    var rel = $("rows-relations"), att = $("rows-attributes");
    rel.replaceChildren();
    att.replaceChildren();
    relations.forEach(function (e) {
      var cells = [byId[e.from].label, e.label, byId[e.to].label];
      if (!keep(cells)) { return; }
      var tr = el("tr");
      cells.forEach(function (c) { tr.appendChild(el("td", c)); });
      tr.addEventListener("click", function () { select(e.from, true, true); });
      rel.appendChild(tr);
    });
    attributeRows.forEach(function (row) {
      var cells = [row[0].label, row[1], row[2]];
      if (!keep(cells)) { return; }
      var tr = el("tr");
      cells.forEach(function (c) { tr.appendChild(el("td", c)); });
      tr.addEventListener("click", function () { select(row[0].id, true, true); });
      att.appendChild(tr);
    });
  }
  fillTable("");
  $("table-filter").addEventListener("input", function (ev) { fillTable(ev.target.value); });

  // --- Graph ---------------------------------------------------------------
  var network = null, nodes = null, edges = null, focus = null;
  var physicsOn = false, hierarchical = false;
  function css() {
    var s = getComputedStyle(root);
    var v = function (name) { return s.getPropertyValue(name).trim(); };
    return { surface: v("--surface"), text: v("--text"), text2: v("--text-2"), edge: v("--edge"),
      cls: v("--class"), entity: v("--entity"), onFill: v("--on-fill"), font: v("--font") };
  }
  function fade(color, alpha) {
    var hex = color.replace("#", "");
    if (hex.length !== 6) { return color; }
    var n = parseInt(hex, 16);
    return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
  }
  function tooltip(n) {
    var box = el("div");
    box.appendChild(el("strong", n.label));
    box.appendChild(el("div", n.kind === "classe" ? "Classe" : "Entité" +
      (n.types.length ? " · " + n.types.join(", ") : "")));
    return box;
  }
  function nodeStyle(n, c) {
    var dim = focus && !focus[n.id];
    var hidden = n.kind === "classe" ? !$("show-classes").checked : !$("show-entities").checked;
    if (n.kind === "classe") {
      var multi = n.parents.length > 1;
      return { id: n.id, label: (multi ? "⚠ " : "") + n.label, shape: "box", hidden: hidden,
        opacity: dim ? 0.15 : 1, margin: 8, borderWidth: multi ? 2 : 1,
        shapeProperties: { borderDashes: multi ? [5, 3] : false, borderRadius: 4 },
        color: { background: c.cls, border: multi ? c.text : c.cls,
          highlight: { background: c.cls, border: c.text }, hover: { background: c.cls, border: c.text } },
        font: { color: dim ? fade(c.onFill, 0.5) : c.onFill, face: c.font, size: 14 }, title: tooltip(n) };
    }
    return { id: n.id, label: n.label, shape: "dot", size: 9, hidden: hidden,
      opacity: dim ? 0.15 : 1, borderWidth: 2,
      color: { background: c.entity, border: c.surface,
        highlight: { background: c.entity, border: c.text }, hover: { background: c.entity, border: c.text } },
      font: { color: dim ? fade(c.text, 0.25) : c.text, face: c.font, size: 13, strokeWidth: 3,
        strokeColor: c.surface }, title: tooltip(n) };
  }
  function edgeStyle(e, i, c) {
    var dim = focus && !(focus[e.from] && focus[e.to]);
    var labels = $("show-labels").checked;
    var style = { id: "x" + i, from: e.from, to: e.to, width: 1.5,
      arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      color: { color: c.edge, highlight: c.text, hover: c.text, opacity: dim ? 0.12 : 1 },
      font: { color: dim ? fade(c.text2, 0.2) : c.text2, face: c.font, size: 11, strokeWidth: 3,
        strokeColor: c.surface } };
    if (e.kind === "relation") { style.label = labels ? e.label : undefined; }
    if (e.kind === "est_un") { style.dashes = [6, 4]; style.label = labels ? "est_un" : undefined; }
    if (e.kind === "type") { style.dashes = [2, 4]; style.hidden = !$("show-types").checked; }
    return style;
  }
  function restyle() {
    var c = css();
    nodes.update(data.nodes.map(function (n) { return nodeStyle(n, c); }));
    edges.update(data.edges.map(function (e, i) { return edgeStyle(e, i, c); }));
  }
  function setFocus(ids) {
    focus = ids;
    if (network) { restyle(); }
  }
  function neighbourhood(id) {
    var ids = {};
    ids[id] = true;
    data.edges.forEach(function (e) {
      if (e.from === id) { ids[e.to] = true; }
      if (e.to === id) { ids[e.from] = true; }
    });
    return ids;
  }
  function highlightFamily(name) {
    var family = descendants(name), ids = {};
    data.nodes.forEach(function (n) {
      if ((n.kind === "classe" && family[n.label]) ||
          (n.kind === "entite" && n.types.some(function (t) { return family[t]; }))) { ids[n.id] = true; }
    });
    setFocus(ids);
    if (network) {
      network.selectNodes([classByName[name].id]);
      network.fit({ nodes: Object.keys(ids), animation: true });
    }
  }
  function select(id, move, stayOnTab) {
    showDetails(id);
    if (!stayOnTab) { showTab("details"); }
    setFocus(neighbourhood(id));
    if (network) {
      network.selectNodes([id]);
      if (move) { network.focus(id, { scale: 1.1, animation: true }); }
    }
  }
  function clearSelection() {
    setFocus(null);
    if (network) { network.unselectAll(); }
  }

  $("search").addEventListener("change", function (ev) {
    var wanted = ev.target.value.trim().toLowerCase();
    if (!wanted) { return; }
    var found = data.nodes.find(function (n) { return n.label.toLowerCase() === wanted; }) ||
      data.nodes.find(function (n) { return n.label.toLowerCase().indexOf(wanted) >= 0; });
    if (found) { select(found.id, true); }
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { clearSelection(); }
  });

  if (typeof vis === "undefined") {
    document.querySelector(".graph-wrap").appendChild(el("div", "Le graphe n'a pas pu être chargé (connexion Internet requise). " +
      "Les onglets Classes et Tableau restent utilisables.", "notice"));
    showTab("classes");
    return;
  }

  var c0 = css();
  nodes = new vis.DataSet(data.nodes.map(function (n) { return nodeStyle(n, c0); }));
  edges = new vis.DataSet(data.edges.map(function (e, i) { return edgeStyle(e, i, c0); }));
  var NETWORK = { hierarchical: { enabled: false } };
  var TREE = { hierarchical: { enabled: true, direction: "DU", sortMethod: "directed",
    levelSeparation: 120, nodeSpacing: 260, treeSpacing: 280 } };
  function createNetwork(tree) {
    if (network) { network.destroy(); }
    network = new vis.Network($("graph"), { nodes: nodes, edges: edges }, {
      layout: tree ? TREE : NETWORK,
      physics: { enabled: true, stabilization: { iterations: 400 },
        solver: tree ? "hierarchicalRepulsion" : "forceAtlas2Based" },
      interaction: { hover: true, keyboard: { enabled: true, bindToWindow: false }, tooltipDelay: 150 },
      edges: { smooth: tree ? { type: "cubicBezier", forceDirection: "vertical" } : { type: "continuous" } }
    });
    network.once("stabilizationIterationsDone", function () {
      if (!physicsOn) { network.setOptions({ physics: { enabled: false } }); }
      network.fit();
    });
    network.on("click", function (params) {
      if (params.nodes.length) { select(params.nodes[0], false); }
      else if (!params.edges.length) { clearSelection(); }
    });
  }
  createNetwork(false);

  ["show-classes", "show-entities", "show-types", "show-labels"].forEach(function (id) {
    $(id).addEventListener("change", restyle);
  });
  function setLayout(tree) {
    hierarchical = tree;
    $("layout-network").setAttribute("aria-pressed", String(!tree));
    $("layout-tree").setAttribute("aria-pressed", String(tree));
    // A fresh network: the options one layout leaves behind spoil the other.
    createNetwork(tree);
  }
  $("layout-network").addEventListener("click", function () { setLayout(false); });
  $("layout-tree").addEventListener("click", function () { setLayout(true); });
  $("fit").addEventListener("click", function () { network.fit({ animation: true }); });
  $("physics").addEventListener("click", function () {
    physicsOn = !physicsOn;
    $("physics").setAttribute("aria-pressed", String(physicsOn));
    network.setOptions({ physics: { enabled: physicsOn,
      solver: hierarchical ? "hierarchicalRepulsion" : "forceAtlas2Based" } });
  });
  $("png").addEventListener("click", function () {
    var source = $("graph").querySelector("canvas");
    var out = document.createElement("canvas");
    out.width = source.width;
    out.height = source.height;
    var ctx = out.getContext("2d");
    ctx.fillStyle = css().surface;
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(source, 0, 0);
    var link = document.createElement("a");
    link.download = (document.title || "ontologie") + ".png";
    link.href = out.toDataURL("image/png");
    link.click();
  });
})();
</script>
</body>
</html>
"""


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
