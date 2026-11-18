# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The studio's MCP server, over standard input, with no extra dependency.

It speaks the JSON-RPC methods an MCP client sends (``initialize``,
``tools/list``, ``tools/call``, ``ping``) and works on the project the studio
has open under ``ONTOLOGY_HOME``, read again on every call so it sees what
the page or the watched folder just added.

Reading tools are always there. The two writing tools (``remember_fact``,
``certify_rule``) are listed only with ``--allow-writes``, and each write is
two calls: the first returns a preview and a ``confirm_token``, the second,
with that token and the same arguments, writes, as one undoable step logged
under ``mcp`` (see :mod:`confirm`). A write is refused while an extraction
runs on the project.

::

    ontology mcp                  # read only
    ontology mcp --allow-writes   # plus confirmed writes
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from auto_ontology.text_ontology.store import ProjectStore, default_home
from auto_ontology.text_ontology.studio_models import Project

logger = logging.getLogger(__name__)

# Newest first. The client's version is used when it is one of these.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "auto-ontology-studio"
SERVER_VERSION = "2"
_ACTOR = "mcp"

INSTRUCTIONS = """\
Auto-Ontology studio: facts, rules and tables of the person's current project, \
each fact with the passage it was read from.
- Start with `brief` (what is new) or `search` (find a name), then \
`get_concept` for everything about one name.
- For numbers, `list_tables` then `describe_table`, then `run_sql` (one \
read-only SELECT). The facts are SQL views too (onto_facts, onto_attributes): \
join them with a table through okey(), and keep their `quote` column to cite.
- `ask_question` answers from the facts, with citations; quote them.
- Writing tools, when present, take two calls: call once without \
`confirm_token`, show the preview to the person, then call again with the \
same arguments and the returned `confirm_token`."""


class ToolError(ValueError):
    """A tool could not answer. The message is for the agent and the person."""


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    read_only: bool = True
    hidden: bool = False  # an older name, still answered, no longer listed

    def listing(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": self.properties,
            "additionalProperties": False,
        }
        if self.required:
            schema["required"] = list(self.required)
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.read_only,
                "openWorldHint": False,
            },
        }


def _string(description: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def _integer(description: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "minimum": minimum,
        "maximum": maximum,
    }


_CONFIRM = _string(
    "Leave out on the first call (preview). Then the token that call returned."
)

READ_TOOLS = (
    Tool(
        "search",
        "Search",
        "Find classes, entities and facts whose name contains the text.",
        {"query": _string("Text to look for."), "limit": _integer("At most.", 1, 100)},
        ("query",),
    ),
    Tool(
        "get_concept",
        "Get concept",
        "Everything about one name: its relations both ways, its attributes, "
        "and the documents and passages they come from.",
        {"name": _string("A class or entity name.")},
        ("name",),
    ),
    Tool(
        "list_concepts",
        "List classes",
        "The classes of the project, with their parent and documents.",
    ),
    Tool(
        "facts",
        "Facts",
        "Facts (subject, predicate, object) with their passage; filter by name "
        "or predicate.",
        {
            "name": _string("Only facts that mention this name."),
            "predicate": _string("Only this relation."),
            "limit": _integer("At most.", 1, 1000),
        },
    ),
    Tool(
        "lineage",
        "Lineage",
        "Document, chunk and quote behind one name.",
        {"name": _string("A class, entity or value.")},
        ("name",),
    ),
    Tool(
        "ask_question",
        "Ask a question",
        "Answer a question from the extracted facts, with the passages cited.",
        {"question": _string("The question, in the person's words.")},
        ("question",),
    ),
    Tool(
        "brief",
        "Brief",
        "What came in since a moment (documents, tables, facts, rules) and what "
        "needs a look (failed chunks, unreadable files, orphan entities).",
        {"since": _string("24h, 7d, 2w, today, or a date (YYYY-MM-DD).")},
    ),
    Tool(
        "list_tables",
        "List tables",
        "Tables loaded from spreadsheets (name, rows, source file), and the "
        "onto_* views of the facts read from documents, to join with okey().",
    ),
    Tool(
        "describe_table",
        "Describe table",
        "Columns of one table, with types, empty values and sample values.",
        {"table": _string("A name from list_tables.")},
        ("table",),
    ),
    Tool(
        "run_sql",
        "Run SQL",
        "Run one read-only SELECT (DuckDB dialect) on the project's tables and "
        "the onto_facts, onto_attributes, onto_entities and onto_rules views. "
        "Join names with okey(), e.g. okey(t.client) = f.subject_key. Files, "
        "writes and settings are refused; rows are capped.",
        {"sql": _string("One SELECT statement."), "limit": _integer("Rows.", 1, 5000)},
        ("sql",),
    ),
    Tool(
        "export_report",
        "Export report",
        "A Markdown report built from the facts: 'meeting' sorts one document's "
        "facts into participants, decisions, actions and figures; 'comparison' "
        "puts a few entities side by side.",
        {
            "kind": _string("meeting or comparison.", enum=["meeting", "comparison"]),
            "document": _string("meeting: part of a file name (default: latest)."),
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "comparison: two or more entity names.",
            },
        },
        ("kind",),
    ),
    Tool(
        "preview_action",
        "Preview a correction",
        "What a rename or a merge would change. Writes nothing.",
        {
            "name": _string("rename or merge.", enum=["rename", "merge"]),
            "source": _string("The name to change."),
            "target": _string("The name to use instead."),
        },
        ("name",),
    ),
    # Names of the first version, answered for clients configured with them.
    Tool(
        "neighbours",
        "Neighbours",
        "See get_concept.",
        {"name": _string("")},
        ("name",),
        hidden=True,
    ),
    Tool(
        "ask",
        "Ask",
        "See ask_question.",
        {"question": _string("")},
        ("question",),
        hidden=True,
    ),
)

