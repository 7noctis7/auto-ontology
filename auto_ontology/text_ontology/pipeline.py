# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turn one loaded document into an updated project.

The same function serves the CLI, the HTTP routes and the tests. It does
not know about FastAPI. A second drop of the same bytes, with the same
prompt, model and chunk size, is a no-op: the facts are not duplicated.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from auto_ontology.text_ontology.cache import FileChunkCache
from auto_ontology.text_ontology.documents import LoadedDocument
from auto_ontology.text_ontology.extractor import (
    ChunkEvent,
    extract_text_ontology,
    prompt_version,
)
from auto_ontology.text_ontology.llm_settings import LlmConfig
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.mutations import absorb_provenance
from auto_ontology.text_ontology.normalize import normalize_ontology
from auto_ontology.text_ontology.provenance import RawChunk, resolve_provenance
from auto_ontology.text_ontology.sample import (
    SAMPLE_MODEL,
    SAMPLE_TEXT,
    sample_ontology,
)
from auto_ontology.text_ontology.store import ProjectStore, now_iso
from auto_ontology.text_ontology.studio_models import DocumentRecord, Project


class IngestError(Exception):
    """A refusal the page can show. ``code`` is stable, ``message`` is French."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def fingerprint(content_hash: str, prompt: str, model: str, chunk_chars: int) -> str:
    """Identity of one extraction: same bytes, prompt, model and chunk size."""
    raw = f"{content_hash}|{prompt}|{model}|{chunk_chars}"
    return hashlib.sha256(raw.encode()).hexdigest()


def ingest_document(
    store: ProjectStore,
    project: Project,
    loaded: LoadedDocument,
    *,
    config: LlmConfig,
    llm: BaseChatModel | None,
    model_label: str,
    force: bool,
    cancel_event: threading.Event | None,
    on_event: Callable[[dict[str, object]], None],
) -> Project:
    """Extract *loaded* into *project* and save after each chunk."""
    if not loaded.text.strip():
        raise IngestError(
            "empty_document",
            "Ce fichier ne contient pas de texte exploitable.",
        )
    prompt = prompt_version()
    stamp = fingerprint(loaded.sha256, prompt, model_label, config.chunk_chars)
    previous = next(
        (document for document in project.documents if document.fingerprint == stamp),
        None,
    )
    if previous is not None and not force:
        on_event(
            {
                "type": "duplicate",
                "filename": loaded.filename,
                "message": (
                    f"{loaded.filename} est déjà dans le projet "
                    "(même texte, même modèle). Rien n'a été dupliqué."
                ),
            }
        )
        return project

    store.save(project, snapshot=True)
    if not project.documents and project.name in {
        "Brouillon",
        "Nouveau projet",
        "New project",
    }:
        project.name = Path(loaded.filename).name or project.name
    if previous is not None:
        project.documents = [
            document for document in project.documents if document.id != previous.id
        ]
        _drop_sources(project, previous.id)

    document = DocumentRecord(
        id=uuid.uuid4().hex[:12],
        filename=loaded.filename,
        media_type=loaded.media_type,
        sha256=loaded.sha256,
        char_count=len(loaded.text),
        added_at=now_iso(),
        status="running",
        noise_ratio=loaded.noise_ratio,
        warnings=list(loaded.warnings),
        prompt_version=prompt,
        model=model_label,
        fingerprint=stamp,
    )
    project.documents.append(document)
    store.remember_upload(project.id, document.id, loaded.filename, loaded.original)
    store.save(project, snapshot=False)
    on_event(
        {
            "type": "read",
            "filename": loaded.filename,
            "chars": len(loaded.text),
            "warnings": list(loaded.warnings),
            "document_id": document.id,
        }
    )

    base = project.ontology.model_copy(deep=True)
    # The document was appended onto the project whose ontology is base.
    # Preview merges replace project.ontology but must keep the same base.
    known_classes = [cls.name for cls in base.classes]
    known_predicates = list(dict.fromkeys(item.predicate for item in base.triplets))
    raw_chunks: list[RawChunk] = []
    cached_indexes: list[int] = []
    durations: list[float] = []
    chunk_started: dict[int, float] = {}
    started = time.monotonic()

    def on_chunk(event: ChunkEvent) -> None:
        now = time.monotonic()
        if event.status == "started":
            chunk_started[event.index] = now
        elif event.index in chunk_started:
            durations.append(now - chunk_started[event.index])
        eta = None
        if durations and event.status != "started":
            average = sum(durations) / len(durations)
            eta = round(average * max(0, event.total - event.index))
        if event.status in {"ok", "cached"} and event.ontology is not None:
            if event.status == "cached":
                cached_indexes.append(event.index)
            raw_chunks.append(
                RawChunk(index=event.index, text=event.text, ontology=event.ontology)
            )
            preview = _union(base, [chunk.ontology for chunk in raw_chunks])
            project.ontology, _warnings = normalize_ontology(preview, known_classes)
            store.save(project, snapshot=False)
        on_event(
            {
                "type": "chunk",
                "index": event.index,
                "total": event.total,
                "status": event.status,
                "eta_s": eta,
                "classes": len(event.ontology.classes) if event.ontology else 0,
                "triplets": len(event.ontology.triplets) if event.ontology else 0,
                "document_id": document.id,
            }
        )

    cache = FileChunkCache(store.cache_dir(project.id))
    try:
        result = extract_text_ontology(
            loaded.text,
            known_classes=known_classes,
            known_predicates=known_predicates,
            max_chunk_chars=config.chunk_chars,
            base=base,
            max_tokens=config.max_tokens,
            skip_failed_chunks=True,
            llm=llm,
            cache=cache,
            on_chunk=on_chunk,
            cancel_event=cancel_event,
            model_name=model_label,
        )
    except Exception:
        document.status = "failed"
        document.duration_s = round(time.monotonic() - started, 2)
        store.save(project, snapshot=False)
        raise

    project.ontology = result.ontology
    triplets, attributes, classes = resolve_provenance(
        result.ontology,
        raw_chunks,
        document_id=document.id,
        filename=loaded.filename,
    )
    absorb_provenance(project, triplets, attributes, classes)
    document.chunks_total = result.chunks
    document.chunks_failed = list(result.failed_chunks)
    document.chunks_cached = cached_indexes
    document.duration_s = round(time.monotonic() - started, 2)
    document.warnings = [*document.warnings, *result.warnings]
    if result.cancelled:
        document.status = "cancelled"
    elif result.failed_chunks:
        document.status = "incomplete"
    else:
        document.status = "ok"
    store.save(project, snapshot=False)
    on_event(
        {
            "type": "done",
            "document_id": document.id,
            "filename": loaded.filename,
            "status": document.status,
            "chunks": result.chunks,
            "failed": list(result.failed_chunks),
            "cached": list(cached_indexes),
        }
    )
    return project


def load_sample(store: ProjectStore, project: Project) -> tuple[Project, str]:
    """Merge the bundled example into *project*. No model is called."""
    loaded = _sample_loaded()
    stamp = fingerprint(loaded.sha256, "sample", SAMPLE_MODEL, 0)
    if any(document.fingerprint == stamp for document in project.documents):
        return project, "already"
    store.save(project, snapshot=True)
    if (
        project.name in {"Brouillon", "Nouveau projet", "New project"}
        and not project.documents
    ):
        project.name = "Exemple"
    document = DocumentRecord(
        id=uuid.uuid4().hex[:12],
        filename="exemple.txt",
        media_type="text/plain",
        sha256=loaded.sha256,
        char_count=len(SAMPLE_TEXT),
        added_at=now_iso(),
        chunks_total=1,
        status="ok",
        prompt_version="sample",
        model=SAMPLE_MODEL,
        fingerprint=stamp,
        warnings=["Exemple local : aucun modèle n'a été appelé."],
    )
    merged, _warnings = normalize_ontology(
        _union(project.ontology, [sample_ontology()])
    )
    project.ontology = merged
    raw = RawChunk(index=1, text=SAMPLE_TEXT, ontology=sample_ontology())
    triplets, attributes, classes = resolve_provenance(
        project.ontology,
        [raw],
        document_id=document.id,
        filename=document.filename,
    )
    absorb_provenance(project, triplets, attributes, classes)
    project.documents.append(document)
    store.remember_upload(project.id, document.id, document.filename, loaded.original)
    store.save(project, snapshot=False)
    return project, "loaded"


def _sample_loaded() -> LoadedDocument:
    from auto_ontology.text_ontology.documents import load_text

    return load_text("exemple.txt", SAMPLE_TEXT)


def _union(base: TextOntology, parts: list[TextOntology]) -> TextOntology:
    union = base.model_copy(deep=True)
    for part in parts:
        union.classes.extend(part.classes)
        union.triplets.extend(part.triplets)
        union.attributes.extend(part.attributes)
    return union


def _drop_sources(project: Project, document_id: str) -> None:
    for bucket in (project.triplets, project.attributes, project.classes):
        for item in bucket:
            item.sources = [
                source for source in item.sources if source.document_id != document_id
            ]
    project.triplets = [item for item in project.triplets if item.sources]
    project.attributes = [item for item in project.attributes if item.sources]
    project.classes = [item for item in project.classes if item.sources]
