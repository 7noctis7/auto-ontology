# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HTTP API of the studio, documented by the OpenAPI page at ``/docs``.

The same functions back the page. A token is required only for clients that
are not on this machine, and only when ``ONTOLOGY_API_TOKEN`` is set.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from auto_ontology.text_ontology.query import (
    answer,
    compare,
    concepts,
    list_facts,
    neighbours,
    paths,
    search,
)
from auto_ontology.text_ontology.studio_export import render_export
from auto_ontology.text_ontology.studio_models import Edit

_LOCAL = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


class AskBody(BaseModel):
    question: str = ""


class PinBody(BaseModel):
    id: str = ""
    pinned: bool = True


class GenreBody(BaseModel):
    genre: str = ""
    domain: str = ""


def access_allowed(client_host: str, authorization: str, token: str) -> bool:
    """Local clients are always allowed. A remote client needs the token if one is set."""
    if client_host in _LOCAL or not token:
        return True
    return authorization == f"Bearer {token}"


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


def _project(request: Request) -> Any:
    from auto_ontology.text_ontology.app.server import _open_project
    from auto_ontology.text_ontology.mutations import EditError

    project = _open_project(request.app.state.studio)
    if project is None:
        raise EditError("Aucun projet. Déposez un document ou ouvrez l'exemple.")
    return project
