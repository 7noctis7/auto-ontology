# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A small MCP server over standard input, with no extra dependency.

It speaks the JSON-RPC methods an MCP client sends at startup
(``initialize``, ``tools/list``, ``tools/call``) and reads the last project
under ``ONTOLOGY_HOME``. Tools only query; they do not extract.

::

    ontology mcp
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from auto_ontology.text_ontology.query import (
    answer,
    concepts,
    list_facts,
    neighbours,
    search,
)
from auto_ontology.text_ontology.store import ProjectStore, default_home

_TOOLS = (
    {
        "name": "list_concepts",
        "description": "Classes of the open ontology project.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search",
        "description": "Find concepts, entities and facts by text.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "neighbours",
        "description": "Relations that touch one name.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "facts",
        "description": "Triplets with the passage they came from.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ask",
        "description": "Answer a question from extracted facts, with citations.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
)


def serve_mcp(home: object | None = None) -> None:
    """Read MCP JSON-RPC messages from stdin until it closes."""
    store = ProjectStore(home or default_home())  # type: ignore[arg-type]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(store, message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def _handle(store: ProjectStore, message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    if method.startswith("notifications/"):
        return None
    request_id = message.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ontology-studio", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": list(_TOOLS)}
    elif method == "tools/call":
        result = _call(store, message.get("params") or {})
    elif method == "ping":
        result = {}
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Méthode inconnue : {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _call(store: ProjectStore, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    project = _project(store)
    if project is None:
        return _text("Aucun projet. Lancez ontology serve et déposez un document.")
    tools: dict[str, Callable[[], object]] = {
        "list_concepts": lambda: concepts(project),
        "search": lambda: search(project, str(arguments.get("query") or "")),
        "neighbours": lambda: neighbours(project, str(arguments.get("name") or "")),
        "facts": lambda: list_facts(project),
        "ask": lambda: answer(project, str(arguments.get("question") or "")),
    }
    if name not in tools:
        return _text(f"Outil inconnu : {name}")
    payload = tools[name]()
    return _text(json.dumps(payload, ensure_ascii=False, indent=2))


def _project(store: ProjectStore) -> object | None:
    settings = store.settings()
    if settings.last_project_id:
        try:
            return store.load(settings.last_project_id)
        except (FileNotFoundError, ValueError):
            pass
    projects = store.list_projects()
    return projects[0] if projects else None


def _text(value: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": value}], "isError": False}
