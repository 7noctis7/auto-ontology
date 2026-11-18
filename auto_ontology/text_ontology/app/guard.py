# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keep the studio's local server for the person running it.

The studio has no login: it trusts whoever can reach it, which binding to
127.0.0.1 is meant to limit to this machine. A web page the person visits can
still reach 127.0.0.1, in two ways this module closes:

* DNS rebinding. A hostile domain re-resolves to 127.0.0.1, and the page's
  requests become same-origin, able to read projects, point the endpoint at
  its own server (the next extraction sends the API key there) or set the
  watched folder to private files. Such requests carry the hostile domain in
  ``Host``, so only the studio's own host names are served.
* Cross-site requests. A form on another site can POST a document without
  any preflight. Browsers name the sending site in ``Origin`` and
  ``Sec-Fetch-Site``, so a write from elsewhere is refused. Clients that are
  not browsers (curl, the generated SDK) send neither and are let through.

It also caps the request body, so one upload cannot exhaust memory.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_MAX_BODY_MB = 50


def max_body_bytes() -> int:
    """The request size cap, from ``ONTOLOGY_MAX_UPLOAD_MB`` (default 50)."""
    raw = os.environ.get("ONTOLOGY_MAX_UPLOAD_MB", "").strip()
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_BODY_MB
    except ValueError:
        megabytes = DEFAULT_MAX_BODY_MB
    return int(max(megabytes, 1) * 1024 * 1024)


def allowed_hosts(bound_host: str | None = None, extra: Iterable[str] = ()) -> set[str]:
    """The host names the studio answers to.

    Loopback names always; the address it is bound to, unless that is a
    wildcard; and ``ONTOLOGY_ALLOWED_HOSTS`` (comma-separated), for a studio
    deliberately reached from another machine.
    """
    hosts = set(LOOPBACK_HOSTS)
    if bound_host and bound_host not in {"0.0.0.0", "::", ""}:  # noqa: S104
        hosts.add(bound_host.strip("[]").lower())
    configured = os.environ.get("ONTOLOGY_ALLOWED_HOSTS", "")
    hosts.update(
        h.strip().strip("[]").lower() for h in configured.split(",") if h.strip()
    )
    hosts.update(h.strip().strip("[]").lower() for h in extra if h.strip())
    return hosts


def _host_name(host_header: str) -> str:
    """``"[::1]:4173"`` -> ``"::1"``, ``"localhost:4173"`` -> ``"localhost"``."""
    value = host_header.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _forbidden(code: str, message: str, status: int = 403) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def guard_middleware(
    hosts: set[str], max_bytes: int
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """The HTTP middleware enforcing the rules above."""

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = _host_name(request.headers.get("host", ""))
        if host not in hosts:
            return _forbidden(
                "forbidden_host",
                "Cette adresse n'est pas celle du studio. Ouvrez-le depuis "
                "http://127.0.0.1 ou ajoutez l'hôte à ONTOLOGY_ALLOWED_HOSTS.",
            )
        if request.method not in _SAFE_METHODS:
            if request.headers.get("sec-fetch-site", "") == "cross-site":
                return _forbidden(
                    "cross_site", "Requête refusée : elle vient d'un autre site."
                )
            origin = request.headers.get("origin")
            if origin and origin != "null":
                origin_host = (urlparse(origin).hostname or "").lower()
                if origin_host not in hosts:
                    return _forbidden(
                        "cross_site", "Requête refusée : elle vient d'un autre site."
                    )
            elif origin == "null":
                return _forbidden("cross_site", "Requête refusée : origine inconnue.")
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > max_bytes:
            return _forbidden(
                "too_large",
                f"Fichier trop volumineux (limite : {max_bytes // (1024 * 1024)} Mo, "
                "réglable avec ONTOLOGY_MAX_UPLOAD_MB).",
                status=413,
            )
        return await call_next(request)

    return guard
