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

from auto_ontology.text_ontology.export import (
    _VIS_NETWORK_URL,
    ExportFormat,
    export_ontology,
    to_html,
)
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.studio_models import Project

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
        return to_jsonld(ontology), filename, media
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


def to_jsonld(ontology: TextOntology) -> str:
    """A compact JSON-LD graph: classes, individuals and relations."""
    graph: list[dict[str, object]] = []
    class_names = {cls.name for cls in ontology.classes}
    for cls in ontology.classes:
        node: dict[str, object] = {
            "@id": cls.name,
            "@type": "owl:Class",
            "rdfs:label": cls.name,
        }
        if cls.parent:
            node["rdfs:subClassOf"] = {"@id": cls.parent}
        if cls.description:
            node["rdfs:comment"] = cls.description
        graph.append(node)
    for triplet in ontology.triplets:
        if triplet.predicate == "est_un" and triplet.object in class_names:
            continue
        graph.append(
            {
                "@id": triplet.subject,
                "@type": triplet.subject_type,
                triplet.predicate: {"@id": triplet.object},
            }
        )
    for attribute in ontology.attributes:
        graph.append(
            {
                "@id": attribute.entity,
                attribute.key: attribute.value,
            }
        )
    document = {
        "@context": {
            "owl": "http://www.w3.org/2002/07/owl#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "@vocab": "http://example.org/auto-ontology#",
        },
        "@graph": graph,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
