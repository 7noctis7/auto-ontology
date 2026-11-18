# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Derived views: communities, matrices, timelines and dashboards.

Everything here is computed from the project file. Nothing is stored except
the ids of dashboards the person pinned.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from auto_ontology.text_ontology.profile import GENRE_LABELS_FR
from auto_ontology.text_ontology.studio_models import Project

_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def annotate_graph(
    nodes: list[dict[str, object]], edges: list[dict[str, object]]
) -> None:
    """Set ``community`` and ``scope`` on each node. Communities are labels, not a layout."""
    labels = {str(node["id"]): index for index, node in enumerate(nodes)}
    relation = [edge for edge in edges if edge.get("kind") != "type"]
    for _round in range(6):
        nxt = dict(labels)
        for node in nodes:
            votes: Counter[int] = Counter()
            node_id = str(node["id"])
            for edge in relation:
                if edge["from"] == node_id and str(edge["to"]) in labels:
                    votes[labels[str(edge["to"])]] += 1
                elif edge["to"] == node_id and str(edge["from"]) in labels:
                    votes[labels[str(edge["from"])]] += 1
            if votes:
                nxt[node_id] = votes.most_common(1)[0][0]
        labels = nxt
    compact: dict[int, int] = {}
    for node in nodes:
        raw = labels[str(node["id"])]
        if raw not in compact:
            compact[raw] = len(compact)
        documents = node.get("documents") or []
        count = len(documents) if isinstance(documents, list) else 0
        node["community"] = compact[raw]
        if count > 1:
            node["scope"] = "shared"
        elif count == 1:
            node["scope"] = "specific"
        else:
            node["scope"] = "unlinked"


def build_panels(project: Project, nodes: list[dict[str, object]]) -> dict[str, object]:
    """Matrices, timeline, coverage and the dashboards the page can pin."""
    matrix = _matrix(project)
    timeline = _timeline(project)
    coverage = _coverage(project, nodes)
    genres = Counter(document.genre or "other" for document in project.documents)
    return {
        "matrix": matrix,
        "timeline": timeline,
        "coverage": coverage,
        "genres": [
            {
                "id": genre,
                "label": GENRE_LABELS_FR.get(genre, genre),
                "count": count,
            }
            for genre, count in genres.most_common()
        ],
        "dashboards": propose_dashboards(project, nodes, matrix, timeline, coverage),
        "pinned": list(project.pinned_dashboards),
        "scores": [point.model_dump() for point in project.memory.scores[-20:]],
        "aliases": len(project.memory.aliases),
        "rejected": len(project.memory.rejected),
    }


def propose_dashboards(
    project: Project,
    nodes: list[dict[str, object]],
    matrix: dict[str, object],
    timeline: list[dict[str, object]],
    coverage: dict[str, object],
) -> list[dict[str, object]]:
    """A short list. Each item is one chart, not a page of widgets."""
    entities = [
        {"name": str(node["label"]), "count": int(node.get("degree") or 0)}
        for node in nodes
        if node.get("kind") == "entity"
    ]
    entities.sort(key=lambda item: item["count"], reverse=True)
    shared = sum(1 for node in nodes if node.get("scope") == "shared")
    specific = sum(1 for node in nodes if node.get("scope") == "specific")
    metrics = _metrics(project)
    genre_bars = [
        {
            "name": GENRE_LABELS_FR.get(document.genre, document.genre),
            "count": 1,
        }
        for document in project.documents
    ]
    genre_counts: Counter[str] = Counter(item["name"] for item in genre_bars)
    boards: list[dict[str, object]] = [
        {
            "id": "connected",
            "title": "Concepts les plus reliés",
            "why": "La taille du graphe suit le nombre de relations.",
            "kind": "bars",
            "items": entities[:8],
        },
        {
            "id": "coverage",
            "title": "Faits par document",
            "why": "Un document creux a été mal lu, ou il parle d'autre chose.",
            "kind": "bars",
            "items": [
                {"name": str(item["filename"]), "count": int(item["facts"])}
                for item in coverage.get("documents", [])
                if isinstance(item, dict)
            ],
        },
        {
            "id": "shared",
            "title": "Communs et propres",
            "why": "Un concept présent dans plusieurs documents relie le corpus.",
            "kind": "bars",
            "items": [
                {"name": "Communs", "count": shared},
                {"name": "Propres à un document", "count": specific},
            ],
        },
        {
            "id": "genres",
            "title": "Types de documents",
            "why": "Le type est une estimation, corrigeable dans Documents.",
            "kind": "bars",
            "items": [
                {"name": name, "count": count} for name, count in genre_counts.items()
            ],
        },
    ]
    if metrics:
        boards.append(
            {
                "id": "metrics",
                "title": "Quantités extraites",
                "why": "Valeurs numériques trouvées comme attributs.",
                "kind": "table",
                "items": metrics[:12],
            }
        )
    if timeline:
        boards.append(
            {
                "id": "timeline",
                "title": "Repères datés",
                "why": "Années lues dans les attributs.",
                "kind": "timeline",
                "items": timeline[:12],
            }
        )
    if matrix.get("rows"):
        boards.append(
            {
                "id": "matrix",
                "title": "Relations entre classes",
                "why": "Combien de faits relient une classe à une autre.",
                "kind": "matrix",
                "items": [],
            }
        )
    return boards


