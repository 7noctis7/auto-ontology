# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Project files on disk, with undo.

A project lives in ``<home>/projects/<id>/project.json``. Every correction
and every completed document copies the previous file into ``history/``
(thirty copies at most) and clears ``redo/``. The home directory defaults
to ``~/AutoOntology`` so the files are where a person can find them.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from auto_ontology.text_ontology.studio_models import (
    SCHEMA_VERSION,
    Project,
    StudioSettings,
)

_HISTORY_LIMIT = 30


def now_iso() -> str:
    """Current UTC time, second precision, for project timestamps."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_home() -> Path:
    """Where projects and settings are stored."""
    override = os.environ.get("ONTOLOGY_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "AutoOntology"


class ProjectStore:
    """Read and write the studio's files under one home directory."""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        return self.home / "projects" / project_id

    def cache_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "cache"

    def settings(self) -> StudioSettings:
        path = self.home / "settings.json"
        if not path.is_file():
            return StudioSettings()
        try:
            return StudioSettings.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return StudioSettings()

    def save_settings(self, settings: StudioSettings) -> None:
        path = self.home / "settings.json"
        self._atomic_write(path, settings.model_dump_json(indent=2) + "\n")
        path.chmod(0o600)

    def list_projects(self) -> list[Project]:
        root = self.home / "projects"
        if not root.is_dir():
            return []
        found: list[Project] = []
        for child in root.iterdir():
            file = child / "project.json"
            if file.is_file():
                try:
                    found.append(self._read(file))
                except (OSError, ValueError):
                    continue
        found.sort(key=lambda project: project.updated_at, reverse=True)
        return found

    def create(self, name: str) -> Project:
        moment = now_iso()
        project = Project(
            id=uuid.uuid4().hex[:12],
            name=name.strip() or "Brouillon",
            created_at=moment,
            updated_at=moment,
        )
        self.save(project, snapshot=False)
        return project

    def load(self, project_id: str) -> Project:
        file = self.project_dir(project_id) / "project.json"
        if not file.is_file():
            raise FileNotFoundError(project_id)
        return self._read(file)

    def save(self, project: Project, *, snapshot: bool = False) -> None:
        directory = self.project_dir(project.id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "project.json"
        if snapshot and target.is_file():
            self._archive(directory / "history", target.read_text(encoding="utf-8"))
            self._clear(directory / "redo")
        project.updated_at = now_iso()
        self._atomic_write(target, project.model_dump_json(indent=2) + "\n")

    def can_undo(self, project_id: str) -> bool:
        return any(self._history(project_id).glob("*.json"))

    def can_redo(self, project_id: str) -> bool:
        return any((self.project_dir(project_id) / "redo").glob("*.json"))

    def undo(self, project_id: str) -> Project:
        return self._swap(project_id, source="history", destination="redo")

    def redo(self, project_id: str) -> Project:
        return self._swap(project_id, source="redo", destination="history")

    def remember_upload(
        self, project_id: str, document_id: str, filename: str, data: bytes
    ) -> Path:
        """Keep the original bytes next to the project, under a safe name."""
        folder = self.project_dir(project_id) / "documents"
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:80] or "document"
        target = folder / f"{document_id}_{safe}"
        target.write_bytes(data)
        return target

    def _history(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "history"

    def _swap(self, project_id: str, *, source: str, destination: str) -> Project:
        directory = self.project_dir(project_id)
        pile = sorted((directory / source).glob("*.json"))
        if not pile:
            raise ValueError(
                "Rien à annuler." if source == "history" else "Rien à rétablir."
            )
        current = directory / "project.json"
        self._archive(directory / destination, current.read_text(encoding="utf-8"))
        latest = pile[-1]
        current.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
        latest.unlink()
        return self.load(project_id)

    def _read(self, path: Path) -> Project:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(data.get("schema_version", 1))
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"Ce projet utilise le schéma {version}. "
                f"Cette application connaît le schéma {SCHEMA_VERSION}."
            )
        return Project.model_validate(data)

    def _archive(self, folder: Path, content: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{time.time_ns()}.json").write_text(content, encoding="utf-8")
        files = sorted(folder.glob("*.json"))
        while len(files) > _HISTORY_LIMIT:
            files.pop(0).unlink()

    @staticmethod
    def _clear(folder: Path) -> None:
        if not folder.is_dir():
            return
        for file in folder.glob("*.json"):
            file.unlink()

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
