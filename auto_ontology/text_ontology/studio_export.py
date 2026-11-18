# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exports the studio offers from the page.

HTML, Mermaid, Turtle and Cypher reuse the package exporters. The HTML
page inlines the vendored vis-network build, so the downloaded file opens
from disk without a network. CSV and JSON-LD are added here and are not
part of the shared export API.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from auto_ontology.text_ontology.analysis import dashboard_html
from auto_ontology.text_ontology.export import (
    DEFAULT_BASE_IRI,
    _VIS_NETWORK_URL,
    ExportFormat,
    _turtle_string,
    export_ontology,
    to_html,
    to_turtle,
)
from auto_ontology.text_ontology.standards import local_name, shacl_turtle
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.learning import training_rows
from auto_ontology.text_ontology.studio_models import Project
from auto_ontology.text_ontology.view import build_view

_VENDOR = (
    Path(__file__).resolve().parent / "app" / "static" / "vendor" / "vis-network.min.js"
)

_FORMATS = {
    "html": ("ontologie.html", "text/html; charset=utf-8"),
    "mermaid": ("ontologie.mmd", "text/vnd.mermaid; charset=utf-8"),
    "turtle": ("ontologie.ttl", "text/turtle; charset=utf-8"),
    "cypher": ("ontologie.cypher", "application/x-cypher-query; charset=utf-8"),
    "json": ("ontologie.json", "application/json; charset=utf-8"),
    "csv": ("ontologie.csv", "text/csv; charset=utf-8"),
    "jsonld": ("ontologie.jsonld", "application/ld+json; charset=utf-8"),
    "project": ("projet.json", "application/json; charset=utf-8"),
    "dashboard": ("tableaux.html", "text/html; charset=utf-8"),
    "jsonl": ("triplets.jsonl", "application/jsonl; charset=utf-8"),
}


def export_formats() -> dict[str, tuple[str, str]]:
    """Download filename and media type of each studio format."""
    return dict(_FORMATS)


def render_export(project: Project, export_format: str) -> tuple[str, str, str]:
    """Return ``(body, filename, media_type)`` for *export_format*."""
    if export_format not in _FORMATS:
        raise ValueError(f"Format inconnu : {export_format}.")
    filename, media = _FORMATS[export_format]
    ontology = project.ontology
    title = project.name or "Ontologie"
    if export_format == "html":
        return offline_html(ontology, title), filename, media
    if export_format == "json":
        body = json.dumps(ontology.model_dump(), ensure_ascii=False, indent=2) + "\n"
        return body, filename, media
    if export_format == "project":
        return project.model_dump_json(indent=2) + "\n", filename, media
    if export_format == "csv":
        return to_csv(project), filename, media
    if export_format == "jsonld":
        return to_jsonld(project), filename, media
    if export_format == "turtle":
        return _turtle(project), filename, media
    if export_format == "dashboard":
        return _dashboard(project), filename, media
    if export_format == "jsonl":
        rows = training_rows(project)
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        return body, filename, media
    rendered = export_ontology(ontology, ExportFormat(export_format), title=title)
    return rendered, filename, media


def offline_html(ontology: TextOntology, title: str) -> str:
    """The interactive graph page, with vis-network inlined."""
    page = to_html(ontology, title=title)
    script = _VENDOR.read_text(encoding="utf-8").replace("</", "<\\/")
    needle = f'<script src="{_VIS_NETWORK_URL}"></script>'
    inline = f"<script>{script}</script>"
    if needle not in page:
        raise RuntimeError("The HTML export no longer references vis-network.")
    return page.replace(needle, inline, 1)


