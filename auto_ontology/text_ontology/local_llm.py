# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Extraction through any model served by a local OpenAI-compatible server.

LM Studio, Ollama, llama.cpp's server and vLLM all speak the OpenAI chat API,
but the models behind them differ in ways that break a plain structured call:

* Some honour ``response_format`` with a JSON schema (the server then forces
  valid JSON); some servers or models reject it.
* Reasoning models write ``<think>...</think>`` before the answer, and many
  models wrap JSON in a Markdown fence or add a sentence around it.
* Some chat templates refuse a ``system`` message (Gemma, for one).
* A small model can loop until it runs out of tokens, leaving the JSON cut.

:class:`LocalChatModel` tries the strictest request first and steps down only
when the server refuses it, remembering what worked for the next chunk. It
reads JSON out of whatever surrounds it, asks the model once to fix an answer
that does not validate, and keeps the complete items of an answer that was cut
at the token limit, saying so in :attr:`LocalChatModel.notes`.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from auto_ontology.text_ontology.models import TextOntology

if TYPE_CHECKING:
    import openai

logger = logging.getLogger(__name__)

_LOCAL_HOSTNAMES = {"localhost", "host.docker.internal", "0.0.0.0"}

# The output contract of the system prompt, written out rather than generated
# from the Pydantic models: no `$ref`, every field required, so the grammar
# engines behind local servers (llama.cpp, MLX/outlines) all accept it.
ONTOLOGY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["classes", "triplets", "attributes"],
    "properties": {
        "classes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "parent", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "parent": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                },
            },
        },
        "triplets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "subject",
                    "subject_type",
                    "predicate",
                    "object",
                    "object_type",
                ],
                "properties": {
                    "subject": {"type": "string"},
                    "subject_type": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "object_type": {"type": "string"},
                },
            },
        },
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity", "key", "value"],
                "properties": {
                    "entity": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
        },
    },
}

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "ontology", "strict": True, "schema": ONTOLOGY_JSON_SCHEMA},
}


def is_local_endpoint(url: str) -> bool:
    """Whether *url* points at this machine or the private network.

    That is where LM Studio, Ollama and llama.cpp run; a hosted API does not.
    """
    host = (urlparse(url).hostname or "").lower()
    if host in _LOCAL_HOSTNAMES or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


# ---------------------------------------------------------------------------
# Reading JSON out of a model's answer
# ---------------------------------------------------------------------------

_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _without_reasoning(text: str) -> str:
    text = _THINK.sub("", text)
    # A reasoning block whose opening tag the server already stripped.
    for closing in ("</think>", "</thinking>", "</reasoning>"):
        if closing in text:
            text = text.rsplit(closing, 1)[1]
    return text


def _scan(text: str, start: int) -> tuple[int | None, list[tuple[int, list[str]]]]:
    """From the ``{`` at *start*: where it closes, and where each item closes.

    The second value lists, for every ``}`` or ``]`` met, its position and the
    closers still open after it, which is what a cut answer needs to be shut.
    """
    stack: list[str] = []
    in_string = escaped = False
    closings: list[tuple[int, list[str]]] = []
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                return None, closings
            stack.pop()
            if not stack:
                return index, closings
            closings.append((index, list(stack)))
    return None, closings


def _loads(candidate: str) -> dict[str, Any] | None:
    for text in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_json_object(text: str) -> tuple[dict[str, Any], bool]:
    """The JSON object in a model's answer, and whether it had to be salvaged.

    Reasoning blocks and Markdown fences are dropped and the first complete
    object is read. When the answer was cut off, the object is closed after
    its last complete item, and the second value is ``True``. Raises
    ``ValueError`` when no object can be read.
    """
    text = _without_reasoning(text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("the answer holds no JSON object")
    end, closings = _scan(text, start)
    if end is not None:
        value = _loads(text[start : end + 1])
        if value is not None:
            return value, False
    # Cut off: close it after the latest item that is complete.
    for index, still_open in reversed(closings[-200:]):
        value = _loads(text[start : index + 1] + "".join(reversed(still_open)))
        if value is not None:
            return value, True
    raise ValueError("the answer is not valid JSON")


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("models", []))
    return (
        [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, list)
        else []
    )


def _model_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "key", "model_key", "modelKey", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_chat_model(item: dict[str, Any], model_id: str) -> bool:
    kind = str(item.get("type", "")).lower()
    if kind:
        return kind in ("llm", "vlm")
    return "embed" not in model_id.lower()


def _is_loaded(item: dict[str, Any]) -> bool:
    return item.get("state") == "loaded" or bool(item.get("loaded_instances"))


def detect_model(base_url: str, api_key: str, timeout: float = 10.0) -> str:
    """The chat model the local server has loaded, else the first it offers.

    LM Studio's own API says which model is loaded; the OpenAI ``/models``
    listing is the fallback for other servers. Embedding models are skipped.
    """
    root = base_url.rstrip("/")
    server = root[: -len("/v1")] if root.endswith("/v1") else root
    headers = {"Authorization": f"Bearer {api_key}"}
    candidates: list[tuple[bool, str]] = []
    for url in (f"{server}/api/v0/models", f"{server}/api/v1/models", f"{root}/models"):
        try:
            response = httpx.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            continue
        for item in _items(payload):
            model_id = _model_id(item)
            if model_id and _is_chat_model(item, model_id):
                candidates.append((_is_loaded(item), model_id))
        if candidates:
            break
    if not candidates:
        raise ValueError(f"no chat model is available at {base_url}")
    loaded = [model_id for is_loaded, model_id in candidates if is_loaded]
    return (loaded or [model_id for _, model_id in candidates])[0]


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Strategy:
    name: str
    response_format: bool
    system_role: bool


