# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An unfinished extraction picks up where it stopped: read chunks are cached."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from auto_ontology.text_ontology.documents import load_bytes
from auto_ontology.text_ontology.llm_settings import resolve_llm_config
from auto_ontology.text_ontology.models import OntologyTriplet
from auto_ontology.text_ontology.pipeline import RESUME_FILE, ingest_document
from auto_ontology.text_ontology.sample import FakeLLM
from auto_ontology.text_ontology.store import ProjectStore

_FIRST = ["Alice", "Bruno", "Claire", "David", "Emma", "Fabien", "Gabriel", "Hugo"]
_LAST = ["Bernard", "Dupont", "Moreau", "Laurent", "Lefebvre", "Garnier", "Roussel"]


def _book() -> bytes:
    """Eight chapters, each naming other people: about eight chunks of 600."""
    chapters = []
    for i in range(8):
        a = f"{_FIRST[i]} {_LAST[i % 7]}"
        b = f"{_FIRST[(i + 3) % 8]} {_LAST[(i + 5) % 7]}"
        line = f"Chapitre {i}. {a} travaille avec {b} sur le projet « Atlas {i} ». "
        chapters.append(line * 6)
    return "\n\n".join(chapters).encode()


class Stops(FakeLLM):
    """Answers like the demo model until call *at*, which raises *error*."""

    def __init__(self, at: int, error: BaseException) -> None:
        self.calls = 0
        self.at = at
        self.error = error

    def invoke(self, messages: list[object]) -> Any:
        self.calls += 1
        if self.calls == self.at:
            raise self.error
        return super().invoke(messages)


def _run(store: ProjectStore, llm: object) -> list[str]:
    """Import the book into the current project; the chunk outcomes."""
    events: list[dict[str, object]] = []
    project = store.current() or store.create("Livre")
    config = dataclasses.replace(resolve_llm_config(store), chunk_chars=600)
    ingest_document(
        store,
        project,
        load_bytes("livre.txt", _book()),
        config=config,
        llm=llm,  # type: ignore[arg-type]
        model_label="local",
        force=False,
        cancel_event=None,
        on_event=events.append,
    )
    return [
        str(e["status"])
        for e in events
        if e["type"] == "chunk" and e["status"] != "started"
    ]


def _facts(store: ProjectStore) -> set[str]:
    ontology = store.current().ontology
    return {f"{t.subject}|{t.predicate}|{t.object}" for t in ontology.triplets}


def test_a_killed_extraction_resumes_from_the_cache(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "a")
    with pytest.raises(KeyboardInterrupt):  # Ctrl+C on the server, at chunk 3
        _run(store, Stops(3, KeyboardInterrupt()))
    assert store.current().documents[0].status == "running"

    resumed = _run(store, FakeLLM())

    assert resumed[:2] == ["cached", "cached"] and set(resumed[2:]) == {"ok"}
    clean = ProjectStore(tmp_path / "b")
    _run(clean, FakeLLM())
    assert _facts(store) == _facts(clean)  # nothing left over from the first try
    assert [d.status for d in store.current().documents] == ["ok"]
    assert not (store.project_dir(store.current().id) / RESUME_FILE).exists()


def test_an_incomplete_extraction_reuses_the_chunks_before_the_failure(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    first = _run(store, Stops(2, ValueError("le serveur ne répond pas")))
    assert first[:2] == ["ok", "failed"]
    assert store.current().documents[0].status == "incomplete"

    again = _run(store, FakeLLM())

    # The chunk that failed now answers, which changes the context of the
    # chunks after it: only those before it come from the cache.
    assert again[0] == "cached" and "failed" not in again
    assert store.current().documents[0].status == "ok"


def test_an_edit_after_the_interruption_is_kept(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        _run(store, Stops(3, KeyboardInterrupt()))
    project = store.current()
    project.ontology.triplets.append(
        OntologyTriplet(
            subject="Zoé Martin",
            subject_type="Personne",
            predicate="relit",
            object="Atlas 0",
            object_type="Document",
        )
    )
    store.save(project)

    resumed = _run(store, FakeLLM())

    assert "Zoé Martin|relit|Atlas 0" in _facts(store)
    assert "cached" not in resumed  # the context changed: read again, safely
