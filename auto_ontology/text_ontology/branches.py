# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Project branches as JSON copies next to ``project.json``.

``main`` is written when the active branch is main. A side branch is a
second file. Discarding it reloads main and leaves main untouched.
"""

from __future__ import annotations

import json
import re

from auto_ontology.text_ontology.normalize import normalize_ontology
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.studio_models import Project

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


def active_branch(store: ProjectStore, project_id: str) -> str:
    """The branch the working ``project.json`` currently is."""
    pointer = store.project_dir(project_id) / "branch.json"
    if not pointer.is_file():
        return "main"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "main"
    return str(data.get("active") or "main")


def list_branches(store: ProjectStore, project_id: str) -> list[str]:
    """Branch names, ``main`` first."""
    folder = store.project_dir(project_id) / "branches"
    names = {"main"}
    if folder.is_dir():
        names.update(path.stem for path in folder.glob("*.json"))
    return ["main", *sorted(name for name in names if name != "main")]


def create_branch(store: ProjectStore, project: Project, name: str) -> Project:
    """Copy the current project into *name* and switch to it. Main stays as it is."""
    _check(name)
    if name == "main":
        raise ValueError("main existe déjà.")
    _write_named(store, project, "main")
    _write_named(store, project, name)
    _point(store, project.id, name)
    return project


def checkout(store: ProjectStore, project_id: str, name: str) -> Project:
    """Save the current branch, then load *name* into ``project.json``."""
    current_name = active_branch(store, project_id)
    current = store.load(project_id)
    _write_named(store, current, current_name)
    loaded = _read_named(store, project_id, name)
    _point(store, project_id, name)
    store.save(loaded, snapshot=False)
    return loaded


def discard_branch(store: ProjectStore, project_id: str) -> Project:
    """Drop the active side branch and restore main."""
    name = active_branch(store, project_id)
    if name == "main":
        raise ValueError("La branche main ne se jette pas.")
    path = store.project_dir(project_id) / "branches" / f"{name}.json"
    if path.is_file():
        path.unlink()
    _point(store, project_id, "main")
    main = _read_named(store, project_id, "main")
    store.save(main, snapshot=False)
    return main


def merge_branch(store: ProjectStore, project_id: str) -> Project:
    """Union the active branch into main, then stay on main."""
    name = active_branch(store, project_id)
    if name == "main":
        return store.load(project_id)
    branch = store.load(project_id)
    main = _read_named(store, project_id, "main")
    merged = _union(main, branch)
    _point(store, project_id, "main")
    store.save(merged, snapshot=True)
    return merged


def diff_projects(left: Project, right: Project) -> dict[str, list[str]]:
    """Names and facts present on only one side."""
    left_facts = _facts(left)
    right_facts = _facts(right)
    return {
        "only_left": sorted(left_facts - right_facts),
        "only_right": sorted(right_facts - left_facts),
    }


def _union(base: Project, extra: Project) -> Project:
    merged = base.model_copy(deep=True)
    ontology, _warnings = normalize_ontology(_join(merged.ontology, extra.ontology))
    merged.ontology = ontology
    known = {document.id for document in merged.documents}
    for document in extra.documents:
        if document.id not in known:
            merged.documents.append(document)
    for entry in extra.action_log:
        if entry.id not in {item.id for item in merged.action_log}:
            merged.action_log.append(entry)
    return merged


def _join(left: object, right: object) -> object:
    from auto_ontology.text_ontology.models import TextOntology

    union = (
        left.model_copy(deep=True) if isinstance(left, TextOntology) else TextOntology()
    )
    other = right if isinstance(right, TextOntology) else TextOntology()
    union.classes.extend(other.classes)
    union.triplets.extend(other.triplets)
    union.attributes.extend(other.attributes)
    return union


def _facts(project: Project) -> set[str]:
    facts = {cls.name for cls in project.ontology.classes}
    facts.update(
        f"{item.subject}|{item.predicate}|{item.object}"
        for item in project.ontology.triplets
    )
    return facts


def _check(name: str) -> None:
    if not _NAME.match(name):
        raise ValueError("Nom de branche invalide.")


def _write_named(store: ProjectStore, project: Project, name: str) -> None:
    _check(name) if name != "main" else None
    folder = store.project_dir(project.id) / "branches"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(
        project.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def read_branch(store: ProjectStore, project_id: str, name: str) -> Project:
    """The saved copy of *name*, or the working file when main was never snapshotted."""
    return _read_named(store, project_id, name)


def _read_named(store: ProjectStore, project_id: str, name: str) -> Project:
    if not _NAME.match(name):
        raise FileNotFoundError(name)
    path = store.project_dir(project_id) / "branches" / f"{name}.json"
    if not path.is_file():
        if name == "main":
            return store.load(project_id)
        raise FileNotFoundError(name)
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def _point(store: ProjectStore, project_id: str, name: str) -> None:
    path = store.project_dir(project_id) / "branch.json"
    path.write_text(json.dumps({"active": name}) + "\n", encoding="utf-8")
