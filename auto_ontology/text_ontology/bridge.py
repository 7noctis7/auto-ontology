# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Documents and data in one query.

The facts read from documents are offered to SQL as four views next to the
spreadsheet tables, so one ``SELECT`` can join "ACME's credit limit" (a
table) with "ACME is located in Lyon" (a contract)::

    onto_facts       subject, subject_key, subject_type, predicate,
                     object, object_key, object_type, document, quote
    onto_attributes  entity, entity_key, key, value, document, quote
    onto_entities    name, key, class, facts
    onto_rules       text, source, created_at, tags

``okey(text)`` gives the join key both sides share: accents, case,
punctuation and a trailing legal form (SA, SAS, Inc…) do not count, so
``okey(clients.nom) = onto_facts.subject_key`` matches "ACME S.A." with
"Acme". The views are built in memory for each query, on the same read-only,
file-less connection as any other query.

:func:`ask_data` turns a question into such a query with the configured
model, runs it (with one corrected retry), and answers from the rows only,
with the passages behind the facts it used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_ontology.text_ontology.normalize import ascii_fold
from auto_ontology.text_ontology.studio_models import Project
from auto_ontology.text_ontology.tables import SqlResult, TableError, run_sql

FACT_VIEWS: dict[str, tuple[str, ...]] = {
    "onto_facts": (
        "subject",
        "subject_key",
        "subject_type",
        "predicate",
        "object",
        "object_key",
        "object_type",
        "document",
        "quote",
    ),
    "onto_attributes": ("entity", "entity_key", "key", "value", "document", "quote"),
    "onto_entities": ("name", "key", "class", "facts"),
    "onto_rules": ("text", "source", "created_at", "tags"),
}
_LEGAL_FORM = re.compile(
    r"\s+(?:sa|sas|sasu|sarl|eurl|sci|snc|gie|inc|llc|ltd|plc|gmbh|ag|bv|nv|spa"
    r"|srl|corp|co|company|corporation|limited)$"
)
_ROWS_FOR_ANSWER = 30
_MAX_ATTEMPTS = 2


def okey(value: object) -> str | None:
    """The join key of a name: ``"ACME S.A."`` and ``"Acme"`` give ``"acme"``."""
    if value is None:
        return None
    text = ascii_fold(str(value)).casefold()
    text = " ".join(re.sub(r"[^\w]+", " ", text.replace(".", "")).split())
    return _LEGAL_FORM.sub("", text) or text


def _first_source(sources: list[Any]) -> tuple[str, str]:
    if not sources:
        return "", ""
    return sources[0].filename, sources[0].quote


def fact_frames(project: Project) -> dict[str, Any]:
    """The four views, as DataFrames."""
    import pandas as pd

    provenance = {
        (okey(t.subject), t.predicate, okey(t.object)): t.sources
        for t in project.triplets
    }
    facts = []
    entity_class: dict[str, tuple[str, str]] = {}
    counts: dict[str, int] = {}
    for t in project.ontology.triplets:
        document, quote = _first_source(
            provenance.get((okey(t.subject), t.predicate, okey(t.object)), [])
        )
        subject_key, object_key = okey(t.subject) or "", okey(t.object) or ""
        facts.append(
            (
                t.subject,
                subject_key,
                t.subject_type,
                t.predicate,
                t.object,
                object_key,
                t.object_type,
                document,
                quote,
            )
        )
        for name, key, kind in (
            (t.subject, subject_key, t.subject_type),
            (t.object, object_key, t.object_type),
        ):
            entity_class.setdefault(key, (name, kind))
            counts[key] = counts.get(key, 0) + 1
    attribute_sources = {
        (okey(a.entity), a.key, a.value): a.sources for a in project.attributes
    }
    attributes = []
    for a in project.ontology.attributes:
        key = okey(a.entity) or ""
        document, quote = _first_source(
            attribute_sources.get((key, a.key, a.value), [])
        )
        attributes.append((a.entity, key, a.key, a.value, document, quote))
        entity_class.setdefault(key, (a.entity, ""))
        counts[key] = counts.get(key, 0) + 1
    entities = [
        (name, key, kind, counts.get(key, 0))
        for key, (name, kind) in entity_class.items()
    ]
    rules = [
        (r.text, r.source, r.created_at, ", ".join(r.tags))
        for r in project.rules
        if r.status == "certified"
    ]
    rows = {
        "onto_facts": facts,
        "onto_attributes": attributes,
        "onto_entities": entities,
        "onto_rules": rules,
    }
    return {
        name: pd.DataFrame(rows[name], columns=list(columns)).astype(
            {c: "string" for c in columns if c != "facts"}
        )
        for name, columns in FACT_VIEWS.items()
    }


