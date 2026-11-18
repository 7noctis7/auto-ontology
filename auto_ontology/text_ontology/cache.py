# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cache one LLM answer per chunk, so a repeated passage is not extracted twice.

The key is the system prompt, the model name and the exact user message
(which already contains the chunk and the names to reuse). A failed answer is
not stored, so the next run can try it again.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
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
    """One JSON file per answer, under a directory the user can delete.

    At most *max_entries* answers are kept: past that, the least recently
    used tenth is removed, so a long-lived project's cache stays bounded.
    """

    def __init__(self, directory: Path, *, max_entries: int = 5000) -> None:
        self.directory = directory
        self.max_entries = max_entries
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> TextOntology | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            ontology = TextOntology.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            return None
        with contextlib.suppress(OSError):
            os.utime(path)  # recently used: kept by the next pruning
        return ontology

    def put(self, key: str, ontology: TextOntology) -> None:
        path = self._path(key)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            ontology.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        self._prune()

    def _prune(self) -> None:
        entries = list(self.directory.glob("*.json"))
        if len(entries) <= self.max_entries:
            return

        def used(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        entries.sort(key=used)
        for path in entries[: len(entries) - int(self.max_entries * 0.9)]:
            with contextlib.suppress(OSError):
                path.unlink()
