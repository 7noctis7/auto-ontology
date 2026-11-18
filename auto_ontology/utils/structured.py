# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The base of LLM structured-output schemas, without the LLM client stack.

Kept apart from :mod:`auto_ontology.utils.llm_invoke` (which re-exports it)
so a data model can inherit from it without importing LangChain.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class StrictLLMOutputModel(BaseModel):
    """Base for LLM structured-output schemas.

    Forbids genuine hallucinated fields (``extra="forbid"``) but first strips any
    key starting with ``$`` — some models leak tool-calling metadata (e.g. a stray
    ``$FUNCTION_NAME`` field echoing the tool name) into the arguments payload,
    which would otherwise fail validation and burn all retry attempts even though
    the real data is fine. Opt a schema into this by inheriting from it instead of
    ``BaseModel``.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _strip_provider_artifact_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not k.startswith("$")}
        return data