def prepare_for(project: Project) -> Callable[[Any], None]:
    """Register the views and ``okey`` on a connection."""
    frames = fact_frames(project)

    def prepare(connection: Any) -> None:
        connection.create_function(
            "okey", okey, ["VARCHAR"], "VARCHAR", null_handling="special"
        )
        for name, frame in frames.items():
            connection.register(name, frame)

    return prepare


def run_bridge_sql(
    project_dir: Path, project: Project, sql: str, *, limit: int = 200
) -> SqlResult:
    """:func:`tables.run_sql` with the fact views and ``okey`` available."""
    return run_sql(project_dir, sql, limit=limit, prepare=prepare_for(project))


def describe_views(project: Project) -> str:
    """The views, for a prompt or a terminal, with their row counts."""
    frames = fact_frames(project)
    lines = []
    for name, columns in FACT_VIEWS.items():
        lines.append(
            f"Vue {name} ({len(frames[name])} lignes, depuis les documents) : "
            + ", ".join(columns)
        )
    lines.append(
        "Fonction okey(texte) : clé de jointure (sans casse, accents, ponctuation "
        "ni forme juridique), à comparer aux colonnes *_key."
    )
    return "\n".join(lines)


# --- Questions in plain words --------------------------------------------------------

SQL_SYSTEM = """\
You write one DuckDB SELECT query that answers the user's question from the \
tables and views below, and nothing else.
Rules:
- One read-only SELECT (WITH is fine). No other statement, no file access.
- Use only the tables, views and columns listed. Quote odd column names with \
double quotes.
- Names in spreadsheet columns and in the onto_* views are spelled differently: \
join them with okey(), e.g. `JOIN onto_facts f ON okey(c.client) = f.subject_key`.
- Facts read from documents are in onto_facts (relations) and onto_attributes \
(characteristics); keep their `document` and `quote` columns in the result \
when you use them, so the answer can cite them.
- Add LIMIT 50 unless the question asks for a total.
Answer with JSON only: {"sql": "...", "explanation": "one sentence"}"""

ANSWER_SYSTEM = """\
You answer the user's question in their language, in one to three sentences, \
using only the query result given. Quote numbers exactly. If the result is \
empty or does not answer the question, say so plainly. Do not invent anything.
Answer with JSON only: {"answer": "..."}"""


@dataclass
class DataAnswer:
    question: str
    answer: str = ""
    sql: str = ""
    explanation: str = ""
    result: SqlResult | None = None
    citations: list[dict[str, str]] = field(default_factory=list)
    attempts: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "answer": self.answer,
            "sql": self.sql,
            "explanation": self.explanation,
            "result": self.result.as_dict() if self.result else None,
            "citations": self.citations,
            "attempts": self.attempts,
        }

    def markdown(self) -> str:
        lines = [self.answer or "(pas de réponse)", "", "```sql", self.sql, "```"]
        if self.result is not None and self.result.columns:
            lines += ["", self.result.as_table()]
        if self.citations:
            lines += ["", "Sources :"]
            lines += [f"- {c['document']} : « {c['quote']} »" for c in self.citations]
        return "\n".join(lines) + "\n"


