# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Turn one loaded document into an updated project.

The same function serves the CLI, the HTTP routes and the tests. It does
not know about FastAPI. A second drop of the same bytes, with the same
prompt, model and chunk size, is a no-op: the facts are not duplicated.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError

from auto_ontology.text_ontology.cache import FileChunkCache
from auto_ontology.text_ontology.documents import LoadedDocument
from auto_ontology.text_ontology.extractor import (
    ChunkEvent,
    extract_text_ontology,
    prompt_version,
)
from auto_ontology.text_ontology.learning import (
    align_names,
    drop_rejected,
    lessons_text,
    merged_memory,
    record_score,
)
from auto_ontology.text_ontology.llm_settings import LlmConfig
from auto_ontology.text_ontology.profile import profile_text, project_name_from
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.mutations import absorb_provenance
from auto_ontology.text_ontology.normalize import normalize_ontology
from auto_ontology.text_ontology.provenance import RawChunk, resolve_provenance
from auto_ontology.text_ontology.quality import apply_expectations
from auto_ontology.text_ontology.sample import (
    SAMPLE_MODEL,
    SAMPLE_TEXT,
    sample_ontology,
)
from auto_ontology.text_ontology.store import (
    ProjectStore,
    atomic_write_text,
    now_iso,
)
from auto_ontology.text_ontology.schema_layer import sync_schema
from auto_ontology.text_ontology.studio_models import (
    ChunkNote,
    DocumentRecord,
    Project,
    StepNote,
)


