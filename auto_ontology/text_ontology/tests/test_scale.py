# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The studio view stays usable on a large project."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from auto_ontology.text_ontology.analysis import MATRIX_MAX_LABELS, annotate_graph
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.normalize import normalize_ontology
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.view import build_view


def _large(classes: int, triplets: int, seed: int = 0) -> TextOntology:
    rng = random.Random(seed)
    entities = [f"Entite {i}" for i in range(triplets // 2)]
    return TextOntology.model_validate(
        {
            "classes": [
                {
                    "name": f"Classe{i}",
                    "parent": f"Classe{rng.randrange(i)}"
                    if i and rng.random() < 0.8
                    else None,
                    "description": "",
                }
                for i in range(classes)
            ],
            "triplets": [
                {
                    "subject": rng.choice(entities),
                    "subject_type": f"Classe{rng.randrange(classes)}",
                    "predicate": f"rel_{rng.randrange(40)}",
                    "object": rng.choice(entities),
                    "object_type": f"Classe{rng.randrange(classes)}",
                }
                for _ in range(triplets)
            ],
        }
    )


def _view(tmp_path: Path, ontology: TextOntology) -> dict[str, object]:
    store = ProjectStore(tmp_path)
    project = store.create("Gros")
    project.ontology, _ = normalize_ontology(ontology)
    return build_view(
        project, path="x", can_undo=False, can_redo=False, llm={}, projects=[]
    )


def test_a_large_project_builds_quickly(tmp_path: Path) -> None:
    started = time.perf_counter()
    view = _view(tmp_path, _large(800, 5000))
    elapsed = time.perf_counter() - started

    # Was 9 s on this size, quadratic in the number of links. Generous bound,
    # so a slow CI runner does not flake: the old code was ten times over it.
    assert elapsed < 5
    assert len(json.dumps(view)) < 8_000_000


def test_the_drawn_graph_is_capped_and_hidden_nodes_stay_findable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONTOLOGY_GRAPH_MAX_NODES", "60")

    graph = _view(tmp_path, _large(40, 400))["graph"]

    assert isinstance(graph, dict)
    shown = {node["id"] for node in graph["nodes"]}
    assert len(shown) == 60
    assert graph["truncated"]["shown"] == 60
    assert graph["truncated"]["total"] == 60 + len(graph["hidden"])
    assert all(edge["from"] in shown and edge["to"] in shown for edge in graph["edges"])
    assert {"id", "label", "kind"} == set(graph["hidden"][0])


def test_a_small_graph_is_sent_whole(tmp_path: Path) -> None:
    graph = _view(tmp_path, _large(10, 30))["graph"]

    assert "truncated" not in graph and "hidden" not in graph


def test_the_class_matrix_keeps_the_most_connected_classes(tmp_path: Path) -> None:
    matrix = _view(tmp_path, _large(200, 2000))["analysis"]["matrix"]

    assert len(matrix["labels"]) == MATRIX_MAX_LABELS
    assert len(matrix["rows"][0]["cells"]) == MATRIX_MAX_LABELS
    assert matrix["truncated"]["shown"] == MATRIX_MAX_LABELS


def test_communities_follow_the_links() -> None:
    nodes = [{"id": name} for name in ("a1", "a2", "a3", "b1", "b2", "b3")]
    edges = [
        {"from": "a1", "to": "a2", "kind": "relation"},
        {"from": "a2", "to": "a3", "kind": "relation"},
        {"from": "a3", "to": "a1", "kind": "relation"},
        {"from": "b1", "to": "b2", "kind": "relation"},
        {"from": "b2", "to": "b3", "kind": "relation"},
        {"from": "b3", "to": "b1", "kind": "relation"},
        {"from": "a1", "to": "b1", "kind": "type"},  # type links do not vote
    ]

    annotate_graph(nodes, edges)

    community = {node["id"]: node["community"] for node in nodes}
    assert community["a1"] == community["a2"] == community["a3"]
    assert community["b1"] == community["b2"] == community["b3"]
    assert community["a1"] != community["b1"]
