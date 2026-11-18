# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the studio's protections and for its use of local models."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import llm_settings
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.branches import _read_named
from auto_ontology.text_ontology.documents import DocumentReadError, load_bytes
from auto_ontology.text_ontology.extractor import extract_text_ontology
from auto_ontology.text_ontology.local_llm import LocalChatModel
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.sdkgen import render_sdk
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.studio_models import ObjectTypeDef

_STUDIO = "http://127.0.0.1:4173"


def _client(tmp_path: Path, base_url: str = _STUDIO) -> TestClient:
    return TestClient(create_app(home=tmp_path, fake=True), base_url=base_url)


# --- The local server only serves the person running it ---------------------


def test_a_foreign_host_name_is_refused(tmp_path: Path) -> None:
    """DNS rebinding: a hostile domain that resolves to 127.0.0.1."""
    response = _client(tmp_path, "http://attacker.example:4173").get("/api/state")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden_host"


@pytest.mark.parametrize("base_url", [_STUDIO, "http://localhost:4173"])
def test_loopback_names_are_served(tmp_path: Path, base_url: str) -> None:
    assert _client(tmp_path, base_url).get("/api/health").status_code == 200


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("[::1]:4173", "::1"),
        ("127.0.0.1:4173", "127.0.0.1"),
        ("localhost", "localhost"),
    ],
)
def test_host_headers_are_read_with_or_without_a_port(header: str, name: str) -> None:
    from auto_ontology.text_ontology.app.guard import _host_name

    assert _host_name(header) == name


def test_a_write_from_another_site_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)

    by_origin = client.put(
        "/api/settings",
        json={"endpoint": "https://attacker.example/v1"},
        headers={"Origin": "https://attacker.example"},
    )
    by_fetch_site = client.post("/api/sample", headers={"Sec-Fetch-Site": "cross-site"})
    by_null_origin = client.post("/api/sample", headers={"Origin": "null"})

    assert [
        by_origin.status_code,
        by_fetch_site.status_code,
        by_null_origin.status_code,
    ] == [
        403,
        403,
        403,
    ]
    assert (
        client.get("/api/settings").json().get("endpoint")
        != "https://attacker.example/v1"
    )


def test_the_studio_page_and_tools_without_an_origin_may_write(tmp_path: Path) -> None:
    client = _client(tmp_path)

    from_page = client.post("/api/sample", headers={"Origin": _STUDIO})
    from_curl = client.post("/api/sample")

    assert from_page.status_code == 200
    assert from_curl.status_code == 200


def test_extra_hosts_can_be_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONTOLOGY_ALLOWED_HOSTS", "mac-studio.local")

    assert (
        _client(tmp_path, "http://mac-studio.local:4173").get("/api/health").status_code
        == 200
    )


def test_an_oversized_upload_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONTOLOGY_MAX_UPLOAD_MB", "1")
    client = _client(tmp_path)

    response = client.post(
        "/api/ingest",
        files={"file": ("gros.txt", b"a" * (2 * 1024 * 1024), "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"] == "too_large"


# --- Files and names from outside --------------------------------------------


def _zip(name: str, size: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, b"\0" * size)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "member"),
    [("livre.epub", "ch1.xhtml"), ("note.docx", "word/document.xml")],
)
def test_an_archive_that_expands_abnormally_is_not_opened(
    filename: str, member: str
) -> None:
    bomb = _zip(member, 20 * 1024 * 1024)  # 20 MB of zeros, a few KB compressed
    assert len(bomb) < 100 * 1024

    with pytest.raises(DocumentReadError, match="anormal"):
        load_bytes(filename, bomb)


