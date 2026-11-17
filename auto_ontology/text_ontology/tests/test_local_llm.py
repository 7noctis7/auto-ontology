# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for extraction through a local OpenAI-compatible server (LM Studio)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from auto_ontology.text_ontology import extractor
from auto_ontology.text_ontology.local_llm import (
    LocalChatModel,
    detect_model,
    is_local_endpoint,
    parse_json_object,
)

_ANSWER = {
    "classes": [{"name": "Bloc", "parent": None, "description": "Unité de la chaîne"}],
    "triplets": [
        {
            "subject": "Bloc 1",
            "subject_type": "Bloc",
            "predicate": "contient",
            "object": "Transaction 1",
            "object_type": "Transaction",
        }
    ],
    "attributes": [],
}

Responder = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]


class _FakeServer:
    """An OpenAI-compatible server whose answers each test scripts."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.responder: Responder = lambda path, body: (404, {})
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _reply(self, body: dict[str, Any] | None) -> None:
                server.requests.append((self.path, body or {}))
                status, payload = server.responder(self.path, body or {})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._reply(None)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                self._reply(json.loads(self.rfile.read(length) or b"{}"))

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}/v1"
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    @property
    def chat_requests(self) -> list[dict[str, Any]]:
        return [b for path, b in self.requests if path.endswith("/chat/completions")]


@pytest.fixture
def server() -> Iterator[_FakeServer]:
    fake = _FakeServer()
    yield fake
    fake.close()


def _completion(
    content: str, finish_reason: str = "stop"
) -> tuple[int, dict[str, Any]]:
    return 200, {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }


def _bad_request(message: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": {"message": message, "type": "invalid_request_error"}}


def _model(server: _FakeServer) -> LocalChatModel:
    return LocalChatModel(base_url=server.base_url, model="m", timeout=5)


# --- Reading JSON out of an answer ------------------------------------------


def test_json_is_read_through_reasoning_fences_and_trailing_commas() -> None:
    answer = (
        "<think>Je dois lister les classes {pas du JSON}.</think>\n"
        "Voici l'ontologie :\n```json\n"
        '{"classes": [{"name": "Bloc", "parent": null, "description": "x",},],}\n'
        "```\nBonne journée."
    )

    value, salvaged = parse_json_object(answer)

    assert value["classes"][0]["name"] == "Bloc"
    assert salvaged is False


def test_a_reasoning_block_without_its_opening_tag_is_dropped() -> None:
    value, _ = parse_json_object('réflexion {"a": 1}</think>{"classes": []}')

    assert value == {"classes": []}


def test_an_answer_cut_mid_item_keeps_its_complete_items() -> None:
    cut = json.dumps(_ANSWER)[:-60]

    value, salvaged = parse_json_object(cut)

    assert salvaged is True
    assert value["classes"] == _ANSWER["classes"]


def test_no_json_at_all_is_an_error() -> None:
    with pytest.raises(ValueError):
        parse_json_object("Je ne peux pas répondre.")


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:1234/v1", True),
        ("http://localhost:11434/v1", True),
        ("http://192.168.1.20:1234/v1", True),
        ("http://mac-studio.local:1234/v1", True),
        ("https://integrate.api.nvidia.com/v1", False),
        ("https://inference-api.nvidia.com/v1", False),
    ],
)
def test_local_endpoints_are_recognized(url: str, local: bool) -> None:
    assert is_local_endpoint(url) is local


# --- Talking to the server ---------------------------------------------------


def test_the_schema_is_sent_when_the_server_accepts_it(server: _FakeServer) -> None:
    server.responder = lambda path, body: _completion(json.dumps(_ANSWER))

    result = _model(server)("système", "texte")

    assert result is not None and result.classes[0].name == "Bloc"
    request = server.chat_requests[0]
    assert request["response_format"]["type"] == "json_schema"
    assert request["messages"][0] == {"role": "system", "content": "système"}
    assert request["temperature"] == 0


def test_a_refused_schema_falls_back_to_plain_json_and_stays_there(
    server: _FakeServer,
) -> None:
    def responder(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if "response_format" in body:
            return _bad_request("response_format is not supported")
        return _completion("```json\n" + json.dumps(_ANSWER) + "\n```")

    server.responder = responder
    model = _model(server)

    assert model("s", "chunk 1") is not None
    assert model("s", "chunk 2") is not None
    assert model.strategy == "plain JSON"
    # One refused request, then two plain ones: the fallback is remembered.
    assert ["response_format" in r for r in server.chat_requests] == [
        True,
        False,
        False,
    ]


def test_a_template_without_a_system_role_gets_the_prompt_in_the_user_turn(
    server: _FakeServer,
) -> None:
    def responder(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if any(m["role"] == "system" for m in body["messages"]):
            return _bad_request("System role not supported")
        return _completion(json.dumps(_ANSWER))

    server.responder = responder

    model = _model(server)
    assert model("règles", "texte") is not None
    assert model.strategy == "plain JSON, no system role"
    last = server.chat_requests[-1]["messages"]
    assert last == [{"role": "user", "content": "règles\n\ntexte"}]


def test_an_unreadable_answer_is_sent_back_once_for_repair(server: _FakeServer) -> None:
    answers = iter(
        [
            _completion("Désolé, voici les classes : Bloc."),
            _completion(json.dumps(_ANSWER)),
        ]
    )
    server.responder = lambda path, body: next(answers)

    result = _model(server)("s", "texte")

    assert result is not None
    repair = server.chat_requests[1]["messages"]
    assert repair[-2]["role"] == "assistant"
    assert "JSON" in repair[-1]["content"]


def test_an_answer_cut_at_the_token_limit_is_salvaged_with_a_note(
    server: _FakeServer,
) -> None:
    server.responder = lambda path, body: _completion(
        json.dumps(_ANSWER)[:-60], finish_reason="length"
    )
    model = _model(server)

    result = model("s", "texte")

    assert result is not None and [c.name for c in result.classes] == ["Bloc"]
    assert len(server.chat_requests) == 1  # no repair: it would be cut again
    assert "token limit" in model.notes[0]


def test_a_context_overflow_is_reported_without_changing_strategy(
    server: _FakeServer,
) -> None:
    server.responder = lambda path, body: _bad_request(
        "The number of tokens to keep from the initial prompt is greater than the "
        "context length"
    )
    model = _model(server)

    assert model("s", "texte") is None
    assert model.strategy == "json_schema"
    assert "context" in model.notes[0]


# --- Finding the model -------------------------------------------------------


def test_the_loaded_chat_model_is_detected(server: _FakeServer) -> None:
    def responder(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/api/v0/models":
            return 200, {
                "data": [
                    {"id": "nomic-embed", "type": "embeddings", "state": "loaded"},
                    {"id": "qwen3-8b", "type": "llm", "state": "not-loaded"},
                    {"id": "gemma-3-12b", "type": "llm", "state": "loaded"},
                ]
            }
        return 404, {}

    server.responder = responder

    assert detect_model(server.base_url, "k") == "gemma-3-12b"


def test_other_servers_fall_back_to_the_openai_listing(server: _FakeServer) -> None:
    def responder(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/v1/models":
            return 200, {"data": [{"id": "text-embedding-3"}, {"id": "llama3.1:8b"}]}
        return 404, {}

    server.responder = responder

    assert detect_model(server.base_url, "k") == "llama3.1:8b"


def test_a_local_endpoint_is_used_with_the_server_model(
    server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.responder = lambda path, body: (
        (200, {"data": [{"id": "mistral-7b", "type": "llm", "state": "loaded"}]})
        if path == "/api/v0/models"
        else _completion(json.dumps(_ANSWER))
    )
    monkeypatch.setenv("REASONING_ENDPOINT", server.base_url)
    monkeypatch.setenv("REASONING_API_KEY", "lm-studio")
    for name in ("REASONING_MODEL", "DEFAULT_MODELS_MODEL", "MODEL_NAME"):
        monkeypatch.delenv(name, raising=False)

    backend = extractor.resolve_backend()
    result = extractor.extract_text_ontology(
        "Le bloc 1 contient une transaction.", backend=backend
    )

    assert isinstance(backend, LocalChatModel)
    assert backend.model == "mistral-7b"
    assert [c.name for c in result.ontology.classes] == ["Bloc", "Transaction"]


def test_an_explicit_model_wins_over_detection(
    server: _FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REASONING_ENDPOINT", server.base_url)
    monkeypatch.setenv("REASONING_MODEL", "nvidia-nemotron-3.5-bolt-e4b-mlx")

    backend = extractor.resolve_backend(model="qwen3-30b")

    assert isinstance(backend, LocalChatModel)
    assert backend.model == "qwen3-30b"
    assert server.requests == []  # nothing had to be looked up
