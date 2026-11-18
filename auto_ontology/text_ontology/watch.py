# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import files that appear in a folder.

Sub-folders are read too (a notes vault), an email brings its attachments
and a zip its notes; see :mod:`inbox`. The same content is not extracted
twice: the pipeline skips a text it already stored. Every arrival is
journaled for ``ontology brief``. The loop is started by ``ontology serve``
and stays quiet when no folder is configured.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from auto_ontology.text_ontology.inbox import ingest_item, unpack, unreadable, walk
from auto_ontology.text_ontology.llm_settings import (
    build_llm,
    model_label,
    resolve_llm_config,
)
from auto_ontology.text_ontology.sample import FakeLLM

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from auto_ontology.text_ontology.llm_settings import LlmConfig

logger = logging.getLogger(__name__)


def watch_loop(studio: object, stop: threading.Event) -> None:
    """Poll the configured folder until *stop* is set."""
    seen: set[tuple[str, int]] = set()
    while not stop.is_set():
        try:
            _scan(studio, seen)
        except Exception:
            # A bad file must not kill the page, but it must not vanish either:
            # this swallowed every failure, a wrong call included, for good.
            logger.exception("Watched folder: a file could not be ingested")
        stop.wait(3)


@contextlib.contextmanager
def _claim(studio: object) -> Iterator[bool]:
    """Mark the studio busy for one file, as the page does for an upload.

    Yields ``False`` when the page is already extracting: the file is then
    tried again on the next pass instead of being written concurrently.
    """
    lock = getattr(studio, "lock", None)
    if lock is None:  # a bare stand-in, in tests
        yield True
        return
    with lock:
        if getattr(studio, "running", False):
            busy = True
        else:
            busy = False
            studio.running = True  # type: ignore[attr-defined]
    try:
        yield not busy
    finally:
        if not busy:
            with lock:
                studio.running = False  # type: ignore[attr-defined]


def _scan(studio: object, seen: set[tuple[str, int]]) -> None:
    store = studio.store  # type: ignore[attr-defined]
    folder = Path(store.settings().watch_dir.strip())
    if not str(folder) or folder == Path("."):
        return
    if not folder.is_dir():
        return
    # Sub-folders too: an Obsidian vault or an unpacked Notion export.
    for path in walk(folder, exclude=store.home):
        try:
            stamp = (str(path), path.stat().st_mtime_ns)
        except OSError:
            continue  # removed between the listing and now
        if stamp in seen:
            continue
        if _ingest_path(studio, path):
            seen.add(stamp)


def _ingest_path(studio: object, path: Path) -> bool:
    """Ingest *path*; ``False`` means "busy, try again on the next pass"."""
    with _claim(studio) as free:
        if not free:
            return False
        _ingest_claimed(studio, path)
    return True


def _ingest_claimed(studio: object, path: Path) -> None:
    store = studio.store  # type: ignore[attr-defined]
    # The project open in the studio, not merely the first one listed.
    project = store.current() or store.create("Import")
    try:
        items = unpack(path.name, path.read_bytes())
    except OSError:
        return  # being written or removed: the next pass sees it again
    except ValueError as exc:  # DocumentReadError: a broken email or zip
        unreadable(store.project_dir(project.id), path.name, str(exc))
        logger.warning("Watched folder: %s could not be read (%s)", path.name, exc)
        return
    model = _model_source(studio)
    for item in items:
        outcome = ingest_item(store, project.id, item, model=model)
        if outcome.kind == "error":
            logger.warning("Watched folder: %s", outcome.line())


def _model_source(studio: object) -> object:
    """Build the model once, when the first document needs it."""
    built: list[tuple[LlmConfig, BaseChatModel, str] | None] = []

    def source() -> tuple[LlmConfig, BaseChatModel, str] | None:
        if not built:
            built.append(_build_model(studio))
        return built[0]

    return source


def _build_model(studio: object) -> tuple[LlmConfig, BaseChatModel, str] | None:
    config = resolve_llm_config(studio.store)  # type: ignore[attr-defined]
    factory = getattr(studio, "llm_factory", None)
    if factory is not None:
        return config, factory(config), "démonstration"
    if getattr(studio, "fake", False):
        return config, FakeLLM(), "démonstration"
    if not config.configured:
        return None
    try:
        llm = build_llm(config)
    except EnvironmentError:
        return None
    return config, llm, model_label(llm, config)


def start_watcher(studio: object) -> threading.Event:
    """Daemon thread. The returned event stops it."""
    stop = threading.Event()
    threading.Thread(
        target=watch_loop, args=(studio, stop), name="ontology-watch", daemon=True
    ).start()
    return stop
