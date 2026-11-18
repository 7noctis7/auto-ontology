# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local similarity over names, descriptions and citations.

The vectors are hashed character trigrams. They need no model and no
network. A high score is a merge *candidate*. Nothing is merged by itself.
"""

from __future__ import annotations

import hashlib
import math
import re

from auto_ontology.text_ontology.studio_models import Project

_DIM = 32
_TOKEN = re.compile(r"[0-9A-Za-zÀ-ÿ]{2,}")


def vector(text: str) -> list[float]:
    """A unit vector. The same text always yields the same coordinates."""
    raw = [0.0] * _DIM
    folded = text.casefold()
    pieces = _TOKEN.findall(folded) or [folded]
    for piece in pieces:
        padded = f" {piece} "
        for index in range(len(padded) - 2):
            gram = padded[index : index + 3]
            digest = hashlib.sha256(gram.encode()).digest()
            raw[digest[0] % _DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in raw)) or 1.0
    return [value / norm for value in raw]


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine of two equal-length vectors."""
    return round(sum(a * b for a, b in zip(left, right, strict=True)), 4)


def merge_candidates(project: Project, limit: int = 8) -> list[dict[str, object]]:
    """Pairs of individuals that look alike and share a type.

    A class is never proposed as the merge of an individual, and two
    different types are not paired. Nothing is merged by itself.
    """
    classes = {item.name for item in project.ontology.classes}
    entities: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for triplet in project.ontology.triplets:
        for name, type_name in (
            (triplet.subject, triplet.subject_type),
            (triplet.object, triplet.object_type),
        ):
            if name in seen or name in classes:
                continue
            seen.add(name)
            entities.append((name, type_name, _blob(project, name)))
    scored: list[dict[str, object]] = []
    for index, (left, left_type, left_text) in enumerate(entities):
        left_vector = vector(left_text)
        for right, right_type, right_text in entities[index + 1 :]:
            if left in classes or right in classes:
                continue
            if left == right_type or right == left_type:
                continue
            if left_type != right_type:
                continue
            score = cosine(left_vector, vector(right_text))
            if score < 0.72:
                continue
            scored.append(
                {
                    "a": left,
                    "b": right,
                    "type": left_type or right_type,
                    "score": score,
                    "auto": False,
                }
            )
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    return scored[:limit]


def semantic_search(
    project: Project, query: str, limit: int = 8
) -> list[dict[str, object]]:
    """Concepts and citations closest to *query*."""
    query_vector = vector(query)
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for triplet in project.ontology.triplets:
        for name in (triplet.subject, triplet.object):
            if name in seen:
                continue
            seen.add(name)
            blob = _blob(project, name)
            rows.append(
                {
                    "name": name,
                    "score": cosine(query_vector, vector(blob)),
                    "quote": _quote(project, name),
                }
            )
    for cls in project.ontology.classes:
        rows.append(
            {
                "name": cls.name,
                "score": cosine(query_vector, vector(cls.name + " " + cls.description)),
                "quote": "",
            }
        )
    rows.sort(key=lambda item: float(item["score"]), reverse=True)
    return [row for row in rows if float(row["score"]) > 0][:limit]


def _blob(project: Project, name: str) -> str:
    parts = [name, _quote(project, name)]
    for cls in project.ontology.classes:
        if cls.name == name:
            parts.append(cls.description)
    return " ".join(parts)


def _quote(project: Project, name: str) -> str:
    for item in project.triplets:
        if name in {item.subject, item.object} and item.sources:
            return item.sources[0].quote
    return ""