def schema_text(project: Project) -> str:
    """Tables and views with columns and samples, as given to the model."""
    from auto_ontology.text_ontology.tables import describe_tables

    parts = [
        describe_tables(project) or "(aucune table chargée)",
        describe_views(project),
    ]
    rules = [r.text for r in project.rules if r.status == "certified"]
    if rules:
        parts.append("Règles certifiées : " + " | ".join(rules[:10]))
    return "\n\n".join(parts)


def complete_text(llm: Any, system: str, user: str) -> str:
    """One free-text answer from any configured model.

    :class:`LocalChatModel` and the demo model expose ``complete``; a
    LangChain chat model is invoked with a system and a user message.
    """
    complete = getattr(llm, "complete", None)
    if callable(complete):
        return str(complete(system, user))
    from langchain_core.messages import HumanMessage, SystemMessage

    reply = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = getattr(reply, "content", reply)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _json_field(text: str, name: str) -> str:
    from auto_ontology.text_ontology.local_llm import parse_json_object

    try:
        payload, _repaired = parse_json_object(text)
    except ValueError:
        payload = {}
    value = payload.get(name) if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    if name == "sql":
        fenced = re.search(r"```(?:sql)?\s*(.+?)```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()
        bare = re.search(r"((?:WITH|SELECT)\b.+)", text, re.DOTALL | re.IGNORECASE)
        if bare:
            return bare.group(1).strip()
    return ""


def ask_data(
    project: Project, project_dir: Path, question: str, llm: Any
) -> DataAnswer:
    """Question → SQL (checked, one corrected retry) → rows → grounded answer."""
    question = " ".join(question.split())
    if not question:
        raise TableError("Posez une question.")
    result = DataAnswer(question=question)
    schema = schema_text(project)
    user = f"Schema:\n{schema}\n\nQuestion: {question}"
    error = ""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result.attempts = attempt
        prompt = user
        if error:
            prompt += (
                f"\n\nYour previous query was:\n{result.sql}\n"
                f"It failed with: {error}\nWrite a corrected query."
            )
        reply = complete_text(llm, SQL_SYSTEM, prompt)
        result.sql = _json_field(reply, "sql")
        result.explanation = _json_field(reply, "explanation")
        if not result.sql:
            error = "the answer contained no SQL query"
            continue
        try:
            result.result = run_bridge_sql(project_dir, project, result.sql, limit=200)
            break
        except TableError as exc:
            error = str(exc)
    if result.result is None:
        raise TableError(
            f"Le modèle n'a pas produit de requête valable ({error}). "
            'Reformulez la question, ou écrivez la requête : ontology sql "…"'
        )
    rows = result.result.rows[:_ROWS_FOR_ANSWER]
    table = json.dumps(
        {"columns": result.result.columns, "rows": rows},
        ensure_ascii=False,
        default=str,
    )
    reply = complete_text(
        llm,
        ANSWER_SYSTEM,
        f"Question: {question}\nSQL: {result.sql}\nResult: {table}",
    )
    result.answer = _json_field(reply, "answer") or _fallback_answer(result.result)
    result.citations = _citations(project, result.result)
    return result


def _fallback_answer(rows: SqlResult) -> str:
    if not rows.rows:
        return "La requête ne renvoie aucune ligne."
    return f"{len(rows.rows)} ligne(s) trouvée(s) ; voir le tableau."


def _citations(
    project: Project, rows: SqlResult, limit: int = 5
) -> list[dict[str, str]]:
    """Passages behind the result: its quote column, else facts on its names."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(document: str, quote: str) -> None:
        if document and quote and (document, quote) not in seen and len(found) < limit:
            seen.add((document, quote))
            found.append({"document": document, "quote": quote})

    columns = [c.lower() for c in rows.columns]
    if "quote" in columns and "document" in columns:
        q, d = columns.index("quote"), columns.index("document")
        for row in rows.rows:
            add(str(row[d] or ""), str(row[q] or ""))
    if found:
        return found
    keys = {okey(value) for row in rows.rows for value in row if isinstance(value, str)}
    keys.discard(None)
    for item in project.triplets:
        if okey(item.subject) in keys or okey(item.object) in keys:
            for source in item.sources[:1]:
                add(source.filename, source.quote)
    return found