def to_csv(project: Project) -> str:
    """One row per triplet or attribute, with its source filenames."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "kind",
            "subject",
            "predicate",
            "object",
            "subject_type",
            "object_type",
            "documents",
            "quote",
        ]
    )
    sources = {
        (item.subject, item.predicate, item.object): item.sources
        for item in project.triplets
    }
    for triplet in project.ontology.triplets:
        found = sources.get((triplet.subject, triplet.predicate, triplet.object), [])
        writer.writerow(
            [
                "triplet",
                triplet.subject,
                triplet.predicate,
                triplet.object,
                triplet.subject_type,
                triplet.object_type,
                "; ".join(sorted({source.filename for source in found})),
                found[0].quote if found else "",
            ]
        )
    attribute_sources = {
        (item.entity, item.key, item.value): item.sources for item in project.attributes
    }
    for attribute in project.ontology.attributes:
        found = attribute_sources.get(
            (attribute.entity, attribute.key, attribute.value), []
        )
        writer.writerow(
            [
                "attribute",
                attribute.entity,
                attribute.key,
                attribute.value,
                "",
                "",
                "; ".join(sorted({source.filename for source in found})),
                found[0].quote if found else "",
            ]
        )
    return buffer.getvalue()


def _turtle(project: Project) -> str:
    aliases: dict[str, list[str]] = {}
    for alias in project.memory.aliases:
        aliases.setdefault(alias.target, []).append(alias.source)
    base = project.base_iri.strip() or DEFAULT_BASE_IRI
    body = to_turtle(
        project.ontology,
        base_iri=base,
        title=project.name,
        created=project.created_at,
        creator="local",
        aliases=aliases,
    )
    extra: list[str] = []
    for mapping in project.mappings:
        if not mapping.accepted:
            continue
        name = local_name(mapping.source, "class")
        predicate = mapping.predicate
        if predicate.startswith("owl:"):
            predicate = predicate
        extra.append(f":{name} {predicate} <{mapping.iri}> .")
    parts = [body, shacl_turtle(project, base)]
    if extra:
        parts.append("# Alignements retenus\n" + "\n".join(extra) + "\n")
    provenance = _provenance(project)
    if provenance:
        parts.append(provenance)
    return "\n".join(parts)


def _prov_token(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum())
    return cleaned[:32] or "x"


def _provenance(project: Project) -> str:
    """PROV-O for each document, its extraction run, and the individuals it produced."""
    if not project.documents:
        return ""
    lines = ["# Provenance"]
    known = {document.id for document in project.documents}
    for document in project.documents:
        token = _prov_token(document.id)
        lines.append(f":doc{token} a prov:Entity ;")
        lines.append(f"    rdfs:label {_turtle_string(document.filename)} .")
        lines.append(f":run{token} a prov:Activity ;")
        lines.append('    rdfs:label "extraction" ;')
        lines.append(
            f"    dcterms:hasVersion {_turtle_string(document.prompt_version or '1')} ;"
        )
        lines.append(f"    prov:used :doc{token} .")
        if document.model:
            lines.append(f":agent{token} a prov:SoftwareAgent ;")
            lines.append(f"    rdfs:label {_turtle_string(document.model)} .")
            lines.append(f":run{token} prov:wasAssociatedWith :agent{token} .")
    seen: set[tuple[str, str]] = set()
    for fact in project.triplets:
        subject = local_name(fact.subject, "individual")
        for source in fact.sources:
            if source.document_id not in known:
                continue
            token = _prov_token(source.document_id)
            passage = ""
            if source.quote:
                passage = f"passage{token}c{source.chunk_index}"
                key = ("passage", passage)
                if key not in seen:
                    seen.add(key)
                    lines.append(f":{passage} a prov:Entity ;")
                    lines.append(
                        f"    rdfs:label {_turtle_string(source.quote[:240])} ;"
                    )
                    lines.append(f"    prov:wasDerivedFrom :doc{token} .")
            for predicate, target in (
                ("prov:wasDerivedFrom", f":doc{token}"),
                ("prov:wasGeneratedBy", f":run{token}"),
            ):
                edge = (f"{subject} {predicate}", target)
                if edge not in seen:
                    seen.add(edge)
                    lines.append(f":{subject} {predicate} {target} .")
            if passage:
                edge = (f"{subject} prov:wasDerivedFrom", f":{passage}")
                if edge not in seen:
                    seen.add(edge)
                    lines.append(f":{subject} prov:wasDerivedFrom :{passage} .")
    return "\n".join(lines) + "\n"


def to_jsonld(project: Project) -> str:
    """JSON-LD with a context, CamelCase ids, and separate class IRIs."""
    ontology = project.ontology
    base = project.base_iri.strip() or DEFAULT_BASE_IRI
    graph: list[dict[str, object]] = []
    class_names = {cls.name for cls in ontology.classes}
    for cls in ontology.classes:
        node: dict[str, object] = {
            "@id": local_name(cls.name, "class"),
            "@type": "owl:Class",
            "label": cls.name,
        }
        if cls.parent:
            node["subClassOf"] = {"@id": local_name(cls.parent, "class")}
        if cls.description:
            node["definition"] = cls.description
        graph.append(node)
    seen: set[str] = set()
    for triplet in ontology.triplets:
        if triplet.predicate == "est_un" and triplet.object in class_names:
            if triplet.subject in class_names:
                continue
            node_id = local_name(triplet.subject, "individual")
            graph.append(
                {
                    "@id": node_id,
                    "@type": [
                        "owl:NamedIndividual",
                        local_name(triplet.object, "class"),
                    ],
                    "label": triplet.subject,
                }
            )
            continue
        if triplet.subject in class_names or triplet.object in class_names:
            continue
        node_id = local_name(triplet.subject, "individual")
        if node_id in seen:
            continue
        seen.add(node_id)
        graph.append(
            {
                "@id": node_id,
                "@type": [
                    "owl:NamedIndividual",
                    local_name(triplet.subject_type, "class"),
                ],
                "label": triplet.subject,
                local_name(triplet.predicate, "property"): {
                    "@id": local_name(triplet.object, "individual")
                },
            }
        )
    for attribute in ontology.attributes:
        if attribute.entity in class_names:
            continue
        graph.append(
            {
                "@id": local_name(attribute.entity, "individual"),
                local_name(attribute.key, "property"): attribute.value,
            }
        )
    document = {
        "@context": {
            "@vocab": base,
            "owl": "http://www.w3.org/2002/07/owl#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "label": {"@id": "rdfs:label", "@language": "fr"},
            "definition": "skos:definition",
            "subClassOf": {"@id": "rdfs:subClassOf", "@type": "@id"},
        },
        "@graph": graph,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _dashboard(project: Project) -> str:
    view = build_view(
        project,
        path="",
        can_undo=False,
        can_redo=False,
        llm={},
        projects=[],
    )
    panels = view.get("analysis")
    return dashboard_html(project, panels if isinstance(panels, dict) else {})
