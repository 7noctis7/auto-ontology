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


def _graph(ontology: TextOntology) -> _Graph:
    # Normalized first: an export may read a file edited by hand, and every
    # exporter relies on declared classes and canonical names.
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
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    ids: dict[tuple[str, str], str] = {}

    def node_id(kind: str, name: str) -> str:
        return ids.setdefault((kind, name), f"{kind}{len(ids)}")

    for name, parent in graph.classes.items():
        nodes.append(
            {
                "id": node_id("c", name),
                "label": name,
                "kind": "classe",
                "description": graph.descriptions.get(name, ""),
                "attributes": graph.class_attributes.get(name, {}),
                "parent": parent,
            }
        )
    for found in graph.entities.values():
        nodes.append(
            {
                "id": node_id("e", found.name),
                "label": found.name,
                "kind": "entite",
                "types": found.types,
                "attributes": found.attributes,
            }
        )
    for name, parent in graph.classes.items():
        if parent is not None:
            edges.append(
                {
                    "from": node_id("c", name),
                    "to": node_id("c", parent),
                    "kind": "est_un",
                }
            )
    for child, parent in graph.extra_parents:
        edges.append(
            {"from": node_id("c", child), "to": node_id("c", parent), "kind": "est_un"}
        )
    for found in graph.entities.values():
        for type_name in found.types:
            if ("c", type_name) in ids:
                edges.append(
                    {
                        "from": node_id("e", found.name),
                        "to": ids[("c", type_name)],
                        "kind": "type",
                    }
                )
    for individual, class_name in graph.stated_types:
        edges.append(
            {
                "from": node_id("e", individual),
                "to": node_id("c", class_name),
                "kind": "type",
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
    --bg: #f7f8fa; --panel: #ffffff; --text: #1d2330; --muted: #5b6475;
    --border: #d9dde5; --class: #4a6fd1; --class-bg: #e8f0fe;
    --entity: #2f855a; --entity-bg: #e6f4ea; --edge: #7b8494;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14171c; --panel: #1c2027; --text: #e6e9ef; --muted: #9aa3b2;
      --border: #2e3440; --class: #8aa8ff; --class-bg: #24304d;
      --entity: #6fcf97; --entity-bg: #1f3a2b; --edge: #8a93a3;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body { display: grid; grid-template-columns: 1fr 320px; grid-template-rows: auto 1fr; }
  header { grid-column: 1 / -1; display: flex; gap: 12px; align-items: center;
    flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel); }
  header h1 { font-size: 16px; margin: 0 8px 0 0; }
  header input[type=search] { padding: 6px 10px; border: 1px solid var(--border);
    border-radius: 6px; background: var(--bg); color: var(--text); min-width: 200px; }
  header label { color: var(--muted); display: flex; gap: 6px; align-items: center; }
  .legend { display: flex; gap: 12px; color: var(--muted); margin-left: auto; }
  .chip { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
    margin-right: 4px; vertical-align: middle; }
  #graph { min-height: 0; }
  aside { border-left: 1px solid var(--border); background: var(--panel);
    padding: 16px; overflow: auto; }
  aside h2 { font-size: 15px; margin: 0 0 4px; word-break: break-word; }
  aside .kind { color: var(--muted); margin-bottom: 12px; }
  aside h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
    color: var(--muted); margin: 16px 0 6px; }
  aside ul { margin: 0; padding-left: 18px; }
  aside li { margin: 2px 0; word-break: break-word; }
  .empty { color: var(--muted); }
  @media (max-width: 720px) {
    body { grid-template-columns: 1fr; grid-template-rows: auto 60vh auto; }
    aside { border-left: 0; border-top: 1px solid var(--border); }
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <input type="search" id="search" placeholder="Rechercher un nœud…" list="names">
  <datalist id="names"></datalist>
  <label><input type="checkbox" id="show-types"> Liens de type</label>
  <span class="legend">
    <span><span class="chip" style="background:var(--class)"></span>Classe</span>
    <span><span class="chip" style="background:var(--entity)"></span>Entité</span>
  </span>
</header>
<div id="graph"></div>
<aside id="details"><p class="empty">Cliquez sur un nœud pour voir ses détails.</p></aside>
<script type="application/json" id="ontology-data">__DATA__</script>
<script src="__VIS_NETWORK_URL__"></script>
<script>
(function () {
  var data = JSON.parse(document.getElementById("ontology-data").textContent);
  var css = getComputedStyle(document.documentElement);
  function v(name) { return css.getPropertyValue(name).trim(); }
  var details = document.getElementById("details");
  if (typeof vis === "undefined") {
    details.textContent = "La bibliothèque de graphe n'a pas pu être chargée " +
      "(connexion Internet requise).";
    return;
  }
  var byId = {};
  data.nodes.forEach(function (n) { byId[n.id] = n; });

  var nodes = new vis.DataSet(data.nodes.map(function (n) {
    var isClass = n.kind === "classe";
    return {
      id: n.id, label: n.label, shape: isClass ? "box" : "dot", size: 10,
      color: isClass
        ? { background: v("--class-bg"), border: v("--class") }
        : { background: v("--entity"), border: v("--entity") },
      font: { color: v("--text") }
    };
  }));
  function edgeStyle(e, i) {
    var base = { id: "x" + i, from: e.from, to: e.to, arrows: "to",
      color: { color: v("--edge") }, font: { color: v("--muted"), strokeWidth: 0, size: 11 } };
    if (e.kind === "relation") { base.label = e.label; }
    if (e.kind === "est_un") { base.label = "est_un"; base.dashes = true; }
    if (e.kind === "type") { base.dashes = [2, 4]; base.hidden = true; }
    base.kind = e.kind;
    return base;
  }
  var edges = new vis.DataSet(data.edges.map(edgeStyle));
  var network = new vis.Network(document.getElementById("graph"),
    { nodes: nodes, edges: edges },
    { physics: { stabilization: { iterations: 300 } },
      interaction: { hover: true }, edges: { smooth: { type: "dynamic" } } });

  document.getElementById("show-types").addEventListener("change", function (ev) {
    edges.update(edges.get({ filter: function (e) { return e.kind === "type"; } })
      .map(function (e) { return { id: e.id, hidden: !ev.target.checked }; }));
  });

  var names = document.getElementById("names");
  data.nodes.forEach(function (n) {
    var option = document.createElement("option");
    option.value = n.label;
    names.appendChild(option);
  });
  document.getElementById("search").addEventListener("change", function (ev) {
    var wanted = ev.target.value.trim().toLowerCase();
    var found = data.nodes.find(function (n) { return n.label.toLowerCase() === wanted; });
    if (!found) { return; }
    network.selectNodes([found.id]);
    network.focus(found.id, { scale: 1.2, animation: true });
    show(found.id);
  });

  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined) { node.textContent = text; }
    if (cls) { node.className = cls; }
    return node;
  }
  function list(title, items) {
    if (!items.length) { return; }
    details.appendChild(el("h3", title));
    var ul = el("ul");
    items.forEach(function (text) { ul.appendChild(el("li", text)); });
    details.appendChild(ul);
  }
  function show(id) {
    var n = byId[id];
    details.replaceChildren();
    details.appendChild(el("h2", n.label));
    details.appendChild(el("div", n.kind === "classe" ? "Classe" : "Entité", "kind"));
    if (n.description) { details.appendChild(el("p", n.description)); }
    if (n.parent) { list("Parent", [n.parent]); }
    if (n.types && n.types.length) { list("Types", n.types); }
    list("Attributs", Object.keys(n.attributes || {}).map(function (k) {
      return k + " : " + n.attributes[k].join(", ");
    }));
    var out = [], inc = [];
    data.edges.forEach(function (e) {
      if (e.kind === "type") { return; }
      var label = e.kind === "relation" ? e.label : "est_un";
      if (e.from === id) { out.push(label + " → " + byId[e.to].label); }
      if (e.to === id) { inc.push(byId[e.from].label + " → " + label); }
    });
    list("Relations sortantes", out);
    list("Relations entrantes", inc);
  }
  network.on("click", function (params) {
    if (params.nodes.length) { show(params.nodes[0]); }
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
