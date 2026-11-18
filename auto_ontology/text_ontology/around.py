# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A parameterized walk around one concept.

Depth, direction and link types limit the walk. The result stops at a node
cap and says so, instead of handing the browser an unbounded graph.
"""

from __future__ import annotations

from collections import deque

from auto_ontology.text_ontology.studio_models import Project

_NODE_CAP = 500
_EDGE_CAP = 1500


def search_around(
    project: Project,
    start: str,
    *,
    link_types: list[str] | None = None,
    direction: str = "both",
    depth: int = 1,
    target_type: str = "",
    cap: int = _NODE_CAP,
) -> dict[str, object]:
    """Nodes and edges reachable from *start* under the given limits."""
    depth = min(3, max(1, depth))
    allowed = set(link_types or [])
    graph: dict[str, list[tuple[str, str, str]]] = {}
    types: dict[str, str] = {}
    for triplet in project.ontology.triplets:
        types.setdefault(triplet.subject, triplet.subject_type)
        types.setdefault(triplet.object, triplet.object_type)
        if allowed and triplet.predicate not in allowed:
            continue
        if direction in {"out", "both"}:
            graph.setdefault(triplet.subject, []).append(
                (triplet.predicate, triplet.object, "out")
            )
        if direction in {"in", "both"}:
            graph.setdefault(triplet.object, []).append(
                (triplet.predicate, triplet.subject, "in")
            )
    kept: set[str] = set()
    edges: list[dict[str, str]] = []
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    seen = {start}
    truncated = False
    while queue:
        current, hops = queue.popleft()
        if hops >= depth:
            continue
        for predicate, nxt, way in graph.get(current, []):
            if target_type and hops + 1 == depth and types.get(nxt) != target_type:
                continue
            if len(kept) >= cap or len(edges) >= _EDGE_CAP:
                truncated = True
                break
            edges.append(
                {
                    "from": current if way == "out" else nxt,
                    "to": nxt if way == "out" else current,
                    "predicate": predicate,
                }
            )
            kept.add(current)
            kept.add(nxt)
            if nxt not in seen and hops + 1 < depth:
                seen.add(nxt)
                queue.append((nxt, hops + 1))
        if truncated:
            break
    kept.add(start)
    return {
        "start": start,
        "nodes": sorted(kept),
        "edges": edges[:_EDGE_CAP],
        "truncated": truncated,
        "cap": cap,
        "depth": depth,
    }
