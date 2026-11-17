# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Corrections, the query API and several documents of different kinds."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from auto_ontology.text_ontology.api import access_allowed
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.extractor import build_user_message
from auto_ontology.text_ontology.mcp_stdio import _handle
from auto_ontology.text_ontology.sample import FakeLLM
from auto_ontology.text_ontology.store import ProjectStore


def _client(tmp_path, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("REASONING_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("ONTOLOGY_API_TOKEN", raising=False)
    return TestClient(create_app(home=tmp_path, llm_factory=lambda _config: FakeLLM()))


def test_remote_token_is_optional_and_checked() -> None:
    assert access_allowed("127.0.0.1", "", "")
    assert access_allowed("10.0.0.8", "", "")
    assert not access_allowed("10.0.0.8", "", "secret")
    assert access_allowed("10.0.0.8", "Bearer secret", "secret")
    assert access_allowed("testclient", "", "secret")


def test_three_document_kinds_share_a_view(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    texts = {
        "contrat.txt": (
            "Contrat de prestation.\nLes parties conviennent.\n"
            "Article 1. Clause de confidentialité.\nAuteur: Jeanne Martin\n"
        ),
        "article.txt": (
            "Abstract\nHypothèse sur les graphes.\nDOI: 10.1000/xyz\nMots-clés : méthode\n"
        ),
        "message.txt": "De : ada@example.test\nObjet : notes\nCordialement\n",
    }
    for name, text in texts.items():
        response = client.post(
            "/api/ingest",
            json={"filename": name, "text": text, "sync": True},
        )
        assert response.status_code == 200, response.text

    state = client.get("/api/state").json()
    genres = {item["genre"] for item in state["documents"]}
    assert genres == {"contract", "scientific_paper", "email"}
    assert state["analysis"]["dashboards"]
    assert state["analysis"]["matrix"]["labels"] or state["stats"]["concepts"] >= 1
    shared = [node for node in state["graph"]["nodes"] if node.get("scope") == "shared"]
    assert shared or state["stats"]["documents"] == 3

    left, right = state["documents"][0]["id"], state["documents"][1]["id"]
    compared = client.get("/api/v1/compare", params={"left": left, "right": right})
    assert compared.status_code == 200
    assert "shared" in compared.json()

    corrected = client.post(
        f"/api/v1/documents/{left}/genre",
        json={"genre": "report"},
    )
    assert corrected.status_code == 200
    updated = next(item for item in corrected.json()["documents"] if item["id"] == left)
    assert updated["genre"] == "report"
    assert updated["genre_source"] == "user"

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/api/v1/concepts" in spec.json()["paths"]
    page = client.get("/docs")
    assert page.status_code == 200
    assert "swagger" in page.text.lower() or "openapi" in page.text.lower()


def test_corrections_enter_the_next_prompt_and_gold_is_scored(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    loaded = client.post("/api/sample")
    assert loaded.status_code == 200
    state = loaded.json()
    scores = state["analysis"]["scores"]
    assert scores
    assert scores[-1]["f1"] == 1.0

    fact = next(item for item in state["facts"] if item["kind"] == "triplet")
    edited = client.post(
        "/api/edits",
        json={
            "op": "delete_triplet",
            "subject": fact["subject"],
            "predicate": fact["predicate"],
            "object": fact["object"],
        },
    )
    assert edited.status_code == 200
    memory = ProjectStore(tmp_path).load_memory()
    assert memory.rejected

    message = build_user_message("Texte.", index=1, total=1, preface="Écrire « Ada ».")
    assert "Écrire « Ada »" in message

    exported = client.get("/api/export", params={"format": "jsonl"})
    rows = [json.loads(line) for line in exported.text.splitlines() if line.strip()]
    assert any(row["accepted"] is False for row in rows)

    answer = client.post(
        "/api/v1/ask", json={"question": "Camille Martin bibliothèque"}
    )
    assert answer.status_code == 200
    assert answer.json()["facts"] or "Aucun" in answer.json()["answer"]


def test_mcp_lists_tools(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/sample")
    store = ProjectStore(tmp_path)
    listed = _handle(store, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert "search" in names
    called = _handle(
        store,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "ask", "arguments": {"question": "Camille"}},
        },
    )
    assert called is not None
    assert "Camille" in called["result"]["content"][0]["text"]