def test_project_ids_and_branch_names_never_leave_the_projects_folder(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Essai")

    for bad in ("..", "a/b", "a.b", ""):
        with pytest.raises(FileNotFoundError):
            store.project_dir(bad)
    with pytest.raises(FileNotFoundError):
        _read_named(store, project.id, "..")
    assert store.project_dir(project.id).is_dir()


def test_the_generated_sdk_compiles_whatever_the_class_names(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Essai")
    project.catalog.object_types = [
        ObjectTypeDef(id=name, label=name)
        for name in ("None", "class", "A-B", "A_B", "Ville de Paris", "2Roues")
    ]

    source = render_sdk(project)

    compile(source, "client.py", "exec")
    for method in (
        "def None_(",
        "def class_(",
        "def A_B(",
        "def A_B_2(",
        "def T_2Roues(",
    ):
        assert method in source
    assert 'quote(self.type_name, safe="")' in source


# --- The studio and local models ---------------------------------------------


_LLM_ENV = (
    "ONTOLOGY_LLM_API_KEY",
    "ONTOLOGY_LLM_ENDPOINT",
    "ONTOLOGY_LLM_MODEL",
    "REASONING_API_KEY",
    "REASONING_ENDPOINT",
    "REASONING_MODEL",
    "DEFAULT_MODELS_API_KEY",
    "DEFAULT_MODELS_ENDPOINT",
    "DEFAULT_MODELS_MODEL",
    "NVIDIA_API_KEY",
    "BASE_URL",
    "MODEL_NAME",
)


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_a_local_endpoint_needs_no_key_and_no_model(
    tmp_path: Path, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.setenv("REASONING_ENDPOINT", "http://127.0.0.1:1234/v1")
    clean_llm_env.setattr(llm_settings, "detect_model", lambda url, key: "qwen3-8b")

    config = llm_settings.resolve_llm_config(ProjectStore(tmp_path))
    llm = llm_settings.build_llm(config)

    assert config.configured and config.local and config.model == ""
    assert isinstance(llm, LocalChatModel)
    assert llm.model == "qwen3-8b"
    assert llm_settings.model_label(llm, config) == "qwen3-8b"
    assert llm_settings.public_llm(config, demo=False)["auto_model"] is True


def test_a_local_server_without_a_loaded_model_says_so(
    tmp_path: Path, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.setenv("REASONING_ENDPOINT", "http://127.0.0.1:1234/v1")

    def nothing_loaded(url: str, key: str) -> str:
        raise ValueError("no chat model")

    clean_llm_env.setattr(llm_settings, "detect_model", nothing_loaded)
    config = llm_settings.resolve_llm_config(ProjectStore(tmp_path))

    with pytest.raises(EnvironmentError, match="Aucun modèle"):
        llm_settings.build_llm(config)


def test_a_hosted_endpoint_still_gets_its_default_model(
    tmp_path: Path, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.setenv("REASONING_API_KEY", "nvapi-test")

    config = llm_settings.resolve_llm_config(ProjectStore(tmp_path))

    assert not config.local
    assert config.model == llm_settings.NVIDIA_MODEL


def test_a_backend_passed_as_llm_is_used_directly() -> None:
    calls: list[str] = []

    class Backend:
        notes: list[str] = []
        description = "local"

        def __call__(self, system: str, user: str) -> TextOntology:
            calls.append(user)
            return TextOntology()

    extract_text_ontology("Un texte.", llm=Backend())  # type: ignore[arg-type]

    assert len(calls) == 1


def test_the_watcher_builds_test_models_like_the_server(tmp_path: Path) -> None:
    from auto_ontology.text_ontology import watch

    seen: list[Any] = []

    class Studio:
        store = ProjectStore(tmp_path)
        fake = False

        @staticmethod
        def llm_factory(config: Any) -> Any:
            seen.append(config)
            from auto_ontology.text_ontology.sample import FakeLLM

            return FakeLLM()

    document = tmp_path / "note.txt"
    document.write_text("Alice travaille pour ACME.", encoding="utf-8")

    watch._ingest_path(Studio(), document)

    assert len(seen) == 1


def test_the_watcher_waits_while_the_page_extracts(tmp_path: Path) -> None:
    import threading

    from auto_ontology.text_ontology import watch

    class Busy:
        store = ProjectStore(tmp_path)
        lock = threading.Lock()
        running = True

    document = tmp_path / "note.txt"
    document.write_text("Alice travaille pour ACME.", encoding="utf-8")
    seen: set[tuple[str, int]] = set()
    Busy.store.save_settings(
        Busy.store.settings().model_copy(update={"watch_dir": str(tmp_path)})
    )

    watch._scan(Busy(), seen)

    assert seen == set()  # not marked: it is tried again on the next pass


def test_an_empty_studio_lists_no_branches_without_an_error(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/v1/branches")

    assert response.status_code == 200
    assert response.json() == {"active": "main", "branches": []}


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/documents/x/genre", {"genre": "paper"}),
        ("/api/dashboards/pin", {"id": "x", "pinned": True}),
        ("/api/v1/object-sets", {"name": "s", "type_name": "Personne"}),
        ("/api/v1/actions/rename/apply", {"params": {}}),
        ("/api/v1/branches", {"name": "essai"}),
        ("/api/v1/branches/essai/checkout", None),
        ("/api/v1/branches/merge", None),
        ("/api/v1/branches/discard", None),
        ("/api/v1/notes", {"source": "a", "target": "b", "label": "n"}),
        ("/api/v1/questions", {"text": "Qui dirige la bibliothèque ?"}),
        ("/api/v1/mappings", {"class_name": "Personne", "target": "foaf:Person"}),
    ],
)
def test_api_writes_wait_for_a_running_extraction(
    tmp_path: Path, path: str, body: dict[str, Any] | None
) -> None:
    """The extraction's final save would erase a change made meanwhile."""
    client = _client(tmp_path)
    assert client.post("/api/sample").status_code == 200
    client.app.state.studio.running = True  # type: ignore[attr-defined]

    response = client.post(path, json=body) if body is not None else client.post(path)

    assert response.status_code == 409, response.text
    assert response.json()["error"] == "busy"
    # Reads still work while the extraction runs.
    assert client.get("/api/v1/concepts").status_code == 200