_STRATEGIES = (
    _Strategy("json_schema", response_format=True, system_role=True),
    _Strategy("plain JSON", response_format=False, system_role=True),
    _Strategy("plain JSON, no system role", response_format=False, system_role=False),
)

_CONTEXT_OVERFLOW = re.compile(
    r"context.{0,40}(length|overflow|exceed|too long)|too many tokens", re.IGNORECASE
)

_REPAIR = (
    "Ta réponse précédente n'est pas un objet JSON valide pour le format demandé "
    "({error}). Réponds UNIQUEMENT avec l'objet JSON corrigé, sans texte autour."
)


@dataclass
class LocalChatModel:
    """One extraction call on a local server, made robust to the model behind it."""

    base_url: str
    model: str
    api_key: str = "local"
    timeout: float = 600.0
    max_tokens: int = 8192
    transport_retries: int = 1
    notes: list[str] = field(default_factory=list)
    _strategy: int = 0
    _client: Any = None

    @property
    def strategy(self) -> str:
        return _STRATEGIES[self._strategy].name

    def _openai(self) -> openai.OpenAI:
        # Imported here: the client costs a few hundred milliseconds to load,
        # and most commands never send a request.
        import openai

        if self._client is None:
            self._client = openai.OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    def _messages(
        self, system: str, turns: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        if _STRATEGIES[self._strategy].system_role:
            return [{"role": "system", "content": system}, *turns]
        first, *rest = turns
        folded = {"role": "user", "content": f"{system}\n\n{first['content']}"}
        return [folded, *rest]

    def _complete(self, system: str, turns: list[dict[str, str]]) -> tuple[str, str]:
        """The answer text and finish reason, stepping down strategies on refusal."""
        import openai

        while True:
            strategy = _STRATEGIES[self._strategy]
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": self._messages(system, turns),
                "temperature": 0,
                "max_tokens": self.max_tokens,
            }
            if strategy.response_format:
                kwargs["response_format"] = _RESPONSE_FORMAT
            try:
                response = self._call(kwargs)
            except openai.BadRequestError as exc:
                # Too long for the model's context: no other request shape helps.
                if _CONTEXT_OVERFLOW.search(str(exc)) or self._strategy + 1 >= len(
                    _STRATEGIES
                ):
                    raise
                self._strategy += 1
                logger.info(
                    "The server refused a %s request (%s); retrying as %s",
                    strategy.name,
                    str(exc)[:160],
                    self.strategy,
                )
                continue
            choice = response.choices[0]
            text = choice.message.content or ""
            if not text.strip():
                # Some servers put a reasoning model's whole answer here.
                text = getattr(choice.message, "reasoning_content", None) or ""
            return text, choice.finish_reason or ""

    def _call(self, kwargs: dict[str, Any]) -> Any:
        import openai

        for attempt in range(self.transport_retries + 1):
            try:
                return self._openai().chat.completions.create(**kwargs)
            except (openai.APIConnectionError, openai.InternalServerError):
                # APITimeoutError is an APIConnectionError.
                if attempt >= self.transport_retries:
                    raise
                time.sleep(2 * (attempt + 1))
        raise AssertionError("unreachable")

    @property
    def description(self) -> str:
        return f"{self.model} on the local server {self.base_url}"

    def __call__(self, system: str, user: str) -> TextOntology | None:
        """The ontology the model gives for one chunk, or ``None``."""
        import openai

        turns = [{"role": "user", "content": user}]
        fallback: TextOntology | None = None
        for attempt in range(2):
            try:
                text, finish_reason = self._complete(system, turns)
            except openai.APIError as exc:
                message = str(exc)
                if _CONTEXT_OVERFLOW.search(message):
                    self.notes.append(
                        "the chunk is too long for the model's context "
                        "(lower --chunk-chars or load the model with a longer context)"
                    )
                logger.error(
                    "Local model call failed: %s: %s", type(exc).__name__, message
                )
                break
            cut = finish_reason == "length"
            try:
                payload, salvaged = parse_json_object(text)
                ontology = TextOntology.model_validate(payload)
            except (ValueError, ValidationError) as exc:
                error = str(exc).splitlines()[0][:300]
                logger.warning("The model's answer could not be read: %s", error)
                if attempt == 0 and not cut:
                    turns = [*turns, *self._repair_turns(text, error)]
                    continue
                break
            if salvaged and not cut and attempt == 0:
                # Malformed rather than cut: ask once for a clean answer, and
                # keep what could be read in case the second one is worse.
                fallback = ontology
                turns = [*turns, *self._repair_turns(text, "JSON mal formé")]
                continue
            if salvaged or cut:
                self.notes.append(
                    "the answer was cut at the token limit; only its complete "
                    "items were kept (raise --max-tokens or lower --chunk-chars)"
                    if cut
                    else "the answer was malformed; only its readable items were kept"
                )
            return ontology
        if fallback is not None:
            self.notes.append(
                "the answer was malformed; only its readable items were kept"
            )
        return fallback

    @staticmethod
    def _repair_turns(text: str, error: str) -> list[dict[str, str]]:
        return [
            {"role": "assistant", "content": text[:4000]},
            {"role": "user", "content": _REPAIR.format(error=error)},
        ]
