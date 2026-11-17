# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cache one LLM answer per chunk, so a repeated passage is not extracted twice.

The key is the system prompt, the model name and the exact user message
(which already contains the chunk and the names to reuse). A failed answer is
not stored, so the next run can try it again.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from auto_ontology.text_ontology.models import TextOntology


def chunk_cache_key(*, prompt: str, model_name: str, message: str) -> str:
    """A stable id for one successful chunk extraction."""
    digest = hashlib.sha256()
    digest.update(prompt.encode())
    digest.update(b"\0")
    digest.update(model_name.encode())
    digest.update(b"\0")
    digest.update(message.encode())
    return digest.hexdigest()


class ChunkCache(Protocol):
    """What the extractor needs in order to skip a chunk it has already seen."""

    def get(self, key: str) -> TextOntology | None: ...

    def put(self, key: str, ontology: TextOntology) -> None: ...


class FileChunkCache:
    """One JSON file per answer, under a directory the user can delete."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> TextOntology | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return TextOntology.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return None

    def put(self, key: str, ontology: TextOntology) -> None:
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            ontology.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