WRITE_TOOLS = (
    Tool(
        "remember_fact",
        "Remember a fact",
        "Add one fact the person told you, with where it comes from. Either "
        "subject, predicate, object (a relation) or entity, key, value (a "
        "characteristic). Two calls: preview, then confirm_token. Undoable in "
        "the studio.",
        {
            "subject": _string("Relation: the entity it is about."),
            "predicate": _string("Relation: a verb in snake_case (dirige, signe)."),
            "object": _string("Relation: the other entity."),
            "subject_type": _string("Class of the subject, if it is new."),
            "object_type": _string("Class of the object, if it is new."),
            "entity": _string("Characteristic: the entity."),
            "key": _string("Characteristic: its name in snake_case."),
            "value": _string("Characteristic: its value."),
            "source": _string("Where it comes from: meeting, message, person."),
            "confirm_token": _CONFIRM,
        },
        ("source",),
        read_only=False,
    ),
    Tool(
        "certify_rule",
        "Certify a rule",
        "Record a business rule or decision the person confirms (for example "
        "'a contract over 50 k€ needs two signatures'). Two calls: preview, "
        "then confirm_token. Undoable in the studio.",
        {
            "text": _string("The rule, in one sentence."),
            "rationale": _string("Why it holds."),
            "source": _string("Where it was decided: document, meeting, person."),
            "tags": {"type": "array", "items": {"type": "string"}},
            "confirm_token": _CONFIRM,
        },
        ("text",),
        read_only=False,
    ),
)


