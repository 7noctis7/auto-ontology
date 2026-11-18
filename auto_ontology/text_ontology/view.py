# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one payload the studio UI renders: graph, KPIs, glossary, facts.

Numbers are counts a person can check. An orphan is an entity with no
relation to another entity (its type link does not count), or a class with
no parent, no subclass and no entity. Node degree uses the same edges the
graph draws, except type links, so a class is large when it sits in a
hierarchy and an entity is large when it has many relations.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from auto_ontology.text_ontology.analysis import annotate_graph, build_panels, genre_ids
from auto_ontology.text_ontology.schema_layer import infer_base_type, sync_schema
from auto_ontology.text_ontology.standards import (
    alignment_suggestions,
    competency_rows,
    shacl_checks,
)
from auto_ontology.text_ontology.export import _graph
from auto_ontology.text_ontology.provenance import entity_key
from auto_ontology.text_ontology.studio_models import Project


def _root(name: str, parents: dict[str, str | None]) -> str:
    seen: set[str] = set()
    current = name
    while current in parents and parents[current] and current not in seen:
        seen.add(current)
        current = parents[current] or current
    return current


def _similar(left: str, right: str) -> bool:
    a, b = entity_key(left), entity_key(right)
    if not a or not b or a == b:
        return False
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return True
    if abs(len(a) - len(b)) > 2 or min(len(a), len(b)) < 5:
        return False
    return _distance(a, b) <= 2


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (char != other)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def build_view(
    project: Project,
    *,
    path: str,
    can_undo: bool,
    can_redo: bool,
    llm: dict[str, object],
    projects: list[dict[str, object]],
) -> dict[str, object]:
    """Everything the page needs for *project*, in one response."""
    graph = _graph(project.ontology)
    parents = dict(graph.classes)
    degree: dict[tuple[str, str], int] = defaultdict(int)
    for name, parent in graph.classes.items():
        if parent:
            degree[("c", name)] += 1
            degree[("c", parent)] += 1
    for child, parent in graph.extra_parents:
        degree[("c", child)] += 1
        degree[("c", parent)] += 1
    for triplet in graph.relations:
        degree[("e", triplet.subject)] += 1
        if triplet.object != triplet.subject:
            degree[("e", triplet.object)] += 1

    children: dict[str, int] = Counter(
        parent for parent in graph.classes.values() if parent
    )
    instances: dict[str, int] = Counter()
    for entity in graph.entities.values():
        for type_name in entity.types:
            instances[type_name] += 1

    triplet_sources = {
        (item.subject, item.predicate, item.object): item.sources
        for item in project.triplets
    }
    attribute_sources = {
        (item.entity, item.key, item.value): item.sources for item in project.attributes
    }
    class_sources = {item.name: item.sources for item in project.classes}
    docs_of_node: dict[tuple[str, str], set[str]] = defaultdict(set)

    def remember(kind: str, name: str, document_ids: set[str]) -> None:
        docs_of_node[(kind, name)].update(document_ids)

    nodes: list[dict[str, object]] = []
    class_orphans: list[str] = []
    for name, parent in graph.classes.items():
        sources = class_sources.get(name, [])
        document_ids = {source.document_id for source in sources}
        remember("c", name, document_ids)
        orphan = (
            parent is None
            and children[name] == 0
            and instances[name] == 0
            and name not in {parent_name for _, parent_name in graph.extra_parents}
            and name not in {child for child, _ in graph.extra_parents}
        )
        if orphan:
            class_orphans.append(name)
        nodes.append(
            {
                "id": f"c:{name}",
                "label": name,
                "kind": "class",
                "family": _root(name, parents),
                "degree": degree[("c", name)],
                "orphan": orphan,
                "description": graph.descriptions.get(name, ""),
                "parent": parent,
                "types": [],
                "attributes": [
                    {"key": key, "value": ", ".join(values)}
                    for key, values in graph.class_attributes.get(name, {}).items()
                ],
                "documents": sorted(document_ids),
                "genres": genre_ids(project, list(document_ids)),
            }
        )

    entity_orphans: list[str] = []
    for entity in graph.entities.values():
        family = ""
        if entity.types:
            family = _root(entity.types[0], parents)
        document_ids: set[str] = set()
        for triplet in graph.relations:
            if entity.name in {triplet.subject, triplet.object}:
                for source in triplet_sources.get(
                    (triplet.subject, triplet.predicate, triplet.object), []
                ):
                    document_ids.add(source.document_id)
        for key, values in entity.attributes.items():
            for value in values:
                for source in attribute_sources.get((entity.name, key, value), []):
                    document_ids.add(source.document_id)
        remember("e", entity.name, document_ids)
        orphan = degree[("e", entity.name)] == 0
        if orphan:
            entity_orphans.append(entity.name)
        nodes.append(
            {
                "id": f"e:{entity.name}",
                "label": entity.name,
                "kind": "entity",
                "family": family or "Entité",
                "degree": degree[("e", entity.name)],
                "orphan": orphan,
                "description": "",
                "parent": None,
                "types": list(entity.types),
                "attributes": [
                    {"key": key, "value": ", ".join(values)}
                    for key, values in entity.attributes.items()
                ],
                "documents": sorted(document_ids),
                "genres": genre_ids(project, list(document_ids)),
            }
        )

    edges: list[dict[str, object]] = []
    edge_id = 0

    def add_edge(source: str, target: str, label: str, kind: str, support: int) -> None:
        nonlocal edge_id
        edge_id += 1
        edges.append(
            {
                "id": f"edge-{edge_id}",
                "from": source,
                "to": target,
                "label": label,
                "kind": kind,
                "support": support,
            }
        )

    for name, parent in graph.classes.items():
        if parent:
            add_edge(f"c:{name}", f"c:{parent}", "est_un", "hierarchy", 1)
    for child, parent in graph.extra_parents:
        add_edge(f"c:{child}", f"c:{parent}", "est_un", "hierarchy", 1)
    for entity in graph.entities.values():
        for type_name in entity.types:
            if type_name in graph.classes:
                add_edge(f"e:{entity.name}", f"c:{type_name}", "", "type", 1)
    for triplet in graph.relations:
        sources = triplet_sources.get(
            (triplet.subject, triplet.predicate, triplet.object), []
        )
        add_edge(
            f"e:{triplet.subject}",
            f"e:{triplet.object}",
            triplet.predicate,
            "relation",
            max(1, len(sources)),
        )

    facts: list[dict[str, object]] = []
    for triplet in project.ontology.triplets:
        sources = triplet_sources.get(
            (triplet.subject, triplet.predicate, triplet.object), []
        )
        facts.append(
            {
                "kind": "triplet",
                "subject": triplet.subject,
                "predicate": triplet.predicate,
                "object": triplet.object,
                "subject_type": triplet.subject_type,
                "object_type": triplet.object_type,
                "support": len(sources),
                "documents": sorted({source.filename for source in sources}),
                "sources": [source.model_dump() for source in sources],
            }
        )
    for attribute in project.ontology.attributes:
        sources = attribute_sources.get(
            (attribute.entity, attribute.key, attribute.value), []
        )
        facts.append(
            {
                "kind": "attribute",
                "subject": attribute.entity,
                "predicate": attribute.key,
                "object": attribute.value,
                "subject_type": "",
                "object_type": "",
                "support": len(sources),
                "documents": sorted({source.filename for source in sources}),
                "sources": [source.model_dump() for source in sources],
            }
        )

    glossary = [
        {
            "name": name,
            "parent": parent,
            "description": graph.descriptions.get(name, ""),
            "entities": instances[name],
            "documents": sorted(
                {source.filename for source in class_sources.get(name, [])}
            ),
        }
        for name, parent in graph.classes.items()
    ]
    top_classes = [
        {"name": name, "count": count}
        for name, count in instances.most_common(8)
        if count
    ]
    predicates = Counter(triplet.predicate for triplet in graph.relations)
    top_predicates = [
        {"name": name, "count": count} for name, count in predicates.most_common(8)
    ]

    per_document: list[dict[str, object]] = []
    for document in project.documents:
        fact_count = 0
        for item in (*project.triplets, *project.attributes):
            if any(source.document_id == document.id for source in item.sources):
                fact_count += 1
        per_document.append(
            {
                "id": document.id,
                "filename": document.filename,
                "char_count": document.char_count,
                "facts": fact_count,
                "status": document.status,
                "chunks_total": document.chunks_total,
                "chunks_failed": list(document.chunks_failed),
                "chunks_cached": list(document.chunks_cached),
                "warnings": list(document.warnings),
                "duration_s": document.duration_s,
                "model": document.model,
                "noise_ratio": document.noise_ratio,
                "added_at": document.added_at,
                "title": document.title,
                "author": document.author,
                "date": document.date,
                "language": document.language,
                "pages": document.pages,
                "genre": document.genre,
                "genre_confidence": document.genre_confidence,
                "genre_source": document.genre_source,
                "domain": document.domain,
                "domain_confidence": document.domain_confidence,
                "steps": [step.model_dump() for step in document.steps],
                "expectations": [step.model_dump() for step in document.expectations],
            }
        )

    names = [entity.name for entity in graph.entities.values()]
    suggestions: list[dict[str, str]] = []
    limited = names[:200]
    for index, left in enumerate(limited):
        for right in limited[index + 1 :]:
            if _similar(left, right):
                suggestions.append({"a": left, "b": right})
            if len(suggestions) >= 12:
                break
        if len(suggestions) >= 12:
            break

    catalog = sync_schema(project)
    status_of = {item.id: item.status for item in catalog.object_types}
    status_of.update({item.id: item.status for item in catalog.link_types})
    group_of = {item.id: item.group for item in catalog.object_types}
    prop_of = {item.id: item for item in catalog.properties}
    for node in nodes:
        family = str(node.get("family") or "")
        node["status"] = status_of.get(str(node.get("label")), "experimental")
        node["group"] = group_of.get(
            family, group_of.get(str(node.get("label")), "Concepts")
        )
        typed = []
        for attribute in node.get("attributes") or []:
            if not isinstance(attribute, dict):
                continue
            definition = prop_of.get(str(attribute.get("key")))
            typed.append(
                {
                    "key": attribute.get("key"),
                    "value": attribute.get("value"),
                    "base_type": definition.base_type
                    if definition
                    else infer_base_type(str(attribute.get("value") or "")),
                    "visibility": definition.visibility if definition else "normal",
                }
            )
        typed.sort(key=lambda item: 0 if item["visibility"] == "prominent" else 1)
        node["typed_properties"] = typed
    for note in project.notes:
        edge_id += 1
        edges.append(
            {
                "id": f"note-{note.id}",
                "from": f"e:{note.source}",
                "to": f"e:{note.target}",
                "label": note.label or "note",
                "kind": "note",
                "support": 0,
            }
        )
    annotate_graph(nodes, edges)
    panels = build_panels(project, nodes)
    node_count = len(nodes)
    orphan_count = len(class_orphans) + len(entity_orphans)
    last = per_document[-1] if per_document else None
    failed = sum(len(document.chunks_failed) for document in project.documents)
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "path": path,
            "updated_at": project.updated_at,
            "schema_version": project.schema_version,
        },
        "projects": projects,
        "undo": {"can_undo": can_undo, "can_redo": can_redo},
        "llm": llm,
        "stats": {
            "concepts": len(graph.classes),
            "relations": len(graph.relations),
            "facts": len(project.ontology.triplets) + len(project.ontology.attributes),
            "documents": len(project.documents),
            "orphans": orphan_count,
            "orphan_ratio": round(orphan_count / node_count, 3) if node_count else 0,
            "failed_chunks": failed,
            "top_classes": top_classes,
            "top_predicates": top_predicates,
            "per_document": [
                {"id": item["id"], "filename": item["filename"], "facts": item["facts"]}
                for item in per_document
            ],
            "last_document": (
                {
                    "id": last["id"],
                    "filename": last["filename"],
                    "facts": last["facts"],
                }
                if last
                else None
            ),
            "insight_classes": [item["name"] for item in top_classes[:3]],
        },
        "graph": {"nodes": nodes, "edges": edges},
        "glossary": glossary,
        "facts": facts,
        "documents": per_document,
        "suggestions": suggestions,
        "analysis": panels,
        "catalog": project.catalog.model_dump(),
        "object_sets": [item.model_dump() for item in project.object_sets],
        "action_log": [item.model_dump() for item in project.action_log[-30:]],
        "notes": [item.model_dump() for item in project.notes],
        "standards": {
            "checks": [item.model_dump() for item in shacl_checks(project)],
            "alignments": alignment_suggestions(project),
            "questions": competency_rows(project),
            "base_iri": project.base_iri,
        },
    }
