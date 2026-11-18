# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HTTP API of the studio, documented by the OpenAPI page at ``/docs``.

The same functions back the page. A token is required only for clients that
are not on this machine, and only when ``ONTOLOGY_API_TOKEN`` is set.
"""

from __future__ import annotations

import hmac
import os
import uuid
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auto_ontology.text_ontology.actions import (
    action_names,
    commit_action,
    preview_action,
)
from auto_ontology.text_ontology.around import search_around
from auto_ontology.text_ontology.branches import (
    active_branch,
    checkout,
    create_branch,
    diff_projects,
    discard_branch,
    list_branches,
    merge_branch,
    read_branch,
)
from auto_ontology.text_ontology.explore import (
    compile_where,
    objects_of_type,
    page_rows,
    search_rows,
)
from auto_ontology.text_ontology.lineage import facts_of_document, lineage_for
from auto_ontology.text_ontology.query import (
    answer,
    compare,
    concepts,
    list_facts,
    neighbours,
    paths,
    search,
)
from auto_ontology.text_ontology.schema_layer import interfaces_for, sync_schema
from auto_ontology.text_ontology.sdkgen import render_sdk
from auto_ontology.text_ontology.similar import merge_candidates, semantic_search
from auto_ontology.text_ontology.studio_export import render_export
from auto_ontology.text_ontology.studio_models import Edit, NoteLink, ObjectSetDef

_LOCAL = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


class AskBody(BaseModel):
    question: str = ""


class SearchBody(BaseModel):
    where: dict[str, Any] | None = None
    pageToken: str = ""


class SetBody(BaseModel):
    name: str = ""
    description: str = ""
    query: dict[str, str] = Field(default_factory=dict)
    pinned_ids: list[str] = Field(default_factory=list)


class AroundBody(BaseModel):
    start: str = ""
    links: str = ""
    direction: str = "both"
    depth: int = 1
    target_type: str = ""


class BranchBody(BaseModel):
    name: str = ""


class NoteBody(BaseModel):
    source: str = ""
    target: str = ""
    label: str = "note"


class ActionBody(BaseModel):
    """Flat action parameters. Unknown keys are the action's own fields."""

    model_config = ConfigDict(extra="allow")


class PinBody(BaseModel):
    id: str = ""
    pinned: bool = True


class GenreBody(BaseModel):
    genre: str = ""
    domain: str = ""


class QuestionBody(BaseModel):
    text: str = ""


class MappingBody(BaseModel):
    source: str = ""
    iri: str = ""
    predicate: str = "owl:equivalentClass"


class BaseIriBody(BaseModel):
    base_iri: str = ""


def _require_write(request: Request) -> None:
    """A write needs the remote-write flag off this machine, and no extraction.

    The idle check sits here so that every route that writes through this
    helper waits for a running extraction, whose final save would erase it.
    """
    host = request.client.host if request.client else ""
    if not write_allowed(host):
        raise HTTPException(
            status_code=403,
            detail="Cette API est en consultation. "
            "ONTOLOGY_API_ALLOW_WRITE=1 autorise l'écriture.",
        )
    _require_idle(request)


def write_allowed(client_host: str) -> bool:
    """Local edits are allowed. A remote client writes only when asked explicitly."""
    if client_host in _LOCAL:
        return True
    return os.environ.get("ONTOLOGY_API_ALLOW_WRITE", "").strip() == "1"


def access_allowed(client_host: str, authorization: str, token: str) -> bool:
    """Local clients are always allowed. A remote client needs the token if one is set."""
    if client_host in _LOCAL or not token:
        return True
    # Constant time: the comparison must not tell how much of a guess was right.
    return hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode())


class SqlBody(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20_000)
    limit: int = Field(default=200, ge=1, le=5000)


class RuleBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    rationale: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)


