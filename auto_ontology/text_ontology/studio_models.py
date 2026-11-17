# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The project file the studio saves on disk.

``schema_version`` is 1. A newer file is refused rather than guessed. The
ontology itself stays the normalized extraction; provenance, documents and
renames sit beside it, so the LLM schema does not have to carry them.
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


class StudioSettings(BaseModel):
    """Choices remembered between launches. The API key stays in this file."""

    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    timeout_s: int = 120
    max_tokens: int = 8192
    chunk_chars: int = 12_000
    last_project_id: str = ""


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
