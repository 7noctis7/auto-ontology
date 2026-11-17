# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Questions a person, a script or an assistant asks of one project.

Answers are facts already in the file, with the passage they came from.
There is no free-form generation here: if nothing matches, the answer says so.
"""

from __future__ import annotations

import re
from collections import deque

from auto_ontology.text_ontology.provenance import entity_key
from auto_ontology.text_ontology.studio_models import Project

_WORD = re.compile(r"[0-9A-Za-zÀ-ÿ]{3,}")
_STOP = frozenset(
    """
    the and for with that this from are was were les des une est dans pour qui
    par avec sur son ses aux que qui quoi comment quel quelle quels quelles
    """.split()
)


def search(project: Project, query: str, limit: int = 20) -> dict[str, object]:
    """Concepts, entities and facts whose name contains *query*."""
    needle = query.casefold().strip()
    concepts = [
        cls.name
        for cls in project.ontology.classes
        if needle and needle in cls.name.casefold()
    ]
    entities: list[str] = []
    seen: set[str] = set()
    for triplet in project.ontology.triplets:
        for name in (triplet.subject, triplet.object):
            if needle and needle in name.casefold() and name not in seen:
                seen.add(name)
                entities.append(name)
    facts = [
        _fact(project, triplet.subject, triplet.predicate, triplet.object)
        for triplet in project.ontology.triplets
        if needle
        and needle
        in f"{triplet.subject} {triplet.predicate} {triplet.object}".casefold()
    ]
    return {
        "query": query,
        "concepts": concepts[:limit],
        "entities": entities[:limit],
        "facts": facts[:limit],
    }


def neighbours(project: Project, name: str) -> dict[str, object]:
    """Relations that touch *name*, in either direction."""
    key = entity_key(name)
    outgoing = []
    incoming = []
    for triplet in project.ontology.triplets:
        if entity_key(triplet.subject) == key:
            outgoing.append(
                _fact(project, triplet.subject, triplet.predicate, triplet.object)
            )
        elif entity_key(triplet.object) == key:
            incoming.append(
                _fact(project, triplet.subject, triplet.predicate, triplet.object)
            )
    label = _canonical(project, name)
    return {
        "name": label or name,
        "found": bool(label or outgoing or incoming),
        "outgoing": outgoing,
        "incoming": incoming,
    }


def paths(project: Project, start: str, end: str, limit: int = 3) -> dict[str, object]:
    """Short undirected paths between two names. At most four steps."""
    graph: dict[str, list[tuple[str, str]]] = {}
    for triplet in project.ontology.triplets:
        graph.setdefault(triplet.subject, []).append(
            (triplet.predicate, triplet.object)
        )
        graph.setdefault(triplet.object, []).append(
            (triplet.predicate, triplet.subject)
        )
    source = _canonical(project, start) or start
    target = _canonical(project, end) or end
    found: list[list[dict[str, str]]] = []
    if source not in graph or target not in graph:
        return {"start": source, "end": target, "paths": found}
    queue: deque[list[tuple[str, str]]] = deque([[("", source)]])
    seen = {source}
    while queue and len(found) < limit:
        trail = queue.popleft()
        current = trail[-1][1]
        for predicate, nxt in graph.get(current, []):
            if nxt == target and nxt != source:
                found.append(_path_steps(source, trail[1:] + [(predicate, nxt)]))
                continue
            if nxt in seen or len(trail) >= 4:
                continue
            seen.add(nxt)
            queue.append(trail + [(predicate, nxt)])
    return {"start": source, "end": target, "paths": found}


def answer(project: Project, question: str) -> dict[str, object]:
    """Pick the facts whose words overlap the question, and cite them."""
    tokens = [word for word in _WORD.findall(question.casefold()) if word not in _STOP]
    if not tokens:
        return {"question": question, "answer": "La question est vide.", "facts": []}
    ranked: list[tuple[int, dict[str, object]]] = []
    for triplet in project.ontology.triplets:
        fact = _fact(project, triplet.subject, triplet.predicate, triplet.object)
        blob = " ".join(
            str(fact.get(key, ""))
            for key in ("subject", "predicate", "object", "quote")
        ).casefold()
        score = sum(1 for token in tokens if token in blob)
        if score:
            ranked.append((score, fact))
    ranked.sort(key=lambda item: item[0], reverse=True)
    facts = [fact for _score, fact in ranked[:5]]
    if not facts:
        return {
            "question": question,
            "answer": "Aucun fait du projet ne répond à cette question.",
            "facts": [],
        }
    best = facts[0]
    sentence = (
        f"{best['subject']} — {best['predicate']} → {best['object']}. "
        f"Source : {best.get('filename') or 'document'}."
    )
    return {"question": question, "answer": sentence, "facts": facts}


def compare(project: Project, left_id: str, right_id: str) -> dict[str, object]:
    """Concepts and facts that two documents share, and those each keeps."""
    left = _names(project, left_id)
    right = _names(project, right_id)
    return {
        "left": left_id,
        "right": right_id,
        "shared": sorted(left & right),
        "only_left": sorted(left - right),
        "only_right": sorted(right - left),
    }


def concepts(project: Project) -> list[dict[str, object]]:
    """Every class, with its parent and the documents that mentioned it."""
    sources = {item.name: item.sources for item in project.classes}
    return [
        {
            "name": cls.name,
            "parent": cls.parent,
            "description": cls.description,
            "documents": sorted(
                {source.filename for source in sources.get(cls.name, [])}
            ),
        }
        for cls in project.ontology.classes
    ]


def list_facts(project: Project, limit: int = 200) -> list[dict[str, object]]:
    """Triplets with their passages."""
    rows = [
        _fact(project, triplet.subject, triplet.predicate, triplet.object)
        for triplet in project.ontology.triplets
    ]
    return rows[:limit]


def _fact(
    project: Project, subject: str, predicate: str, obj: str
) -> dict[str, object]:
    quote = ""
    filename = ""
    document_id = ""
    for item in project.triplets:
        if (
            item.subject == subject
            and item.predicate == predicate
            and item.object == obj
        ):
            if item.sources:
                quote = item.sources[0].quote
                filename = item.sources[0].filename
                document_id = item.sources[0].document_id
            break
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "quote": quote,
        "filename": filename,
        "document_id": document_id,
    }


def _canonical(project: Project, name: str) -> str:
    key = entity_key(name)
    for triplet in project.ontology.triplets:
        for candidate in (triplet.subject, triplet.object):
            if entity_key(candidate) == key:
                return candidate
    for cls in project.ontology.classes:
        if entity_key(cls.name) == key:
            return cls.name
    return ""


def _names(project: Project, document_id: str) -> set[str]:
    names: set[str] = set()
    for item in project.classes:
        if any(source.document_id == document_id for source in item.sources):
            names.add(item.name)
    for item in project.triplets:
        if any(source.document_id == document_id for source in item.sources):
            names.add(item.subject)
            names.add(item.object)
    return names


def _path_steps(source: str, steps: list[tuple[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current = source
    for predicate, nxt in steps:
        rows.append({"from": current, "predicate": predicate, "to": nxt})
        current = nxt
    return rows