def install_api(app: FastAPI) -> None:
    """Routes under ``/api/v1`` plus the token check and the Swagger description."""
    app.title = "Studio d'ontologie"
    app.description = (
        "Importer des documents, interroger les concepts et exporter l'ontologie. "
        "La page interactive est servie à la racine. Cette description est aussi "
        "lisible sur /docs."
    )

    @app.middleware("http")
    async def _guard(request: Request, call_next: Any) -> Response:
        if request.url.path.startswith("/api"):
            host = request.client.host if request.client else ""
            token = os.environ.get("ONTOLOGY_API_TOKEN", "").strip()
            header = request.headers.get("authorization", "")
            if not access_allowed(host, header, token):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "message": "Jeton requis. Envoyez Authorization: Bearer "
                        "et la valeur de ONTOLOGY_API_TOKEN.",
                    },
                )
        return await call_next(request)

    @app.get("/api/v1/concepts")
    def get_concepts(request: Request) -> dict[str, Any]:
        """Classes of the open project."""
        project = _project(request)
        return {"concepts": concepts(project)}

    @app.get("/api/v1/concepts/{name}/neighbours")
    def get_neighbours(name: str, request: Request) -> dict[str, Any]:
        """Relations that touch one concept or entity."""
        return neighbours(_project(request), name)

    @app.get("/api/v1/paths")
    def get_paths(request: Request, start: str = "", end: str = "") -> dict[str, Any]:
        """A short path between two names."""
        return paths(_project(request), start, end)

    @app.get("/api/v1/search")
    def get_search(request: Request, q: str = "") -> dict[str, Any]:
        """Names and facts containing the query."""
        return search(_project(request), q)

    @app.get("/api/v1/facts")
    def get_facts(request: Request) -> dict[str, Any]:
        """Triplets with the passage they were read from."""
        return {"facts": list_facts(_project(request))}

    @app.get("/api/v1/documents")
    def get_documents(request: Request) -> dict[str, Any]:
        """Imported documents, with type, domain and metadata."""
        project = _project(request)
        return {
            "documents": [
                {
                    "id": document.id,
                    "filename": document.filename,
                    "title": document.title,
                    "author": document.author,
                    "date": document.date,
                    "language": document.language,
                    "pages": document.pages,
                    "genre": document.genre,
                    "genre_confidence": document.genre_confidence,
                    "genre_source": document.genre_source,
                    "domain": document.domain,
                    "domain_confidence": document.domain_confidence,
                    "status": document.status,
                }
                for document in project.documents
            ]
        }

    @app.post("/api/v1/documents/{document_id}/genre")
    def post_genre(
        document_id: str, body: GenreBody, request: Request
    ) -> dict[str, Any]:
        """Correct a document type or domain by hand."""
        _require_idle(request)
        from auto_ontology.text_ontology.app.server import _remember_edit, _view
        from auto_ontology.text_ontology.mutations import apply_edit

        studio = request.app.state.studio
        project = _project(request)
        studio.store.save(project, snapshot=True)
        if body.genre:
            edit = Edit(op="set_genre", document_id=document_id, new=body.genre)
            apply_edit(project, edit)
            _remember_edit(studio, project, edit)
        if body.domain:
            edit = Edit(op="set_domain", document_id=document_id, new=body.domain)
            apply_edit(project, edit)
            _remember_edit(studio, project, edit)
        studio.store.save(project, snapshot=False)
        return _view(studio)

    @app.get("/api/v1/export")
    def get_export(request: Request, format: str = "json") -> Response:
        """Download the ontology. ``format`` is json, turtle, cypher, mermaid, html, csv, jsonld, jsonl or dashboard."""
        project = _project(request)
        try:
            body, filename, media = render_export(project, format)
        except ValueError as exc:
            return JSONResponse(
                status_code=400, content={"error": "format", "message": str(exc)}
            )
        return Response(
            content=body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/v1/ask")
    def post_ask(body: AskBody, request: Request) -> dict[str, Any]:
        """Answer from facts already extracted, each with its source passage."""
        return answer(_project(request), body.question)

    @app.get("/api/v1/compare")
    def get_compare(
        request: Request, left: str = "", right: str = ""
    ) -> dict[str, Any]:
        """Concepts shared by two documents, and those kept by only one of them."""
        return compare(_project(request), left, right)

    @app.post("/api/ask")
    def post_ask_page(body: AskBody, request: Request) -> dict[str, Any]:
        """Same answer as ``/api/v1/ask``, used by the page."""
        return answer(_project(request), body.question)

    @app.post("/api/dashboards/pin")
    def post_pin(body: PinBody, request: Request) -> dict[str, Any]:
        """Remember or forget one proposed dashboard."""
        _require_idle(request)
        from auto_ontology.text_ontology.app.server import _view

        studio = request.app.state.studio
        project = _project(request)
        pinned = [item for item in project.pinned_dashboards if item != body.id]
        if body.pinned and body.id:
            pinned.append(body.id)
        project.pinned_dashboards = pinned
        studio.store.save(project, snapshot=False)
        return _view(studio)

    @app.get("/api/v1/learning")
    def get_learning(request: Request) -> dict[str, Any]:
        """Aliases, rejected facts and the quality curve. This is not model training."""
        project = _project(request)
        return {
            "aliases": [item.model_dump() for item in project.memory.aliases],
            "rejected": [item.model_dump() for item in project.memory.rejected],
            "scores": [item.model_dump() for item in project.memory.scores],
            "meaning": (
                "Les corrections sont réinjectées dans le prompt suivant. "
                "Aucun poids de modèle n'est modifié. Le fichier JSONL exporté "
                "peut servir plus tard à un entraînement, hors de cette application."
            ),
        }

    @app.get("/api/v1/schema")
    def get_schema(request: Request) -> dict[str, Any]:
        """Object types, properties, link types and the fixed interfaces."""
        project = _project(request)
        catalog = sync_schema(project)
        return {
            "version": catalog.version,
            "object_types": [item.model_dump() for item in catalog.object_types],
            "properties": [item.model_dump() for item in catalog.properties],
            "link_types": [item.model_dump() for item in catalog.link_types],
            "interfaces": interfaces_for(catalog),
            "actions": list(action_names()),
        }

    @app.post("/api/v1/objects/{type_name}/search")
    def search_objects(
        type_name: str, body: SearchBody, request: Request
    ) -> dict[str, Any]:
        """Instances of one type. ``where`` accepts eq, contains and and."""
        project = _project(request)
        rows = objects_of_type(project, type_name)
        query = compile_where(body.where)
        if query.get("q"):
            needle = query["q"].casefold()
            rows = [row for row in rows if needle in row["name"].casefold()]
        return page_rows(rows, body.pageToken)

    @app.get("/api/v1/objects/{type_name}/{object_id}")
    def get_object(type_name: str, object_id: str, request: Request) -> dict[str, Any]:
        """One instance, with the chain back to its passage."""
        project = _project(request)
        return {
            "type": type_name,
            "id": object_id,
            "lineage": lineage_for(project, object_id),
        }

    @app.get("/api/v1/objects/{type_name}/{object_id}/links/{link_type}")
    def get_links(
        type_name: str, object_id: str, link_type: str, request: Request
    ) -> dict[str, Any]:
        """Links of one type touching one instance."""
        project = _project(request)
        found = neighbours(project, object_id)
        outgoing = [
            item for item in found["outgoing"] if item["predicate"] == link_type
        ]
        incoming = [
            item for item in found["incoming"] if item["predicate"] == link_type
        ]
        return {
            "type": type_name,
            "id": object_id,
            "outgoing": outgoing,
            "incoming": incoming,
        }

    @app.get("/api/v1/object-sets")
    def get_sets(request: Request) -> dict[str, Any]:
        """Saved filters of the open project."""
        project = _project(request)
        return {"sets": [item.model_dump() for item in project.object_sets]}

    @app.post("/api/v1/object-sets")
    def post_set(body: SetBody, request: Request) -> dict[str, Any]:
        """Save a filter. It stores the definition, not a frozen list of ids."""
        _require_idle(request)
        studio, project = _studio(request)
        project.object_sets.append(
            ObjectSetDef(
                id=uuid.uuid4().hex[:12],
                name=body.name or "Ensemble",
                description=body.description,
                query=body.query,
                pinned_ids=body.pinned_ids,
            )
        )
        studio.store.save(project, snapshot=False)
        return {"sets": [item.model_dump() for item in project.object_sets]}

    @app.post("/api/v1/actions/{name}/preview")
    def preview(name: str, body: ActionBody, request: Request) -> dict[str, Any]:
        """Diff of an action. The project is not modified."""
        return preview_action(_project(request), name, _params(body))

    @app.post("/api/v1/actions/{name}/apply")
    def apply(name: str, body: ActionBody, request: Request) -> dict[str, Any]:
        """Apply an action. Remote callers need ONTOLOGY_API_ALLOW_WRITE=1."""
        _require_idle(request)
        host = request.client.host if request.client else ""
        if not write_allowed(host):
            raise HTTPException(
                status_code=403,
                detail="Cette API est en consultation. "
                "ONTOLOGY_API_ALLOW_WRITE=1 autorise l'écriture.",
            )
        studio, project = _studio(request)
        actor = request.headers.get("x-ontology-actor", "api")
        commit_action(studio.store, project, name, _params(body), actor=actor)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.get("/api/v1/lineage")
    def get_lineage(
        request: Request, name: str = "", document: str = ""
    ) -> dict[str, Any]:
        """Chain for one name, or every fact still coming from one document."""
        project = _project(request)
        if document:
            return {"document": document, "facts": facts_of_document(project, document)}
        return lineage_for(project, name)

    @app.post("/api/v1/around")
    def post_around(body: AroundBody, request: Request) -> dict[str, Any]:
        """Walk out from one name, with a depth, a direction and a node cap."""
        project = _project(request)
        links = [item for item in body.links.split(",") if item] if body.links else None
        return search_around(
            project,
            body.start,
            link_types=links,
            direction=body.direction or "both",
            depth=body.depth,
            target_type=body.target_type,
        )

    @app.get("/api/v1/similar")
    def get_similar(request: Request, q: str = "") -> dict[str, Any]:
        """Local trigram similarity. Candidates are never merged automatically."""
        project = _project(request)
        if q:
            return {"results": semantic_search(project, q), "auto_merge": False}
        return {"candidates": merge_candidates(project), "auto_merge": False}

    @app.get("/api/v1/brief")
    def get_brief(request: Request, since: str = "24h") -> dict[str, Any]:
        """What came in since *since* (24h, 7d, a date), and what to check."""
        from auto_ontology.text_ontology.daily import brief, parse_since
        from auto_ontology.text_ontology.inbox import read_journal

        try:
            moment = parse_since(since)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        studio, project = _studio(request)
        journal = read_journal(studio.store.project_dir(project.id), moment)
        result = brief(project, moment, journal)
        return {**result.as_dict(), "markdown": result.markdown()}

    @app.get("/api/v1/diff")
    def get_diff(request: Request, since: str = "7d") -> dict[str, Any]:
        """Classes, facts and attributes added or removed since *since*."""
        from auto_ontology.text_ontology.daily import diff, parse_since

        try:
            moment = parse_since(since)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        studio, project = _studio(request)
        result = diff(project, studio.store.project_dir(project.id), moment)
        return {**result.as_dict(), "markdown": result.markdown()}

    @app.get("/api/v1/rules")
    def get_rules(request: Request, include_retired: bool = False) -> dict[str, Any]:
        """Business rules and decisions the team certified, newest first."""
        project = _project(request)
        rules = [
            rule.model_dump()
            for rule in reversed(project.rules)
            if include_retired or rule.status == "certified"
        ]
        return {"rules": rules}

    @app.post("/api/v1/rules")
    def post_rule(body: RuleBody, request: Request) -> dict[str, Any]:
        """Certify a rule. The same text twice is recorded once."""
        from auto_ontology.text_ontology.agent_writes import WriteError, certify_rule

        _require_write(request)
        studio, project = _studio(request)
        try:
            return certify_rule(studio.store, project, body.model_dump(), actor="local")
        except WriteError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/v1/rules/{rule_id}")
    def delete_rule(rule_id: str, request: Request) -> dict[str, Any]:
        """Retire a rule: kept for the record, no longer applied. Undoable."""
        from auto_ontology.text_ontology.agent_writes import WriteError, retire_rule

        _require_write(request)
        studio, project = _studio(request)
        try:
            rule = retire_rule(studio.store, project, rule_id, actor="local")
        except WriteError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return rule.model_dump()

    @app.get("/api/v1/report/meeting")
    def get_meeting_report(
        request: Request, document: str | None = None
    ) -> dict[str, Any]:
        """One document's facts as a meeting summary skeleton, in Markdown."""
        from auto_ontology.text_ontology.reports import ReportError, meeting

        try:
            return meeting(_project(request), document).as_dict()
        except ReportError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/report/compare")
    def get_comparison_report(
        request: Request, names: Annotated[list[str], Query()]
    ) -> dict[str, Any]:
        """A table of what the project knows about two or more entities."""
        from auto_ontology.text_ontology.reports import ReportError, comparison

        try:
            return comparison(_project(request), names).as_dict()
        except ReportError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/tables")
    def get_tables(request: Request) -> dict[str, Any]:
        """Tables loaded from spreadsheets, and the views of the facts beside them."""
        from auto_ontology.text_ontology.bridge import FACT_VIEWS

        project = _project(request)
        return {
            "tables": [item.model_dump() for item in project.datasets],
            "views": [
                {"view": name, "columns": list(columns)}
                for name, columns in FACT_VIEWS.items()
            ],
        }

    @app.post("/api/v1/sql")
    def post_sql(body: SqlBody, request: Request) -> dict[str, Any]:
        """One read-only SELECT on the project's tables, capped and timed.

        The statement is checked, and the connection is read-only with no
        access to files or the network, whoever wrote the query.
        """
        from auto_ontology.text_ontology.bridge import run_bridge_sql
        from auto_ontology.text_ontology.tables import TableError

        studio, project = _studio(request)
        try:
            result = run_bridge_sql(
                studio.store.project_dir(project.id),
                project,
                body.sql,
                limit=body.limit,
            )
        except TableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.as_dict()

    @app.post("/api/v1/ask/data")
    def post_ask_data(body: QuestionBody, request: Request) -> dict[str, Any]:
        """A question on tables and facts: the model writes a checked SELECT.

        The query runs read-only, with the onto_* views of the facts beside
        the tables; the answer is phrased from the rows only, with sources.
        """
        from auto_ontology.text_ontology.app.server import _prepare_llm
        from auto_ontology.text_ontology.bridge import ask_data
        from auto_ontology.text_ontology.tables import TableError

        studio, project = _studio(request)
        _config, llm, _label = _prepare_llm(studio)
        try:
            answer = ask_data(
                project, studio.store.project_dir(project.id), body.text, llm
            )
        except TableError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return answer.as_dict()

    @app.get("/api/v1/branches")
    def get_branches(request: Request) -> dict[str, Any]:
        """Branch names and the one currently open; none before a first project."""
        from auto_ontology.text_ontology.app.server import _open_project

        if _open_project(request.app.state.studio) is None:
            # The page asks on first launch: an empty studio is not an error.
            return {"active": "main", "branches": []}
        studio, project = _studio(request)
        return {
            "active": active_branch(studio.store, project.id),
            "branches": list_branches(studio.store, project.id),
        }

    @app.post("/api/v1/branches")
    def post_branch(body: BranchBody, request: Request) -> dict[str, Any]:
        """Copy the project into a new branch. Main is left as it is."""
        _require_idle(request)
        studio, project = _studio(request)
        create_branch(studio.store, project, body.name)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.post("/api/v1/branches/{name}/diff")
    def post_diff(name: str, request: Request) -> dict[str, Any]:
        """Facts present on the working copy and not on *name*, and the reverse."""
        studio, project = _studio(request)
        other = read_branch(studio.store, project.id, name)
        return diff_projects(other, project)

    @app.post("/api/v1/branches/{name}/checkout")
    def post_checkout(name: str, request: Request) -> dict[str, Any]:
        """Switch the working copy to *name*."""
        _require_idle(request)
        studio, project = _studio(request)
        checkout(studio.store, project.id, name)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.post("/api/v1/branches/merge")
    def post_merge(request: Request) -> dict[str, Any]:
        """Union the open branch into main."""
        _require_idle(request)
        studio, project = _studio(request)
        merge_branch(studio.store, project.id)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.post("/api/v1/branches/discard")
    def post_discard(request: Request) -> dict[str, Any]:
        """Drop the open side branch and reload main."""
        _require_idle(request)
        studio, project = _studio(request)
        discard_branch(studio.store, project.id)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.get("/api/v1/sdk")
    def get_sdk(request: Request) -> Response:
        """The generated Python client for the current schema."""
        project = _project(request)
        sync_schema(project)
        return Response(
            content=render_sdk(project), media_type="text/x-python; charset=utf-8"
        )

    @app.post("/api/v1/notes")
    def post_note(body: NoteBody, request: Request) -> dict[str, Any]:
        """A dashed remark. It is not exported as a sourced fact."""
        _require_idle(request)
        studio, project = _studio(request)
        project.notes.append(
            NoteLink(
                id=uuid.uuid4().hex[:8],
                source=body.source,
                target=body.target,
                label=body.label or "note",
            )
        )
        studio.store.save(project, snapshot=False)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.post("/api/v1/questions")
    def post_question(body: QuestionBody, request: Request) -> dict[str, Any]:
        """Save a competency question. It is not answered by a new extraction."""
        _require_write(request)
        studio, project = _studio(request)
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="La question est vide.")
        from auto_ontology.text_ontology.studio_models import CompetencyQuestion

        project.questions.append(CompetencyQuestion(id=uuid.uuid4().hex[:8], text=text))
        studio.store.save(project, snapshot=False)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.delete("/api/v1/questions/{question_id}")
    def delete_question(question_id: str, request: Request) -> dict[str, Any]:
        """Drop one competency question."""
        _require_write(request)
        studio, project = _studio(request)
        project.questions = [
            item for item in project.questions if item.id != question_id
        ]
        studio.store.save(project, snapshot=False)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.post("/api/v1/mappings")
    def post_mapping(body: MappingBody, request: Request) -> dict[str, Any]:
        """Remember a vocabulary link. It does not rewrite the class."""
        _require_write(request)
        studio, project = _studio(request)
        from auto_ontology.text_ontology.studio_models import VocabularyMapping

        project.mappings = [
            item
            for item in project.mappings
            if not (item.source == body.source and item.iri == body.iri)
        ]
        project.mappings.append(
            VocabularyMapping(
                source=body.source,
                iri=body.iri,
                predicate=body.predicate or "owl:equivalentClass",
                accepted=True,
            )
        )
        studio.store.save(project, snapshot=False)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.put("/api/v1/base-iri")
    def put_base(body: BaseIriBody, request: Request) -> dict[str, Any]:
        """Set the namespace used by Turtle and JSON-LD exports."""
        _require_write(request)
        studio, project = _studio(request)
        project.base_iri = body.base_iri.strip()
        studio.store.save(project, snapshot=False)
        from auto_ontology.text_ontology.app.server import _view

        return _view(studio)

    @app.get("/api/tester")
    def tester() -> Response:
        """A small page that calls the typed search without leaving the app."""
        page = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Essai de l'API</title>