class IngestError(Exception):
    """A refusal the page can show. ``code`` is stable, ``message`` is French."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def fingerprint(content_hash: str, prompt: str, model: str, chunk_chars: int) -> str:
    """Identity of one extraction: same bytes, prompt, model and chunk size."""
    raw = f"{content_hash}|{prompt}|{model}|{chunk_chars}"
    return hashlib.sha256(raw.encode()).hexdigest()


# The project as an unfinished extraction found it. Resuming from it sends
# the model the same context as the first attempt, so every chunk already
# read comes from the cache; resuming from the project as the attempt left it
# would not, since its partial facts change the context of every chunk.
RESUME_FILE = "resume.json"


class _Resume:
    """Where an unfinished extraction of one document can pick up."""

    def __init__(self, path: Path, stamp: str, document_id: str, base: str) -> None:
        self.path = path
        self.head = {"fingerprint": stamp, "document_id": document_id}
        self.base = base

    def mark(self, project: Project) -> None:
        """Record the ontology as this run last saved it."""
        head = json.dumps({**self.head, "left": _ontology_hash(project)})
        atomic_write_text(self.path, head[:-1] + ', "ontology": ' + self.base + "}")

    def clear(self) -> None:
        with contextlib.suppress(OSError):
            self.path.unlink()


def _ontology_hash(project: Project) -> str:
    return hashlib.sha256(project.ontology.model_dump_json().encode()).hexdigest()


def _resume_base(
    store: ProjectStore, project: Project, stamp: str, previous: DocumentRecord
) -> TextOntology | None:
    """The ontology from before *previous*'s unfinished run, if still valid.

    Valid when the run was this very extraction (same bytes, prompt, model and
    chunk size) and the ontology is still exactly as that run left it: no
    edit, no other document since. Otherwise ``None``, and the extraction
    starts from the project as it is (correct, only slower).
    """
    path = store.project_dir(project.id) / RESUME_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if (
            saved.get("fingerprint") != stamp
            or saved.get("document_id") != previous.id
            or saved.get("left") != _ontology_hash(project)
        ):
            return None
        return TextOntology.model_validate(saved["ontology"])
    except (OSError, ValueError, KeyError, ValidationError):
        return None


def _complete(document: DocumentRecord) -> bool:
    """An extraction that finished: re-importing it would change nothing.

    One with chunks the model did not answer is run again instead. Started
    from the project as that run found it (see :func:`_resume_base`), it
    takes from the cache every chunk before the first one that failed; an
    interrupted run, every chunk it read.
    """
    return document.status == "ok" and not document.chunks_failed


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
    """Extract *loaded* into *project* and save after each chunk.

    The project is marked busy meanwhile, so another process (an MCP
    client's write) waits instead of being overwritten by the next save.
    """
    with store.busy(project.id):
        return _ingest_document(
            store,
            project,
            loaded,
            config=config,
            llm=llm,
            model_label=model_label,
            force=force,
            cancel_event=cancel_event,
            on_event=on_event,
        )


def _ingest_document(
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
    if previous is not None and not force and _complete(previous):
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
    if previous is None and loaded.text_sha256:
        # The same text under another name, pasted, or read by another model:
        # extracting it again would only duplicate its facts.
        same = next(
            (d for d in project.documents if d.text_sha256 == loaded.text_sha256),
            None,
        )
        if same is not None and not force and _complete(same):
            on_event(
                {
                    "type": "duplicate",
                    "filename": loaded.filename,
                    "message": (
                        f"Le contenu de {loaded.filename} est déjà dans le projet "
                        f"({same.filename}). Rien n'a été dupliqué ; forcez "
                        "l'import pour le réextraire avec ce modèle."
                    ),
                }
            )
            return project
        previous = same

    resumed = (
        _resume_base(store, project, stamp, previous)
        if previous is not None and not _complete(previous)
        else None
    )
    store.save(project, snapshot=True)
    naming = not project.documents and project.name in {
        "Brouillon",
        "Nouveau projet",
        "New project",
    }
    if previous is not None:
        project.documents = [
            document for document in project.documents if document.id != previous.id
        ]
        _drop_sources(project, previous.id)
        if resumed is not None:
            project.ontology = resumed

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
        text_sha256=loaded.text_sha256,
    )
    _apply_profile(document, loaded)
    if naming:
        project.name = project_name_from(document.title, document.filename)
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
    resume = _Resume(
        store.project_dir(project.id) / RESUME_FILE,
        stamp,
        document.id,
        base.model_dump_json(),
    )
    resume.mark(project)
    # The document was appended onto the project whose ontology is base.
    # Preview merges replace project.ontology but must keep the same base.
    known_classes = [cls.name for cls in base.classes]
    known_predicates = list(dict.fromkeys(item.predicate for item in base.triplets))
    from auto_ontology.text_ontology.playbooks import active

    playbook = active(project, store.home)
    if playbook is not None:
        # The playbook's vocabulary comes after the project's own names, so a
        # spelling the project already uses still wins.
        known_classes = list(dict.fromkeys([*known_classes, *playbook.classes]))
        known_predicates = list(
            dict.fromkeys([*known_predicates, *playbook.predicates])
        )
    raw_chunks: list[RawChunk] = []
    cached_indexes: list[int] = []
    durations: list[float] = []
    chunk_started: dict[int, float] = {}
    started = time.monotonic()

    def on_chunk(event: ChunkEvent) -> None:
        now = time.monotonic()
        if event.total and document.chunks_total != event.total:
            # Known from the first chunk on, so the brief can show progress
            # (a book read by a local model takes hours).
            document.chunks_total = event.total
            store.save(project, snapshot=False)
            resume.mark(project)
        if event.status == "started":
            chunk_started[event.index] = now
        elif event.index in chunk_started:
            durations.append(now - chunk_started[event.index])
        eta = None
        if durations and event.status != "started":
            average = sum(durations) / len(durations)
            eta = round(average * max(0, event.total - event.index))
        if event.status in {"ok", "cached", "failed"}:
            document.chunk_notes = [
                note for note in document.chunk_notes if note.index != event.index
            ]
            document.chunk_notes.append(
                ChunkNote(
                    index=event.index,
                    status=event.status,
                    preview=" ".join(event.text.split())[:240],
                    model=model_label,
                )
            )
        if event.status in {"ok", "cached"} and event.ontology is not None:
            if event.status == "cached":
                cached_indexes.append(event.index)
            raw_chunks.append(
                RawChunk(index=event.index, text=event.text, ontology=event.ontology)
            )
            preview = _union(base, [chunk.ontology for chunk in raw_chunks])
            project.ontology, _warnings = normalize_ontology(preview, known_classes)
            store.save(project, snapshot=False)
            resume.mark(project)
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
    memory = merged_memory(project, store)
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
            preface="\n\n".join(
                part
                for part in (
                    playbook.guidance() if playbook is not None else "",
                    lessons_text(memory),
                )
                if part
            ),
        )
    except Exception:
        document.status = "failed"
        document.duration_s = round(time.monotonic() - started, 2)
        store.save(project, snapshot=False)
        resume.mark(project)
        raise

    aligned = drop_rejected(align_names(result.ontology, memory, base), memory)
    project.ontology, _warnings = normalize_ontology(aligned, known_classes)
    triplets, attributes, classes = resolve_provenance(
        project.ontology,
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
    document.steps = [
        StepNote(name="ingest", status="ok", detail=loaded.filename),
        StepNote(name="clean", status="ok", detail=f"{len(loaded.text)} caractères"),
        StepNote(name="chunk", status="ok", detail=str(result.chunks)),
        StepNote(
            name="extract",
            status="incomplete" if result.failed_chunks else "ok",
            detail=model_label,
        ),
        StepNote(name="normalize", status="ok"),
        StepNote(name="merge", status=document.status),
    ]
    sync_schema(project)
    apply_expectations(project, document.id)
    point = record_score(project, loaded.text)
    home_memory = store.load_memory()
    home_memory.scores.append(point)
    del home_memory.scores[:-40]
    store.save_memory(home_memory)
    store.save(project, snapshot=False)
    if document.status == "ok":
        resume.clear()
    else:
        resume.mark(project)  # a new import fills in what is missing
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
    _apply_profile(document, loaded)
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
    record_score(project, loaded.text)
    store.remember_upload(project.id, document.id, document.filename, loaded.original)
    store.save(project, snapshot=False)
    return project, "loaded"


def _apply_profile(document: DocumentRecord, loaded: LoadedDocument) -> None:
    profile = profile_text(loaded.text, filename=loaded.filename, pages=loaded.pages)
    document.title = profile.title
    document.author = profile.author
    document.date = profile.date
    document.language = profile.language
    document.pages = profile.pages
    document.genre = profile.genre
    document.genre_confidence = profile.genre_confidence
    document.domain = profile.domain
    document.domain_confidence = profile.domain_confidence
    document.genre_source = "auto"


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
