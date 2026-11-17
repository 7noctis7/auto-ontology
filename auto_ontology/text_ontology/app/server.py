# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local studio: one process, no database, no login.

``ontology serve`` builds this app and opens it in the browser. The page,
the graph library and the exports are served from this package.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auto_ontology.text_ontology.api import install_api
from auto_ontology.text_ontology.documents import (
    DocumentReadError,
    load_bytes,
    load_text,
)
from auto_ontology.text_ontology.llm_settings import (
    NO_KEY_MESSAGE,
    build_llm,
    public_llm,
    resolve_llm_config,
    test_connection,
)
from auto_ontology.text_ontology.learning import remember_edit
from auto_ontology.text_ontology.mutations import EditError, apply_edit
from auto_ontology.text_ontology.pipeline import (
    IngestError,
    ingest_document,
    load_sample,
)
from auto_ontology.text_ontology.sample import FakeLLM
from auto_ontology.text_ontology.store import ProjectStore, default_home
from auto_ontology.text_ontology.studio_export import render_export
from auto_ontology.text_ontology.studio_models import Edit, Project, StudioSettings
from auto_ontology.text_ontology.view import build_view

_STATIC = Path(__file__).resolve().parent / "static"

_EMPTY_STATS: dict[str, Any] = {
    "concepts": 0,
    "relations": 0,
    "facts": 0,
    "documents": 0,
    "orphans": 0,
    "orphan_ratio": 0,
    "failed_chunks": 0,
    "top_classes": [],
    "top_predicates": [],
    "per_document": [],
    "last_document": None,
    "insight_classes": [],
}


