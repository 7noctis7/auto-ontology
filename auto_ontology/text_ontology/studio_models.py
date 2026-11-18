# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The project file the studio saves on disk.

``schema_version`` is 1. New fields have defaults, so a file written by the
first studio still opens. A newer ``schema_version`` is refused rather than
guessed. The ontology itself stays the normalized extraction; provenance,
documents and renames sit beside it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from auto_ontology.text_ontology.models import TextOntology

SCHEMA_VERSION = 1


class SourceRef(BaseModel):
    """Where one fact was read."""

    document_id: str
    filename: str
    chunk_index: int
    quote: str


class TripletProv(BaseModel):
    subject: str
    predicate: str
    object: str
    sources: list[SourceRef] = Field(default_factory=list)


class AttributeProv(BaseModel):
    entity: str
    key: str
    value: str
    sources: list[SourceRef] = Field(default_factory=list)


class ClassProv(BaseModel):
    name: str
    sources: list[SourceRef] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    """One file or pasted passage that was added to the project."""

    id: str
    filename: str
    media_type: str = "text/plain"
    sha256: str = ""
    char_count: int = 0
    added_at: str
    chunks_total: int = 0
    chunks_failed: list[int] = Field(default_factory=list)
    chunks_cached: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_s: float = 0
    status: str = "ok"
    noise_ratio: float = 0
    prompt_version: str = ""
    model: str = ""
    fingerprint: str = ""
    title: str = ""
    author: str = ""
    date: str = ""
    language: str = ""
    pages: int = 0
    genre: str = "notes"
    genre_confidence: float = 0
    genre_source: str = "auto"
    domain: str = ""
    domain_confidence: float = 0
    steps: list["StepNote"] = Field(default_factory=list)
    expectations: list["StepNote"] = Field(default_factory=list)
    chunk_notes: list["ChunkNote"] = Field(default_factory=list)


class StepNote(BaseModel):
    """One pipeline step or one quality check."""

    name: str
    status: str = "ok"
    detail: str = ""


class ChunkNote(BaseModel):
    """A chunk the extractor actually saw, kept short for the lineage view."""

    index: int
    status: str = "ok"
    preview: str = ""
    model: str = ""


class PropertyDef(BaseModel):
    """A typed characteristic. ``shared`` reuses a canonical name when it matches."""

    id: str
    label: str
    base_type: str = "string"
    visibility: str = "normal"
    shared: str = ""


class ObjectTypeDef(BaseModel):
    """The schema of a class, distinct from the instances extracted from text."""

    id: str
    label: str
    description: str = ""
    group: str = "Concepts"
    status: str = "experimental"
    title_key: str = "nom"


class LinkTypeDef(BaseModel):
    """The schema of a predicate."""

    id: str
    label: str
    inverse: str = ""
    source_type: str = ""
    target_type: str = ""
    cardinality: str = "n-n"
    status: str = "experimental"


class SchemaCatalog(BaseModel):
    """Types, properties and links of one project. Instances stay on the ontology."""

    version: int = 1
    object_types: list[ObjectTypeDef] = Field(default_factory=list)
    properties: list[PropertyDef] = Field(default_factory=list)
    link_types: list[LinkTypeDef] = Field(default_factory=list)


class ActionEntry(BaseModel):
    """One applied correction. The log is append-only in the project file."""

    id: str
    at: str
    actor: str = "local"
    name: str
    params: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


class ObjectSetDef(BaseModel):
    """A named filter. ``query`` is the definition; ``pinned_ids`` is optional."""

    id: str
    name: str
    description: str = ""
    query: dict[str, str] = Field(default_factory=dict)
    pinned_ids: list[str] = Field(default_factory=list)


class NoteLink(BaseModel):
    """A local remark. It is not a sourced fact and stays out of RDF exports."""

    id: str
    source: str
    target: str
    label: str = "note"


class CompetencyQuestion(BaseModel):
    """A question the ontology is meant to answer. METHONTOLOGY / NeOn style."""

    id: str
    text: str


class VocabularyMapping(BaseModel):
    """An accepted link to a public vocabulary. Suggestions are not stored here."""

    source: str
    iri: str
    predicate: str = "owl:equivalentClass"
    accepted: bool = True


class Alias(BaseModel):
    """A spelling the person prefers. ``kind`` is entity, class or predicate."""

    kind: str
    source: str
    target: str


class RejectedFact(BaseModel):
    """A triplet the person removed. Later extractions are told to skip it."""

    subject: str
    predicate: str
    object: str
    passage: str = ""


class Example(BaseModel):
    """A short passage kept as a reminder in the next prompt."""

    passage: str
    note: str


class ScorePoint(BaseModel):
    """One reading of quality. Gold precision is set only for the example text."""

    at: str
    quality: float = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    note: str = ""


class Memory(BaseModel):
    """Corrections accumulated in one project, or in the home directory."""

    aliases: list[Alias] = Field(default_factory=list)
    rejected: list[RejectedFact] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    scores: list[ScorePoint] = Field(default_factory=list)


class Project(BaseModel):
    """One domain, stored as ``project.json``."""

    schema_version: int = SCHEMA_VERSION
    id: str
    name: str
    created_at: str
    updated_at: str
    ontology: TextOntology = Field(default_factory=TextOntology)
    documents: list[DocumentRecord] = Field(default_factory=list)
    triplets: list[TripletProv] = Field(default_factory=list)
    attributes: list[AttributeProv] = Field(default_factory=list)
    classes: list[ClassProv] = Field(default_factory=list)
    memory: Memory = Field(default_factory=Memory)
    pinned_dashboards: list[str] = Field(default_factory=list)
    catalog: SchemaCatalog = Field(default_factory=SchemaCatalog)
    action_log: list[ActionEntry] = Field(default_factory=list)
    object_sets: list[ObjectSetDef] = Field(default_factory=list)
    notes: list[NoteLink] = Field(default_factory=list)
    questions: list[CompetencyQuestion] = Field(default_factory=list)
    mappings: list[VocabularyMapping] = Field(default_factory=list)
    base_iri: str = ""


class StudioSettings(BaseModel):
    """Choices remembered between launches. The API key stays in this file."""

    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    timeout_s: int = 120
    max_tokens: int = 8192
    chunk_chars: int = 12_000
    last_project_id: str = ""
    watch_dir: str = ""


class Edit(BaseModel):
    """One correction typed in the side panel."""

    op: str
    old: str = ""
    new: str = ""
    source: str = ""
    target: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    entity: str = ""
    key: str = ""
    value: str = ""
    description: str = ""
    document_id: str = ""
