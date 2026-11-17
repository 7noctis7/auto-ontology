# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The local studio: one process, a fake model, real files."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.cache import FileChunkCache
from auto_ontology.text_ontology.extractor import extract_text_ontology
from auto_ontology.text_ontology.models import OntologyClass, TextOntology
from auto_ontology.text_ontology.sample import SAMPLE_TEXT, FakeLLM

_SECRET_ENV = (
    "ONTOLOGY_LLM_API_KEY",
    "ONTOLOGY_LLM_ENDPOINT",
    "ONTOLOGY_LLM_MODEL",
    "REASONING_API_KEY",
    "REASONING_ENDPOINT",
    "REASONING_MODEL",
    "DEFAULT_MODELS_API_KEY",
    "DEFAULT_MODELS_ENDPOINT",
    "DEFAULT_MODELS_MODEL",
    "NVIDIA_API_KEY",
    "BASE_URL",
    "MODEL_NAME",
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in _SECRET_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ONTOLOGY_HOME", str(tmp_path))
    return tmp_path


class _CountingFake(FakeLLM):
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages: list[object]) -> TextOntology:
        self.calls += 1
        return super().invoke(messages)


def _app(home, factory=None, fake=False):
    return TestClient(create_app(home=home, llm_factory=factory, fake=fake))


def _pdf(text: str) -> bytes:
    from auto_ontology.text_ontology.tests.test_documents import _pdf as build

    return build(text)


def _epub(text: str) -> bytes:
    from auto_ontology.text_ontology.tests.test_documents import _epub as build

    return build(text)


def test_page_is_local_and_explains_a_missing_key(home) -> None:
    client = _app(home)

    page = client.get("/")
    script = client.get("/assets/vendor/vis-network.min.js")
    state = client.get("/api/state")

    assert page.status_code == 200
    assert "Déposez un document" in page.text
    assert "unpkg.com" not in page.text
    assert script.status_code == 200
    assert "vis-network" in script.text[:400]
    assert state.json()["llm"]["configured"] is False
    assert "Aucune clé" in state.json()["llm"]["message"]
    refused = client.post("/api/ingest", json={"text": "Un texte.", "sync": True})
    assert refused.status_code == 409
    assert refused.json()["error"] == "llm_not_configured"


def test_sample_builds_a_graph_with_provenance(home) -> None:
    client = _app(home)

    state = client.post("/api/sample").json()

    labels = {node["label"] for node in state["graph"]["nodes"]}
    assert "Camille Martin" in labels
    assert "Bibliothèque municipale de Lyon" in labels
    assert state["stats"]["concepts"] >= 5
    assert state["stats"]["documents"] == 1
    assert state["stats"]["orphans"] >= 1
    quotes = [
        source["quote"]
        for fact in state["facts"]
        for source in fact["sources"]
        if "Camille" in fact["subject"] or "Camille" in fact["object"]
    ]
    assert quotes
    assert any(
        "Camille" in quote or "bibliothèque" in quote.casefold() for quote in quotes
    )


def test_txt_pdf_and_epub_each_produce_a_graph(home) -> None:
    shared = _CountingFake()

    def factory(_config: object) -> _CountingFake:
        return shared

    client = _app(home, factory=factory)
    text = SAMPLE_TEXT

    def ingest(filename: str, payload: bytes, mime: str) -> dict:
        opened = client.post("/api/projects", json={"name": filename})
        assert opened.status_code == 200
        response = client.post(
            "/api/ingest",
            data={"sync": "1"},
            files={"file": (filename, payload, mime)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stats"]["documents"] == 1
        assert body["graph"]["nodes"]
        assert "Camille Martin" in _labels(body)
        assert any(
            document["filename"] == filename and document["char_count"] > 40
            for document in body["documents"]
        )
        return body

    before = shared.calls
    ingest("notes.txt", text.encode(), "text/plain")
    assert shared.calls > before
    ingest("notes.pdf", _pdf(text), "application/pdf")
    ingest("notes.epub", _epub(text), "application/epub+zip")

    calls_after = shared.calls
    again = client.post(
        "/api/ingest",
        data={"sync": "1"},
        files={"file": ("notes.epub", _epub(text), "application/epub+zip")},
    )
    assert again.status_code == 200
    assert again.json()["stats"]["documents"] == 1
    assert shared.calls == calls_after


def test_rename_is_saved_and_undo_restores_it(home) -> None:
    client = _app(home)
    client.post("/api/sample")

    renamed = client.post(
        "/api/edits",
        json={"op": "rename_entity", "old": "Camille Martin", "new": "Camille M."},
    )
    assert renamed.status_code == 200, renamed.text
    assert "Camille M." in _labels(renamed.json())
    assert "Camille Martin" not in _labels(renamed.json())

    restored = client.post("/api/undo")
    assert "Camille Martin" in _labels(restored.json())
    redone = client.post("/api/redo")
    assert "Camille M." in _labels(redone.json())


def test_html_export_embeds_the_graph_library(home) -> None:
    client = _app(home)
    client.post("/api/sample")

    exported = client.get("/api/export?format=html")

    assert exported.status_code == 200
    assert "unpkg.com" not in exported.text
    assert "vis-network" in exported.text
    assert "Camille Martin" in exported.text
    csv_export = client.get("/api/export?format=csv")
    assert "Camille Martin" in csv_export.text
    assert client.get("/api/export?format=jsonld").status_code == 200


def test_chunk_cache_and_cancel(tmp_path) -> None:
    cache = FileChunkCache(tmp_path)
    llm = _CountingFake()
    text = "Camille Martin dirige la bibliothèque municipale de Lyon depuis 2016."

    extract_text_ontology(text, llm=llm, cache=cache, model_name="demo")
    first = llm.calls
    extract_text_ontology(text, llm=llm, cache=cache, model_name="demo")

    assert first >= 1
    assert llm.calls == first

    cancel = threading.Event()

    class _Once:
        model_name = "demo"

        def with_structured_output(self, schema: type, **_: object) -> _Once:
            return self

        def invoke(self, messages: list[object]) -> TextOntology:
            return TextOntology(
                classes=[OntologyClass(name="Chose", description="Une chose.")]
            )

    def stop(event: object) -> None:
        if getattr(event, "status", "") == "ok":
            cancel.set()

    paragraphs = "\n\n".join(
        f"Paragraphe {index}. " + ("mot " * 30) for index in range(6)
    )
    result = extract_text_ontology(
        paragraphs,
        llm=_Once(),
        max_chunk_chars=80,
        skip_failed_chunks=True,
        cancel_event=cancel,
        on_chunk=stop,
    )

    assert result.cancelled
    assert result.chunks > 1
    assert any(warning.startswith("CANCELLED") for warning in result.warnings)


def _labels(body: dict) -> set[str]:
    return {node["label"] for node in body["graph"]["nodes"]}
