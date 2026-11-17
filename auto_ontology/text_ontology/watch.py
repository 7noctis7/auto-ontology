# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import files that appear in a folder.

The same file is not extracted twice: the pipeline skips a fingerprint it
already stored. The loop is started by ``ontology serve`` and stays quiet
when no folder is configured.
"""

from __future__ import annotations

import threading
from pathlib import Path

from auto_ontology.text_ontology.documents import DocumentReadError, load_bytes
from auto_ontology.text_ontology.llm_settings import build_llm, resolve_llm_config
from auto_ontology.text_ontology.pipeline import IngestError, ingest_document
from auto_ontology.text_ontology.sample import FakeLLM

_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".pdf",
    ".epub",
    ".docx",
    ".html",
    ".htm",
    ".rst",
    ".csv",
    ".json",
}


def watch_loop(studio: object, stop: threading.Event) -> None:
    """Poll the configured folder until *stop* is set."""
    seen: set[tuple[str, int]] = set()
    while not stop.is_set():
        try:
            _scan(studio, seen)
        except Exception:
            # A bad file must not kill the page. The next pass tries again.
            pass
        stop.wait(3)


def _scan(studio: object, seen: set[tuple[str, int]]) -> None:
    store = studio.store  # type: ignore[attr-defined]
    folder = Path(store.settings().watch_dir.strip())
    if not str(folder) or folder == Path("."):
        return
    if not folder.is_dir():
        return
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
            continue
        stamp = (str(path), path.stat().st_mtime_ns)
        if stamp in seen:
            continue
        seen.add(stamp)
        _ingest_path(studio, path)


def _ingest_path(studio: object, path: Path) -> None:
    store = studio.store  # type: ignore[attr-defined]
    if getattr(studio, "running", False):
        return
    try:
        loaded = load_bytes(path.name, path.read_bytes())
    except (OSError, DocumentReadError):
        return
    config = resolve_llm_config(store)
    fake = bool(getattr(studio, "fake", False))
    if fake or getattr(studio, "llm_factory", None) is not None:
        factory = getattr(studio, "llm_factory", None)
        llm = factory() if factory is not None else FakeLLM()
        label = "démonstration"
    elif not config.configured:
        return
    else:
        try:
            llm = build_llm(config)
        except EnvironmentError:
            return
        label = config.model
    projects = store.list_projects()
    project = projects[0] if projects else store.create("Import")
    try:
        ingest_document(
            store,
            project,
            loaded,
            config=config,
            llm=llm,
            model_label=label,
            on_event=lambda _event: None,
        )
    except IngestError:
        return


def start_watcher(studio: object) -> threading.Event:
    """Daemon thread. The returned event stops it."""
    stop = threading.Event()
    threading.Thread(
        target=watch_loop, args=(studio, stop), name="ontology-watch", daemon=True
    ).start()
    return stop
