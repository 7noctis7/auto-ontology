# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Faceted search and saved object sets.

A set stores the filter, not a frozen list, unless the person pins ids.
The same filter is what the graph, the export and the API apply.
"""

from __future__ import annotations

from auto_ontology.text_ontology.studio_models import Project


def match_query(row: dict[str, object], query: dict[str, str]) -> bool:
    """True when *row* satisfies every filled facet. Facets combine with AND."""
    text = str(query.get("q") or "").casefold().strip()
    if text:
        blob = " ".join(
            str(row.get(key) or "")
            for key in ("label", "family", "description", "quote", "types")
        ).casefold()
        if text not in blob:
            return False
    for key, field in (
        ("type", "family"),
        ("document", "documents"),
        ("link", "predicates"),
        ("status", "status"),
        ("scope", "scope"),
    ):
        wanted = str(query.get(key) or "").strip()
        if not wanted:
            continue
        value = row.get(field)
        if isinstance(value, list):
            if wanted not in [str(item) for item in value]:
                return False
        elif str(value or "") != wanted:
            return False
    if query.get("shared") == "1" and row.get("scope") != "shared":
        return False
    if query.get("orphan") == "1" and not row.get("orphan"):
        return False
    return True


def search_rows(
    rows: list[dict[str, object]], query: dict[str, str]
) -> list[dict[str, object]]:
    """Rows matching *query*, in the order they were given."""
    pinned = [item for item in (query.get("ids") or "").split(",") if item]
    if pinned:
        wanted = set(pinned)
        return [row for row in rows if str(row.get("id")) in wanted]
    return [row for row in rows if match_query(row, query)]


def compile_where(where: dict[str, object] | None) -> dict[str, str]:
    """Turn a small filter tree into the facet query the page already uses."""
    if not where:
        return {}
    query: dict[str, str] = {}
    _walk(where, query)
    return query


def _walk(node: object, query: dict[str, str]) -> None:
    if not isinstance(node, dict):
        return
    if "and" in node and isinstance(node["and"], list):
        for child in node["and"]:
            _walk(child, query)
        return
    for operator in ("eq", "contains", "gt", "gte", "lt", "lte"):
        if operator not in node or not isinstance(node[operator], dict):
            continue
        body = node[operator]
        field = str(body.get("field") or "")
        value = str(body.get("value") or "")
        mapped = {
            "name": "q",
            "type": "type",
            "document": "document",
            "link": "link",
            "status": "status",
        }.get(field, field)
        if operator == "contains" or field == "name":
            query["q"] = value
        elif operator == "eq":
            query[mapped] = value


def objects_of_type(project: Project, type_name: str) -> list[dict[str, str]]:
    """Unique instances whose type name matches, classes included when asked."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if any(cls.name == type_name for cls in project.ontology.classes):
        for triplet in project.ontology.triplets:
            for name, kind in (
                (triplet.subject, triplet.subject_type),
                (triplet.object, triplet.object_type),
            ):
                if kind == type_name and name not in seen:
                    seen.add(name)
                    rows.append({"id": name, "name": name, "type": type_name})
    if not rows and any(cls.name == type_name for cls in project.ontology.classes):
        rows.append({"id": type_name, "name": type_name, "type": type_name})
    return rows


def page_rows(
    rows: list[dict[str, object]], token: str, size: int = 20
) -> dict[str, object]:
    """A slice plus the token of the next slice. Tokens are offsets."""
    try:
        start = int(token or "0")
    except ValueError:
        start = 0
    start = max(0, start)
    chunk = rows[start : start + size]
    nxt = "" if start + size >= len(rows) else str(start + size)
    return {"data": chunk, "nextPageToken": nxt, "total": len(rows)}


def rows_from_project(
    project: Project, view_nodes: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Nodes plus the citations a search should see."""
    quotes: dict[str, str] = {}
    predicates: dict[str, list[str]] = {}
    for fact in project.triplets:
        for name in (fact.subject, fact.object):
            if fact.sources and name not in quotes:
                quotes[name] = fact.sources[0].quote
            predicates.setdefault(name, []).append(fact.predicate)
    rows = []
    for node in view_nodes:
        label = str(node.get("label") or "")
        rows.append(
            {
                **node,
                "quote": quotes.get(label, ""),
                "predicates": predicates.get(label, []),
                "status": node.get("status") or "experimental",
            }
        )
    return rows