class Job:
    """One extraction, with the events the page replays over SSE."""

    def __init__(self, project_id: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.project_id = project_id
        self.events: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.finished = False
        self.cancel = threading.Event()

    def push(self, event: dict[str, Any]) -> None:
        with self.condition:
            self.events.append(event)
            if event.get("type") in {"done", "error", "duplicate"}:
                self.finished = True
            self.condition.notify_all()


class Studio:
    """Process-wide handles: files, the running job, the optional fake model."""

    def __init__(
        self,
        home: Path,
        *,
        llm_factory: Any = None,
        fake: bool = False,
    ) -> None:
        self.store = ProjectStore(home)
        self.llm_factory = llm_factory
        self.fake = fake
        self.lock = threading.Lock()
        self.running = False
        self.jobs: dict[str, Job] = {}


class SettingsBody(BaseModel):
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: int | None = Field(default=None, gt=0, le=3600)
    max_tokens: int | None = Field(default=None, gt=0, le=128_000)
    chunk_chars: int | None = Field(default=None, gt=200, le=100_000)
    watch_dir: str | None = None
    clear_api_key: bool = False


class NameBody(BaseModel):
    name: str = ""


class ProjectBody(BaseModel):
    name: str = ""


def create_app(
    home: Path | None = None,
    *,
    llm_factory: Any = None,
    fake: bool = False,
) -> FastAPI:
    """The studio ASGI app. It does not touch Postgres or the chat workers."""
    studio = Studio(home or default_home(), llm_factory=llm_factory, fake=fake)
    app = FastAPI(title="Ontologie", version="1")
    app.state.studio = studio

    @app.exception_handler(IngestError)
    def _ingest_error(_request: Request, exc: IngestError) -> JSONResponse:
        status = 409 if exc.code in {"llm_not_configured", "busy"} else 422
        return JSONResponse(
            status_code=status, content={"error": exc.code, "message": str(exc)}
        )

    @app.exception_handler(DocumentReadError)
    def _read_error(_request: Request, exc: DocumentReadError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"error": "unreadable", "message": str(exc)}
        )

    @app.exception_handler(EditError)
    def _edit_error(_request: Request, exc: EditError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"error": "edit", "message": str(exc)}
        )

    @app.exception_handler(FileNotFoundError)
    def _missing(_request: Request, _exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "missing", "message": "Projet introuvable."},
        )

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return _view(studio)

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return public_llm(resolve_llm_config(studio.store), demo=studio.fake)

    @app.put("/api/settings")
    def put_settings(body: SettingsBody) -> dict[str, Any]:
        saved = studio.store.settings()
        _apply_settings(saved, body)
        studio.store.save_settings(saved)
        return public_llm(resolve_llm_config(studio.store), demo=studio.fake)

    @app.post("/api/settings/test")
    def post_test() -> dict[str, Any]:
        return test_connection(resolve_llm_config(studio.store))

    @app.post("/api/projects")
    def post_project(body: ProjectBody) -> dict[str, Any]:
        project = studio.store.create(body.name or "Brouillon")
        _remember(studio, project.id)
        return _view(studio)

    @app.post("/api/projects/{project_id}/open")
    def open_project(project_id: str) -> dict[str, Any]:
        studio.store.load(project_id)
        _remember(studio, project_id)
        return _view(studio)

    @app.patch("/api/project")
    def rename_project(body: NameBody) -> dict[str, Any]:
        project = _require_project(studio)
        cleaned = body.name.strip()
        if cleaned:
            project.name = cleaned
            studio.store.save(project, snapshot=False)
        return _view(studio)

    @app.post("/api/sample")
    def post_sample() -> dict[str, Any]:
        _ensure_idle(studio)
        project = _ensure_project(studio, "Exemple")
        load_sample(studio.store, project)
        return _view(studio)

    @app.post("/api/edits")
    def post_edit(body: Edit) -> dict[str, Any]:
        _ensure_idle(studio)
        project = _require_project(studio)
        studio.store.save(project, snapshot=True)
        apply_edit(project, body)
        remember_edit(studio.store, project, body)
        studio.store.save(project, snapshot=False)
        return _view(studio)

    @app.post("/api/undo")
    def post_undo() -> dict[str, Any]:
        _ensure_idle(studio)
        project = _require_project(studio)
        try:
            studio.store.undo(project.id)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        return _view(studio)

    @app.post("/api/redo")
    def post_redo() -> dict[str, Any]:
        _ensure_idle(studio)
        project = _require_project(studio)
        try:
            studio.store.redo(project.id)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        return _view(studio)

    @app.post("/api/ingest")
    async def post_ingest(request: Request) -> dict[str, Any]:
        loaded, force, sync = await _read_ingest(request)
        config, llm, label = _prepare_llm(studio)
        project = _ensure_project(studio, Path(loaded.filename).stem or "Brouillon")
        if sync:
            _begin(studio)
            try:
                ingest_document(
                    studio.store,
                    project,
                    loaded,
                    config=config,
                    llm=llm,
                    model_label=label,
                    force=force,
                    cancel_event=None,
                    on_event=lambda _event: None,
                )
            finally:
                _end(studio)
            view = _view(studio)
            view["notice"] = _last_notice(studio, project.id)
            return view
        _begin(studio)
        job = Job(project.id)
        studio.jobs[job.id] = job

        def run() -> None:
            try:
                ingest_document(
                    studio.store,
                    project,
                    loaded,
                    config=config,
                    llm=llm,
                    model_label=label,
                    force=force,
                    cancel_event=job.cancel,
                    on_event=job.push,
                )
            except Exception as exc:  # noqa: BLE001 - the page must hear every failure
                code = exc.code if isinstance(exc, IngestError) else "failed"
                job.push({"type": "error", "error": code, "message": str(exc)})
            finally:
                _end(studio)

        threading.Thread(target=run, name=f"ontology-{job.id}", daemon=True).start()
        return {"job_id": job.id, "project_id": project.id}

    @app.get("/api/jobs/{job_id}", response_model=None)
    def get_job(job_id: str) -> JSONResponse | dict[str, Any]:
        job = studio.jobs.get(job_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"error": "missing", "message": "Extraction introuvable."},
            )
        return {"id": job.id, "finished": job.finished, "events": job.events}

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> Response:
        job = studio.jobs.get(job_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"error": "missing", "message": "Extraction introuvable."},
            )
        return StreamingResponse(
            _stream(job),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/jobs/{job_id}/cancel", response_model=None)
    def cancel_job(job_id: str) -> JSONResponse | dict[str, bool]:
        job = studio.jobs.get(job_id)
        if job is None:
            return JSONResponse(
                status_code=404,
                content={"error": "missing", "message": "Extraction introuvable."},
            )
        job.cancel.set()
        return {"ok": True}

    @app.get("/api/export")
    def export(format: str = "html") -> Response:
        project = _require_project(studio)
        try:
            body, filename, media = render_export(project, format)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        return Response(
            content=body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    app.mount("/assets", StaticFiles(directory=_STATIC), name="assets")
    install_api(app)
    return app


def _remember_edit(studio: Studio, project: Project, edit: Edit) -> None:
    """Keep the correction for the next extraction."""
    remember_edit(studio.store, project, edit)


def _apply_settings(saved: StudioSettings, body: SettingsBody) -> None:
    if body.endpoint is not None:
        saved.endpoint = body.endpoint.strip()
    if body.model is not None:
        saved.model = body.model.strip()
    if body.timeout_s is not None:
        saved.timeout_s = body.timeout_s
    if body.max_tokens is not None:
        saved.max_tokens = body.max_tokens
    if body.chunk_chars is not None:
        saved.chunk_chars = body.chunk_chars
    if body.watch_dir is not None:
        saved.watch_dir = body.watch_dir.strip()
    if body.clear_api_key:
        saved.api_key = ""
    elif body.api_key:
        saved.api_key = body.api_key.strip()


async def _read_ingest(request: Request) -> tuple[Any, bool, bool]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        text = str(body.get("text") or "")
        filename = str(body.get("filename") or "colle.txt")
        if not text.strip():
            raise IngestError("empty_document", "Collez un texte à extraire.")
        return (
            load_text(filename, text),
            bool(body.get("force")),
            bool(body.get("sync")),
        )
    form = await request.form()
    force = str(form.get("force") or "").lower() in {"1", "true", "on"}
    sync = str(form.get("sync") or "").lower() in {"1", "true", "on"}
    upload = form.get("file")
    text = str(form.get("text") or "")
    filename = str(form.get("filename") or "")
    if upload is not None and hasattr(upload, "read"):
        data = await upload.read()
        name = filename or getattr(upload, "filename", "") or "document"
        return load_bytes(str(name), data), force, sync
    if text.strip():
        return load_text(filename or "colle.txt", text), force, sync
    raise IngestError("empty_document", "Déposez un fichier ou collez du texte.")


def _prepare_llm(studio: Studio) -> tuple[Any, Any, str]:
    config = resolve_llm_config(studio.store)
    if studio.llm_factory is not None:
        return config, studio.llm_factory(config), _label(studio, config)
    if studio.fake:
        return config, FakeLLM(), "démonstration"
    if not config.configured:
        raise IngestError("llm_not_configured", NO_KEY_MESSAGE)
    return config, build_llm(config), config.model


def _label(studio: Studio, config: Any) -> str:
    if studio.fake or studio.llm_factory is not None and not config.configured:
        return "démonstration"
    return config.model or "démonstration"


def _remember(studio: Studio, project_id: str) -> None:
    settings = studio.store.settings()
    settings.last_project_id = project_id
    studio.store.save_settings(settings)


def _open_project(studio: Studio) -> Project | None:
    settings = studio.store.settings()
    if settings.last_project_id:
        try:
            return studio.store.load(settings.last_project_id)
        except (FileNotFoundError, ValueError):
            pass
    projects = studio.store.list_projects()
    if not projects:
        return None
    _remember(studio, projects[0].id)
    return projects[0]


def _ensure_project(studio: Studio, name: str) -> Project:
    project = _open_project(studio)
    if project is not None:
        return project
    project = studio.store.create(name)
    _remember(studio, project.id)
    return project


def _require_project(studio: Studio) -> Project:
    project = _open_project(studio)
    if project is None:
        raise EditError("Aucun projet. Déposez un document ou ouvrez l'exemple.")
    return project


def _ensure_idle(studio: Studio) -> None:
    with studio.lock:
        if studio.running:
            raise IngestError("busy", "Une extraction est déjà en cours.")


def _begin(studio: Studio) -> None:
    with studio.lock:
        if studio.running:
            raise IngestError("busy", "Une extraction est déjà en cours.")
        studio.running = True


def _end(studio: Studio) -> None:
    with studio.lock:
        studio.running = False


def _projects(studio: Studio) -> list[dict[str, Any]]:
    return [
        {
            "id": project.id,
            "name": project.name,
            "updated_at": project.updated_at,
            "documents": len(project.documents),
        }
        for project in studio.store.list_projects()
    ]


def _view(studio: Studio) -> dict[str, Any]:
    config = resolve_llm_config(studio.store)
    llm = public_llm(config, demo=studio.fake or studio.llm_factory is not None)
    llm["watch_dir"] = studio.store.settings().watch_dir
    project = _open_project(studio)
    projects = _projects(studio)
    if project is None:
        return {
            "project": None,
            "projects": projects,
            "undo": {"can_undo": False, "can_redo": False},
            "llm": llm,
            "stats": dict(_EMPTY_STATS),
            "graph": {"nodes": [], "edges": []},
            "glossary": [],
            "facts": [],
            "documents": [],
            "suggestions": [],
        }
    return build_view(
        project,
        path=str(studio.store.project_dir(project.id) / "project.json"),
        can_undo=studio.store.can_undo(project.id),
        can_redo=studio.store.can_redo(project.id),
        llm=llm,
        projects=projects,
    )


def _last_notice(studio: Studio, project_id: str) -> str:
    """Unused hook kept so a sync ingest can grow a notice later."""
    return ""


def _sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {event.get('type', 'message')}\ndata: {payload}\n\n"


def _stream(job: Job) -> Any:
    index = 0
    while True:
        with job.condition:
            while index >= len(job.events) and not job.finished:
                job.condition.wait(timeout=15)
            if index >= len(job.events):
                return
            event = job.events[index]
            index += 1
        yield _sse(event)
        if event.get("type") in {"done", "error", "duplicate"}:
            return
