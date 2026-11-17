# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for extracting, merging and exporting ontologies from free text."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auto_ontology.server.responses import (
    TextOntologyExportResponse,
    TextOntologyExtractResponse,
    TextOntologyMergeResponse,
)
from auto_ontology.text_ontology.export import (
    DEFAULT_BASE_IRI,
    MEDIA_TYPES,
    ExportFormat,
    export_ontology,
)
from auto_ontology.text_ontology.extractor import (
    TextOntologyExtractionError,
    extract_text_ontology,
)
from auto_ontology.text_ontology.glossary import glossary_class_names
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.project import merge_ontologies

logger = logging.getLogger(__name__)

router = APIRouter()

# One request is at most ~17 sequential LLM calls at the default chunk size.
# Longer documents belong to a batch job, not to a request a proxy will time out.
MAX_TEXT_CHARS = 200_000
_MAX_KNOWN_NAMES = 1_000
_MAX_MERGED = 100


class TextOntologyExtractRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    known_classes: list[str] = Field(
        default_factory=list,
        max_length=_MAX_KNOWN_NAMES,
        description="Classes that already exist and must be reused, not duplicated.",
    )
    known_predicates: list[str] = Field(
        default_factory=list,
        max_length=_MAX_KNOWN_NAMES,
        description="Relations that already exist and must be reused.",
    )
    reuse_glossary: bool = Field(
        default=False,
        description="Also reuse the glossary's Term names as known classes.",
    )
    base: TextOntology | None = Field(
        default=None,
        description="An ontology to grow, such as a project's: the result merges it.",
    )


class TextOntologyMergeRequest(BaseModel):
    ontologies: list[TextOntology] = Field(..., min_length=1, max_length=_MAX_MERGED)
    known_classes: list[str] = Field(default_factory=list, max_length=_MAX_KNOWN_NAMES)


class TextOntologyExportRequest(BaseModel):
    ontology: TextOntology
    format: ExportFormat
    base_iri: str = Field(default=DEFAULT_BASE_IRI, min_length=1, max_length=500)
    title: str = Field(default="Ontologie", max_length=200)


@router.post("/text-ontology/extract", response_model=TextOntologyExtractResponse)
def extract_ontology_from_text(body: TextOntologyExtractRequest) -> dict:
    """Extract a formal ontology from free text.

    ``data`` holds ``classes`` (PascalCase, singular, with their parent),
    ``triplets`` (subject, predicate in snake_case, object, each typed by a
    class) and ``attributes`` (literal values). Only facts stated in the text
    are extracted. ``warnings`` lists what normalization repaired, such as a
    plural class merged into its singular. Nothing is written to the store.

    With ``base``, the text grows that ontology and ``data`` is the merge.
    With ``reuse_glossary``, the glossary's Terms are classes to reuse.

    Returns 422 for blank text, 502 when the LLM gives no valid answer, and
    503 when no LLM is configured.
    """
    known_classes = list(body.known_classes)
    if body.reuse_glossary:
        known_classes += glossary_class_names()
    try:
        result = extract_text_ontology(
            body.text,
            known_classes=known_classes,
            known_predicates=body.known_predicates,
            base=body.base,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TextOntologyExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EnvironmentError as exc:
        logger.error("Text ontology extraction has no LLM: %s", exc)
        raise HTTPException(status_code=503, detail="No LLM is configured.") from exc
    return {
        "data": result.ontology.model_dump(),
        "warnings": result.warnings,
        "chunks": result.chunks,
    }


@router.post("/text-ontology/merge", response_model=TextOntologyMergeResponse)
def merge_text_ontologies(body: TextOntologyMergeRequest) -> dict:
    """Merge several extracted ontologies into one.

    Duplicates are reconciled as in a single extraction: classes that differ
    only by case, accents or a plural ending become one, and so do entities
    spelled two ways. Earlier ontologies win ties, so pass a project's
    ontology first. No LLM is called.
    """
    ontology, warnings = merge_ontologies(body.ontologies, body.known_classes)
    return {"data": ontology.model_dump(), "warnings": warnings}


@router.post("/text-ontology/export", response_model=TextOntologyExportResponse)
def export_text_ontology(body: TextOntologyExportRequest) -> dict:
    """Render an ontology as Mermaid, RDF/OWL (Turtle), Neo4j Cypher or HTML.

    ``data`` is the rendered text and ``media_type`` its content type. The
    HTML page draws an interactive graph and loads its graph library from a
    CDN. Returns 422 for an unusable ``base_iri``.
    """
    try:
        rendered = export_ontology(
            body.ontology, body.format, base_iri=body.base_iri, title=body.title
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "data": rendered,
        "format": body.format.value,
        "media_type": MEDIA_TYPES[body.format],
    }
