# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which model the studio calls.

The NVIDIA catalog is the default (the same reasoning model as the rest of
Auto-Ontology). An OpenAI-compatible server — OpenAI, LM Studio, vLLM, a
local llama.cpp — is selected by pointing the endpoint at it. Environment
variables win over the settings file, so a shell one-liner stays predictable.
The key is never returned to the page.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from langchain_core.language_models import BaseChatModel

from auto_ontology.text_ontology.store import ProjectStore

NVIDIA_INTEGRATE = "https://integrate.api.nvidia.com/v1"
NVIDIA_INFERENCE = "https://inference-api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_REASONING_MODEL = "azure/anthropic/claude-opus-5-5"

NO_KEY_MESSAGE = (
    "Aucune clé LLM n'est configurée. Indiquez ONTOLOGY_LLM_API_KEY "
    "(ou REASONING_API_KEY, ou NVIDIA_API_KEY), ou ouvrez Réglages pour la saisir. "
    "Sans clé, l'exemple s'affiche quand même."
)


@dataclass(frozen=True)
class LlmConfig:
    """The effective endpoint, model and key for one run."""

    endpoint: str
    model: str
    api_key: str
    timeout_s: int
    max_tokens: int
    chunk_chars: int
    source: str

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key.strip() and self.endpoint.strip() and self.model.strip()
        )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _defaults_for(api_key: str) -> tuple[str, str]:
    if api_key.startswith("sk-"):
        return NVIDIA_INFERENCE, NVIDIA_REASONING_MODEL
    return NVIDIA_INTEGRATE, NVIDIA_MODEL


def resolve_llm_config(store: ProjectStore) -> LlmConfig:
    """Environment, then the settings file, then the NVIDIA defaults."""
    saved = store.settings()
    env_key = _first_env(
        "ONTOLOGY_LLM_API_KEY",
        "REASONING_API_KEY",
        "DEFAULT_MODELS_API_KEY",
        "NVIDIA_API_KEY",
    )
    env_endpoint = _first_env(
        "ONTOLOGY_LLM_ENDPOINT",
        "REASONING_ENDPOINT",
        "DEFAULT_MODELS_ENDPOINT",
        "BASE_URL",
    )
    env_model = _first_env(
        "ONTOLOGY_LLM_MODEL",
        "REASONING_MODEL",
        "DEFAULT_MODELS_MODEL",
        "MODEL_NAME",
    )
    key = env_key or saved.api_key.strip()
    endpoint = env_endpoint or saved.endpoint.strip()
    model = env_model or saved.model.strip()
    if env_key or env_endpoint or env_model:
        source = "env"
    elif saved.api_key or saved.endpoint or saved.model:
        source = "file"
    else:
        source = "default"
    default_endpoint, default_model = _defaults_for(key)
    endpoint = endpoint or default_endpoint
    model = model or default_model
    timeout = _positive(
        _first_env("ONTOLOGY_LLM_TIMEOUT", "LLM_INVOKE_TIMEOUT_S"),
        saved.timeout_s or 120,
    )
    max_tokens = saved.max_tokens or 8192
    chunk_chars = saved.chunk_chars or 12_000
    return LlmConfig(
        endpoint=endpoint.rstrip("/"),
        model=model,
        api_key=key,
        timeout_s=timeout,
        max_tokens=max_tokens,
        chunk_chars=chunk_chars,
        source=source,
    )


def _positive(raw: str, fallback: int) -> int:
    try:
        value = int(raw) if raw else fallback
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def masked_key(api_key: str) -> str:
    """A hint that shows a key is set without revealing it."""
    if not api_key:
        return ""
    tail = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"••••{tail}"


def public_llm(config: LlmConfig, *, demo: bool) -> dict[str, object]:
    """The settings the page is allowed to see."""
    if demo:
        message = (
            "Mode démonstration : l'extraction est factice, aucun modèle n'est appelé."
        )
    elif config.configured:
        message = ""
    else:
        message = NO_KEY_MESSAGE
    return {
        "configured": config.configured or demo,
        "demo": demo,
        "endpoint": config.endpoint,
        "model": config.model,
        "has_key": bool(config.api_key),
        "key_hint": masked_key(config.api_key),
        "timeout_s": config.timeout_s,
        "max_tokens": config.max_tokens,
        "chunk_chars": config.chunk_chars,
        "source": config.source,
        "message": message,
    }


def _nvidia_host(endpoint: str) -> bool:
    host = (urlparse(endpoint).hostname or "").lower()
    return host.endswith("nvidia.com")


def build_llm(config: LlmConfig) -> BaseChatModel:
    """A chat client for *config*. NVIDIA hosts keep the product's client."""
    if not config.configured:
        raise EnvironmentError(NO_KEY_MESSAGE)
    from auto_ontology.utils import llm_invoke

    llm_invoke.LLM_INVOKE_TIMEOUT_S = config.timeout_s
    if _nvidia_host(config.endpoint):
        return llm_invoke._build_client(
            model=config.model,
            api_key=config.api_key,
            base_url=config.endpoint,
            temperature=0.0,
            max_tokens=config.max_tokens,
        )
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, object] = {
        "model": config.model,
        "api_key": config.api_key,
        "base_url": config.endpoint,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout_s,
        "max_retries": 0,
    }
    # gpt-5 and o-series reject an explicit temperature. Leave it unset.
    if not config.model.startswith(
        ("openai/", "azure/", "aws/", "gpt-5", "o1", "o3", "o4")
    ):
        kwargs["temperature"] = 0
    return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


def test_connection(config: LlmConfig) -> dict[str, object]:
    """Ask the endpoint for its model list. No prompt is sent."""
    if not config.api_key:
        return {"ok": False, "message": NO_KEY_MESSAGE}
    if not config.endpoint:
        return {"ok": False, "message": "Indiquez l'adresse du serveur de modèle."}
    url = config.endpoint.rstrip("/") + "/models"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"Connexion impossible : {exc}"}
    if response.status_code == 200:
        return {"ok": True, "message": "Connexion établie."}
    return {
        "ok": False,
        "message": f"Le serveur a répondu {response.status_code}.",
    }