<link rel="stylesheet" href="/assets/app.css">
</head><body class="tester">
<main class="tester-card">
<h1>Essai de l'API</h1>
<p class="muted">Recherche typée sur le projet ouvert. L'écriture distante reste coupée sans ONTOLOGY_API_ALLOW_WRITE.</p>
<form id="f" class="stack">
<label>Type <input name="type" value="Personne"></label>
<label>Contient <input name="q" placeholder="Nom ou fragment"></label>
<button class="primary" type="submit">Chercher</button>
</form>
<pre id="out" class="tester-out">Le résultat s'affiche ici.</pre>
</main>
<script>
(function(){
var theme=localStorage.getItem("ontology.theme");
if(theme==="dark") document.documentElement.setAttribute("data-theme","dark");
document.getElementById("f").onsubmit=async function(e){e.preventDefault();
const type=e.target.type.value, q=e.target.q.value;
const body={where:q?{contains:{field:"name",value:q}}:{}};
const r=await fetch("/api/v1/objects/"+encodeURIComponent(type)+"/search",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
document.getElementById("out").textContent=await r.text();};
})();
</script></body></html>"""
        return Response(content=page, media_type="text/html; charset=utf-8")

    @app.get("/api/v1/explore")
    def get_explore(
        request: Request, q: str = "", type: str = "", document: str = ""
    ) -> dict[str, Any]:
        """The same facet search the Explorer view uses."""
        from auto_ontology.text_ontology.view import build_view

        studio, project = _studio(request)
        view = build_view(
            project, path="", can_undo=False, can_redo=False, llm={}, projects=[]
        )
        nodes = view["graph"]["nodes"] if isinstance(view.get("graph"), dict) else []
        from auto_ontology.text_ontology.explore import rows_from_project

        rows = rows_from_project(project, nodes if isinstance(nodes, list) else [])
        matched = search_rows(rows, {"q": q, "type": type, "document": document})
        return {"total": len(matched), "rows": matched[:50]}


def _params(body: ActionBody) -> dict[str, str]:
    return {
        key: str(value) for key, value in body.model_dump().items() if value is not None
    }


def _studio(request: Request) -> tuple[Any, Any]:
    return request.app.state.studio, _project(request)


def _require_idle(request: Request) -> None:
    """Refuse a write while an extraction runs: its final save would erase it."""
    from auto_ontology.text_ontology.app.server import _ensure_idle

    _ensure_idle(request.app.state.studio)


def _project(request: Request) -> Any:
    from auto_ontology.text_ontology.app.server import _open_project
    from auto_ontology.text_ontology.mutations import EditError

    project = _open_project(request.app.state.studio)
    if project is None:
        raise EditError("Aucun projet. Déposez un document ou ouvrez l'exemple.")
    return project
