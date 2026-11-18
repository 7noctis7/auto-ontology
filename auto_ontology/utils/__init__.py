# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared utilities used across server, ingestion, and dev tools.

The names below are loaded on first use (PEP 562). Importing them eagerly
made every ``auto_ontology.utils.<module>`` import pay for the embedding and
retriever stack, about a second, even for a light module or a command that
never touches them. ``from auto_ontology.utils import get_embed_params``
works as before.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

_EXPORTS = {
    "sample_values_edit_error": "auto_ontology.utils.column_types",
    "sample_values_editable": "auto_ontology.utils.column_types",
    "get_embed_params": "auto_ontology.utils.embedding",
    "get_data_objects_retriever": "auto_ontology.utils.retriever",
    "get_semantic_objects_retriever": "auto_ontology.utils.retriever",
    "dump_sample_values": "auto_ontology.utils.sample_values",
    "parse_sample_values": "auto_ontology.utils.sample_values",
    "render_sample_value": "auto_ontology.utils.sample_values",
    "stringify_sample_values": "auto_ontology.utils.sample_values",
}

__all__ = [
    "get_embed_params",
    "get_data_objects_retriever",
    "get_semantic_objects_retriever",
    "sample_values_edit_error",
    "sample_values_editable",
    "dump_sample_values",
    "parse_sample_values",
    "render_sample_value",
    "stringify_sample_values",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # later lookups skip this function
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_EXPORTS])


if TYPE_CHECKING:  # static analysis sees the real names
    from auto_ontology.utils.column_types import (
        sample_values_edit_error,
        sample_values_editable,
    )
    from auto_ontology.utils.embedding import get_embed_params
    from auto_ontology.utils.retriever import (
        get_data_objects_retriever,
        get_semantic_objects_retriever,
    )
    from auto_ontology.utils.sample_values import (
        dump_sample_values,
        parse_sample_values,
        render_sample_value,
        stringify_sample_values,
    )