class StudioMcp:
    """One MCP session on one studio home."""

    def __init__(self, store: ProjectStore, *, allow_writes: bool = False) -> None:
        from auto_ontology.text_ontology.confirm import Confirmations

        self.store = store
        self.allow_writes = allow_writes
        self.protocol = PROTOCOL_VERSIONS[-1]
        self.confirmations = Confirmations()
        tools = READ_TOOLS + (WRITE_TOOLS if allow_writes else ())
        self.tools = {tool.name: tool for tool in tools}

    # --- JSON-RPC --------------------------------------------------------

    def handle(self, message: object) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, -32600, "Requête invalide.")
        method = str(message.get("method") or "")
        request_id = message.get("id")
        if "id" not in message:
            return None  # a notification: no answer, whatever its name
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, -32602, "params doit être un objet.")
        if method == "initialize":
            wanted = str(params.get("protocolVersion") or "")
            self.protocol = (
                wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            )
            result: dict[str, Any] = {
                "protocolVersion": self.protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            }
        elif method == "tools/list":
            result = {
                "tools": [t.listing() for t in self.tools.values() if not t.hidden]
            }
        elif method == "tools/call":
            name = str(params.get("name") or "")
            if name not in self.tools:
                return _error(request_id, -32602, f"Outil inconnu : {name}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(request_id, -32602, "arguments doit être un objet.")
            result = self.call(name, arguments)
        elif method == "ping":
            result = {}
        else:
            return _error(request_id, -32601, f"Méthode inconnue : {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool. A refusal is a tool result marked ``isError``."""
        from auto_ontology.text_ontology.agent_writes import WriteError
        from auto_ontology.text_ontology.confirm import ConfirmationError
        from auto_ontology.text_ontology.mutations import EditError
        from auto_ontology.text_ontology.reports import ReportError
        from auto_ontology.text_ontology.tables import TableError

        try:
            payload = self._run(name, arguments)
        except (
            ToolError,
            WriteError,
            ConfirmationError,
            EditError,
            ReportError,
            TableError,
        ) as exc:
            return _result(str(exc), error=True)
        except Exception:  # noqa: BLE001 - a client must get an answer
            logger.exception("MCP tool %s failed", name)
            return _result(
                f"L'outil {name} a échoué ; voir le journal du serveur.", error=True
            )
        structured = self.protocol >= "2025-06-18"
        return _result(payload, structured=structured)

    # --- Tools ------------------------------------------------------------

    def _project(self) -> Project:
        project = self.store.current()
        if project is None:
            raise ToolError(
                "Aucun projet. Ouvrez le studio (ontology open <dossier>) et "
                "importez un document."
            )
        return project

    def _run(self, name: str, a: dict[str, Any]) -> object:
        handlers: dict[str, Callable[[Project, dict[str, Any]], object]] = {
            "search": self._search,
            "get_concept": self._concept,
            "neighbours": self._concept,
            "list_concepts": self._concepts,
            "facts": self._facts,
            "lineage": self._lineage,
            "ask_question": self._ask,
            "ask": self._ask,
            "brief": self._brief,
            "list_tables": self._tables,
            "describe_table": self._describe,
            "run_sql": self._sql,
            "export_report": self._report,
            "preview_action": self._preview_action,
            "remember_fact": self._remember,
            "certify_rule": self._certify,
        }
        return handlers[name](self._project(), a)

    @staticmethod
    def _search(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.query import search

        return search(project, _required(a, "query"), limit=_limit(a, 20, 100))

    @staticmethod
    def _concept(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.lineage import lineage_for
        from auto_ontology.text_ontology.normalize import entity_key
        from auto_ontology.text_ontology.query import neighbours

        name = _required(a, "name")
        found = neighbours(project, name)
        key = entity_key(name)
        found["attributes"] = [
            {"key": item.key, "value": item.value}
            for item in project.ontology.attributes
            if entity_key(item.entity) == key
        ]
        cls = next(
            (c for c in project.ontology.classes if entity_key(c.name) == key), None
        )
        if cls is not None:
            found["class"] = {"parent": cls.parent, "description": cls.description}
            found["found"] = True
        found["documents"] = sorted(
            {
                step.get("filename", "")
                for step in lineage_for(project, str(found["name"])).get("steps", [])
                if isinstance(step, dict) and step.get("filename")
            }
        )
        return found

    @staticmethod
    def _concepts(project: Project, _a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.query import concepts

        return {"classes": concepts(project)}

    @staticmethod
    def _facts(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.normalize import entity_key
        from auto_ontology.text_ontology.query import list_facts

        rows = list_facts(project, limit=len(project.ontology.triplets))
        if name := str(a.get("name") or "").strip():
            key = entity_key(name)
            rows = [
                r
                for r in rows
                if key in {entity_key(str(r["subject"])), entity_key(str(r["object"]))}
            ]
        if predicate := str(a.get("predicate") or "").strip():
            rows = [r for r in rows if r["predicate"] == predicate]
        limit = _limit(a, 200, 1000)
        return {
            "facts": rows[:limit],
            "total": len(rows),
            "truncated": len(rows) > limit,
        }

    @staticmethod
    def _lineage(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.lineage import lineage_for

        return lineage_for(project, _required(a, "name"))

    @staticmethod
    def _ask(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.query import answer

        return answer(project, _required(a, "question"))

    def _brief(self, project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.daily import brief, parse_since
        from auto_ontology.text_ontology.inbox import read_journal

        try:
            moment = parse_since(str(a.get("since") or "24h"))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        journal = read_journal(self.store.project_dir(project.id), moment)
        report = brief(project, moment, journal)
        return {**report.as_dict(), "markdown": report.markdown()}

    @staticmethod
    def _tables(project: Project, _a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.bridge import FACT_VIEWS, fact_frames

        frames = fact_frames(project)
        return {
            "tables": [
                {
                    "table": d.table,
                    "rows": d.rows,
                    "source": d.source,
                    "sheet": d.sheet,
                    "columns": [c.name for c in d.columns],
                }
                for d in project.datasets
            ],
            "views": [
                {"view": name, "rows": len(frames[name]), "columns": list(columns)}
                for name, columns in FACT_VIEWS.items()
            ],
            "join": "okey(text) = <view>.*_key joins a table's names with the facts.",
        }

    @staticmethod
    def _describe(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.bridge import FACT_VIEWS, fact_frames

        wanted = _required(a, "table")
        record = next((d for d in project.datasets if d.table == wanted), None)
        if record is not None:
            return record.model_dump()
        if wanted in FACT_VIEWS:
            frame = fact_frames(project)[wanted]
            return {
                "view": wanted,
                "rows": len(frame),
                "columns": [
                    {
                        "name": column,
                        "samples": [
                            str(v) for v in frame[column].dropna().unique()[:5]
                        ],
                    }
                    for column in FACT_VIEWS[wanted]
                ],
            }
        names = ", ".join([*(d.table for d in project.datasets), *FACT_VIEWS])
        raise ToolError(f"Table inconnue : {wanted} (tables : {names}).")

    def _sql(self, project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.bridge import run_bridge_sql

        result = run_bridge_sql(
            self.store.project_dir(project.id),
            project,
            _required(a, "sql"),
            limit=_limit(a, 200, 5000),
        )
        return result.as_dict()

    @staticmethod
    def _report(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.reports import comparison, meeting

        kind = _required(a, "kind")
        if kind == "meeting":
            return meeting(project, str(a.get("document") or "") or None).as_dict()
        if kind == "comparison":
            names = a.get("names") or []
            if not isinstance(names, list):
                raise ToolError("names est une liste de noms.")
            return comparison(project, [str(n) for n in names]).as_dict()
        raise ToolError("kind vaut meeting ou comparison.")

    @staticmethod
    def _preview_action(project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.actions import preview_action

        source, target = str(a.get("source") or ""), str(a.get("target") or "")
        return preview_action(
            project,
            str(a.get("name") or "merge"),
            {
                "source": source,
                "target": target,
                "old": source,
                "new": target,
                "kind": "entity",
            },
        )

    def _remember(self, project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.agent_writes import preview_fact, remember_fact

        return self._two_step("remember_fact", project, a, preview_fact, remember_fact)

    def _certify(self, project: Project, a: dict[str, Any]) -> object:
        from auto_ontology.text_ontology.agent_writes import certify_rule, preview_rule

        return self._two_step("certify_rule", project, a, preview_rule, certify_rule)

    def _two_step(
        self,
        tool: str,
        project: Project,
        arguments: dict[str, Any],
        preview: Callable[[Project, dict[str, Any]], dict[str, object]],
        apply: Callable[..., dict[str, object]],
    ) -> object:
        if reason := self.store.busy_reason(project.id):
            raise ToolError(reason)
        revision = self.store.revision(project.id)
        token = str(arguments.get("confirm_token") or "")
        if not token:
            shown = preview(project, arguments)
            return {
                **shown,
                "applied": False,
                "confirm_token": self.confirmations.issue(
                    tool, arguments, project=project.id, revision=revision
                ),
                "next": "Montrez l'aperçu à la personne. Si elle accepte, "
                "rappelez l'outil avec les mêmes arguments et ce confirm_token "
                "(valable 5 minutes, une fois).",
            }
        self.confirmations.redeem(
            token, tool, arguments, project=project.id, revision=revision
        )
        done = apply(self.store, project, arguments, actor=_ACTOR)
        return {**done, "undo": "Annulable depuis le studio (Annuler)."}


# --- Helpers -------------------------------------------------------------------


def _required(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ToolError(f"Indiquez {name}.")
    return value


def _limit(arguments: dict[str, Any], default: int, ceiling: int) -> int:
    try:
        value = int(arguments.get("limit") or default)
    except (TypeError, ValueError) as exc:
        raise ToolError("limit est un nombre entier.") from exc
    return max(1, min(value, ceiling))


def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(
    payload: object, *, error: bool = False, structured: bool = False
) -> dict[str, Any]:
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": error,
    }
    if structured and not error:
        result["structuredContent"] = (
            payload if isinstance(payload, dict) else {"items": payload}
        )
    return result


def serve_mcp(home: object | None = None, *, allow_writes: bool = False) -> None:
    """Answer MCP JSON-RPC messages from stdin until it closes.

    Nothing but JSON-RPC goes to stdout: logs go to stderr.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    server = StudioMcp(
        ProjectStore(home or default_home()),  # type: ignore[arg-type]
        allow_writes=allow_writes,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = _error(None, -32700, "JSON illisible.")
        else:
            response = server.handle(message)
        if response is not None:
            sys.stdout.write(
                json.dumps(response, ensure_ascii=False, default=str) + "\n"
            )
            sys.stdout.flush()
