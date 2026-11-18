# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Schema, actions, lineage, sets, branches and local similarity."""

from __future__ import annotations

from fastapi.testclient import TestClient

from auto_ontology.text_ontology.actions import commit_action, preview_action
from auto_ontology.text_ontology.api import write_allowed
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.around import search_around
from auto_ontology.text_ontology.branches import (
    active_branch,
    create_branch,
    diff_projects,
    discard_branch,
)
from auto_ontology.text_ontology.explore import compile_where, match_query
from auto_ontology.text_ontology.learning import lessons_text, merged_memory
from auto_ontology.text_ontology.lineage import lineage_for
from auto_ontology.text_ontology.quality import expectation_report, ocr_hint
from auto_ontology.text_ontology.sample import FakeLLM
from auto_ontology.text_ontology.schema_layer import infer_base_type, sync_schema
from auto_ontology.text_ontology.sdkgen import render_sdk
from auto_ontology.text_ontology.similar import cosine, merge_candidates, vector
from auto_ontology.text_ontology.store import ProjectStore
import json

from auto_ontology.text_ontology.studio_models import Project


def _client(tmp_path, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_API_TOKEN", raising=False)
    monkeypatch.delenv("ONTOLOGY_API_ALLOW_WRITE", raising=False)
    return TestClient(create_app(home=tmp_path, llm_factory=lambda _config: FakeLLM()))


def test_old_project_file_still_opens(tmp_path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Ancien")
    raw = project.model_dump()
    raw.pop("catalog")
    raw.pop("action_log")
    raw.pop("object_sets")
    raw.pop("notes")
    path = store.project_dir(project.id) / "project.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load(project.id)
    assert loaded.catalog.object_types == []
    assert loaded.name == "Ancien"


def test_schema_actions_lineage_and_reuse(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    state = client.post("/api/sample").json()
    names = {item["id"] for item in state["catalog"]["object_types"]}
    assert "Bibliotheque" in names or "Personne" in names
    assert any(
        item["id"] == "est_dirigee_par" for item in state["catalog"]["link_types"]
    )

    project = ProjectStore(tmp_path).load(state["project"]["id"])
    preview = preview_action(
        project,
        "merge",
        {"source": "Camille Martin", "target": "Ada Lovelace"},
    )
    assert preview["removed"]
    assert any(
        "Camille Martin" in {item.subject, item.object}
        for item in project.ontology.triplets
    )

    applied = client.post(
        "/api/v1/actions/merge/apply",
        json={"source": "Camille Martin", "target": "Ada Lovelace"},
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["action_log"][-1]["name"] == "merge"
    assert not any(
        fact["subject"] == "Camille Martin"
        for fact in body["facts"]
        if fact["kind"] == "triplet"
    )
    store = ProjectStore(tmp_path)
    remembered = merged_memory(store.load(body["project"]["id"]), store)
    assert "Camille Martin" in lessons_text(remembered)

    chain = lineage_for(store.load(body["project"]["id"]), "Ada Lovelace")
    assert chain["steps"]
    assert chain["steps"][0]["quote"]
    assert chain["actions"]

    around = search_around(store.load(body["project"]["id"]), "Ada Lovelace", depth=2)
    assert "Ada Lovelace" in around["nodes"]
    assert around["cap"] == 500


def test_filter_sets_branches_and_similarity(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    state = client.post("/api/sample").json()
    assert match_query(
        {
            "label": "Lyon",
            "family": "Ville",
            "documents": ["a"],
            "status": "experimental",
            "scope": "specific",
        },
        {"type": "Ville"},
    )
    assert compile_where({"eq": {"field": "type", "value": "Ville"}})["type"] == "Ville"

    saved = client.post(
        "/api/v1/object-sets",
        json={"name": "villes", "query": {"q": "Lyon", "type": "Ville"}},
    )
    assert saved.status_code == 200
    found = client.get("/api/v1/explore", params={"q": "Lyon"})
    assert found.json()["total"] >= 1

    store = ProjectStore(tmp_path)
    project = store.load(state["project"]["id"])
    create_branch(store, project, "essai")
    commit_action(
        store,
        store.load(project.id),
        "rename",
        {"kind": "entity", "old": "Lyon", "new": "Lyon centre"},
        actor="local",
    )
    assert active_branch(store, project.id) == "essai"
    main = store.project_dir(project.id) / "branches" / "main.json"
    main_project = Project.model_validate_json(main.read_text(encoding="utf-8"))
    side = store.load(project.id)
    diff = diff_projects(main_project, side)
    assert any("Lyon centre" in line for line in diff["only_right"])
    restored = discard_branch(store, project.id)
    assert active_branch(store, project.id) == "main"
    assert any(
        item.subject == "Lyon" or item.object == "Lyon"
        for item in restored.ontology.triplets
    )

    left = vector("Camille Martin bibliothécaire")
    right = vector("Camille Martin, bibliothécaire")
    assert cosine(left, right) > 0.8
    assert merge_candidates(restored) == [] or all(
        item["auto"] is False for item in merge_candidates(restored)
    )
    assert (
        "Tesseract" in ocr_hint()
        or "scan" in ocr_hint().casefold()
        or "binaire" in ocr_hint()
    )
    report = expectation_report(restored)
    assert {item.name for item in report} == {"chunks", "citations", "hierarchie"}
    assert infer_base_type("2016") == "date"
    sync_schema(restored)
    source = render_sdk(restored)
    assert "def search" in source
    assert "class Client" in source

    remote = client.get("/api/v1/schema")
    assert remote.status_code == 200
    page = client.get("/api/tester")
    assert page.status_code == 200
    assert "Personne" in page.text
    assert write_allowed("127.0.0.1")
    assert not write_allowed("10.1.1.1")