def dashboard_html(project: Project, panels: dict[str, object]) -> str:
    """A single HTML file of the pinned dashboards, or of all of them."""
    pinned = set(project.pinned_dashboards)
    boards = panels.get("dashboards") or []
    chosen = [
        board
        for board in boards
        if isinstance(board, dict) and (not pinned or board.get("id") in pinned)
    ]
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{_esc(project.name)} — tableaux</title>",
        "<style>body{font:15px/1.45 sans-serif;margin:24px;color:#1c2430}",
        "h1{font-size:20px} article{margin:18px 0;padding:12px;border:1px solid #d9e0ea}",
        ".bar{height:8px;background:#e6edf5;border-radius:4px;margin:4px 0}",
        ".bar span{display:block;height:100%;background:#0072b2}",
        "td,th{text-align:left;padding:4px 8px;border-bottom:1px solid #d9e0ea}</style>",
        f"<h1>{_esc(project.name)}</h1>",
        "<p>Tableaux dérivés de l'ontologie. Les chiffres sont des comptes.</p>",
    ]
    for board in chosen:
        if not isinstance(board, dict):
            continue
        parts.append("<article>")
        parts.append(f"<h2>{_esc(str(board.get('title', '')))}</h2>")
        parts.append(f"<p>{_esc(str(board.get('why', '')))}</p>")
        kind = board.get("kind")
        items = board.get("items") if isinstance(board.get("items"), list) else []
        if kind == "bars":
            counts = [
                int(item.get("count") or 0) for item in items if isinstance(item, dict)
            ]
            top = max(counts or [1])
            for item in items:
                if not isinstance(item, dict):
                    continue
                width = int(100 * int(item.get("count") or 0) / top)
                parts.append(
                    f"<div>{_esc(str(item.get('name')))} · {item.get('count')}"
                    f"<div class='bar'><span style='width:{width}%'></span></div></div>"
                )
        elif kind == "table":
            parts.append(
                "<table><tr><th>Entité</th><th>Attribut</th><th>Valeur</th></tr>"
            )
            for item in items:
                if isinstance(item, dict):
                    parts.append(
                        "<tr><td>"
                        + "</td><td>".join(
                            _esc(str(item.get(key, "")))
                            for key in ("entity", "key", "value")
                        )
                        + "</td></tr>"
                    )
            parts.append("</table>")
        elif kind == "timeline":
            for item in items:
                if isinstance(item, dict):
                    parts.append(
                        f"<div>{_esc(str(item.get('year')))} — "
                        f"{_esc(str(item.get('label')))}</div>"
                    )
        elif kind == "matrix":
            parts.append(
                "<p>Matrice des classes : ouvrez la vue Analyse dans l'application.</p>"
            )
        parts.append("</article>")
    return "\n".join(parts)


def _matrix(project: Project) -> dict[str, object]:
    counts: Counter[tuple[str, str]] = Counter()
    for triplet in project.ontology.triplets:
        if triplet.subject_type and triplet.object_type:
            counts[(triplet.subject_type, triplet.object_type)] += 1
    labels = sorted({name for pair in counts for name in pair})
    rows = []
    for source in labels:
        rows.append(
            {
                "name": source,
                "cells": [counts[(source, target)] for target in labels],
            }
        )
    return {"labels": labels, "rows": rows}


def _timeline(project: Project) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for attribute in project.ontology.attributes:
        match = _YEAR.search(attribute.value) or _YEAR.search(attribute.key)
        if not match:
            continue
        found.append(
            {
                "year": match.group(1),
                "label": f"{attribute.entity} · {attribute.key}",
                "value": attribute.value,
            }
        )
    found.sort(key=lambda item: str(item["year"]))
    return found


def _coverage(project: Project, nodes: list[dict[str, object]]) -> dict[str, object]:
    concepts = [str(node["label"]) for node in nodes if node.get("kind") == "class"][
        :12
    ]
    rows = []
    for document in project.documents:
        present = []
        for name in concepts:
            hit = any(
                source.document_id == document.id
                for item in project.classes
                if item.name == name
                for source in item.sources
            )
            present.append(hit)
        fact_count = sum(
            1
            for item in (*project.triplets, *project.attributes)
            if any(source.document_id == document.id for source in item.sources)
        )
        rows.append(
            {
                "id": document.id,
                "filename": document.filename,
                "facts": fact_count,
                "present": present,
            }
        )
    return {"concepts": concepts, "documents": rows}


def _metrics(project: Project) -> list[dict[str, str]]:
    rows = []
    for attribute in project.ontology.attributes:
        if _NUMBER.match(attribute.value.strip()):
            rows.append(
                {
                    "entity": attribute.entity,
                    "key": attribute.key,
                    "value": attribute.value,
                }
            )
    return rows


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def genre_ids(project: Project, document_ids: list[str]) -> list[str]:
    """Genres of the given documents, for colouring a node."""
    by_id = {document.id: document.genre for document in project.documents}
    return sorted({by_id[item] for item in document_ids if item in by_id})


def facts_by_document(project: Project) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in (*project.triplets, *project.attributes):
        for source in item.sources:
            counts[source.document_id] += 1
    return counts
