# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API route for extracting an ontology from free text."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auto_ontology.server.responses import TextOntologyExtractResponse
from auto_ontology.text_ontology.extractor import (
    TextOntologyExtractionError,
    extract_text_ontology,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# One request is at most ~17 sequential LLM calls at the default chunk size.
# Longer documents belong to a batch job, not to a request a proxy will time out.
MAX_TEXT_CHARS = 200_000
_MAX_KNOWN_NAMES = 1_000


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


@router.post("/text-ontology/extract", response_model=TextOntologyExtractResponse)
def extract_ontology_from_text(body: TextOntologyExtractRequest) -> dict:
    """Extract a formal ontology from free text.

    ``data`` holds ``classes`` (PascalCase, singular, with their parent),
    ``triplets`` (subject, predicate in snake_case, object, each typed by a
    class) and ``attributes`` (literal values). Only facts stated in the text
    are extracted. ``warnings`` lists what normalization repaired, such as a
    plural class merged into its singular. Nothing is written to the store.

    Returns 422 for blank text, 502 when the LLM gives no valid answer, and
    503 when no LLM is configured.
    """
    try:
        result = extract_text_ontology(
            body.text,
            known_classes=body.known_classes,
            known_predicates=body.known_predicates,
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
