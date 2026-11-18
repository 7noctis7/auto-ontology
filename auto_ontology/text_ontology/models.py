# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Schemas for an ontology extracted from free text.

The field names are the output contract of ``prompts/system_prompt.txt``
(``classes`` / ``triplets`` / ``attributes``), so the same models serve as the
LLM structured-output schema and as the normalized result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from auto_ontology.utils.llm_invoke import StrictLLMOutputModel

# Spellings of "no parent" that models write instead of a JSON null, the prompt's
# own placeholder ("ClasseParenteOuNull") included.
_NULL_PARENTS = frozenset({"", "null", "none", "nil", "n/a", "classeparenteounull"})


class OntologyClass(StrictLLMOutputModel):
    """A class (concept) of the ontology, with its direct parent."""

    name: str = Field(description="Class name in PascalCase, singular.")
    parent: str | None = Field(
        default=None,
        description="Name of the direct parent class (subClassOf), or null.",
    )
    description: str = Field(default="", description="Short definition.")

    @field_validator("parent", mode="before")
    @classmethod
    def _null_parent(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in _NULL_PARENTS:
            return None
        return value


class OntologyTriplet(StrictLLMOutputModel):
    """An atomic fact ``(subject) -[predicate]-> (object)``."""

    subject: str = Field(description="Source entity (individual or class).")
    subject_type: str = Field(description="Class of the subject.")
    predicate: str = Field(description="Relation name in snake_case, active verb.")
    object: str = Field(description="Target entity (individual or class).")
    object_type: str = Field(description="Class of the object.")


class OntologyAttribute(StrictLLMOutputModel):
    """A literal property of an entity (date, number, identifier...)."""

    entity: str = Field(description="Entity carrying the attribute.")
    key: str = Field(description="Attribute name in snake_case.")
    value: str = Field(description="Literal value, as text.")

    @field_validator("value", mode="before")
    @classmethod
    def _stringify_scalar(cls, value: Any) -> Any:
        # Models routinely answer numbers and booleans unquoted; the contract
        # is a literal, so keep it as text rather than burn a retry.
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return value


class TextOntology(StrictLLMOutputModel):
    """The full extraction result: classes, triplets and literal attributes."""

    classes: list[OntologyClass] = Field(default_factory=list)
    triplets: list[OntologyTriplet] = Field(default_factory=list)
    attributes: list[OntologyAttribute] = Field(default_factory=list)


class TextOntologyResult(BaseModel):
    """A normalized ontology plus what normalization had to repair."""

    model_config = ConfigDict(extra="forbid")

    ontology: TextOntology
    warnings: list[str] = Field(default_factory=list)
    chunks: int = Field(default=1, description="Number of LLM calls made.")
    failed_chunks: list[int] = Field(
        default_factory=list,
        description="Chunks skipped because the LLM gave no valid answer.",
    )
    cancelled: bool = Field(
        default=False,
        description="The run stopped before every chunk because it was cancelled.",
    )
