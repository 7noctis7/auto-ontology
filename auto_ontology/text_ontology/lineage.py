# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""From a file to the chunk, the quote, and the fact that remains.

Later corrections that mention the same name are listed after the quote,
so the chain does not stop at extraction.
"""

from __future__ import annotations

from auto_ontology.text_ontology.studio_models import Project


def lineage_for(project: Project, name: str) -> dict[str, object]:
    """The chain for one class, entity or literal name."""
    steps: list[dict[str, object]] = []
    documents = {item.id: item for item in project.documents}
    for bucket, kind in (
        (project.classes, "class"),
        (project.triplets, "triplet"),
        (project.attributes, "attribute"),
    ):
        for item in bucket:
            label = _label(item, kind)
            if name not in label and getattr(item, "name", None) != name:
                continue
            if kind == "triplet" and name not in {item.subject, item.object}:
                continue
            if kind == "attribute" and item.entity != name and item.value != name:
                continue
            if kind == "class" and item.name != name:
                continue
            for source in item.sources:
                document = documents.get(source.document_id)
                chunk = _chunk(document, source.chunk_index) if document else None
                steps.append(
                    {
                        "kind": kind,
                        "fact": label,
                        "filename": source.filename,
                        "document_id": source.document_id,
                        "chunk_index": source.chunk_index,
                        "quote": source.quote,
                        "preview": chunk.preview if chunk else "",
                        "model": (document.model if document else ""),
                        "genre": document.genre if document else "",
                        "repairs": list(document.warnings)[:4] if document else [],
                    }
                )
    actions = [
        {
            "at": entry.at,
            "name": entry.name,
            "summary": entry.summary,
            "actor": entry.actor,
        }
        for entry in project.action_log
        if name and name in entry.summary
    ]
    return {"name": name, "steps": steps, "actions": actions}


def facts_of_document(project: Project, document_id: str) -> list[dict[str, str]]:
    """Everything one file produced that is still in the project."""
    rows: list[dict[str, str]] = []
    for item in project.triplets:
        if any(source.document_id == document_id for source in item.sources):
            rows.append(
                {
                    "kind": "triplet",
                    "label": f"{item.subject} {item.predicate} {item.object}",
                    "quote": item.sources[0].quote if item.sources else "",
                }
            )
    for item in project.attributes:
        if any(source.document_id == document_id for source in item.sources):
            rows.append(
                {
                    "kind": "attribute",
                    "label": f"{item.entity}.{item.key} = {item.value}",
                    "quote": item.sources[0].quote if item.sources else "",
                }
            )
    return rows


def _label(item: object, kind: str) -> str:
    if kind == "class":
        return str(getattr(item, "name", ""))
    if kind == "triplet":
        return f"{item.subject} {item.predicate} {item.object}"
    return f"{item.entity} {item.key} {item.value}"


def _chunk(document: object, index: int) -> object | None:
    for note in getattr(document, "chunk_notes", []):
        if note.index == index:
            return note
    return None
