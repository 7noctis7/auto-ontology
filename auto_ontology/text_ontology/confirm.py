# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Two-step writes: a preview hands out a token, the write spends it.

A token is an HMAC, under a secret drawn when the server starts, of the tool,
its exact arguments, the project and its revision, and an expiry. It is
therefore worthless after a restart, for other arguments, once the project
has changed, after five minutes, or a second time. That makes an agent show
what it is about to write and write exactly that, on the state it previewed.
It does not replace the client's own approval prompt; it adds to it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Mapping

TOKEN_TTL_S = 300


class ConfirmationError(ValueError):
    """The token cannot be spent. The message says what to do."""


def _canonical(arguments: Mapping[str, object]) -> str:
    kept = {
        key: value
        for key, value in arguments.items()
        if key != "confirm_token" and value not in (None, "", [])
    }
    return json.dumps(kept, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Confirmations:
    """Tokens of one server process."""

    def __init__(
        self, *, ttl_s: int = TOKEN_TTL_S, secret: bytes | None = None
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._ttl_s = ttl_s
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def _sign(self, payload: bytes) -> str:
        digest = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue(
        self, tool: str, arguments: Mapping[str, object], *, project: str, revision: str
    ) -> str:
        expires = int(time.time()) + self._ttl_s
        nonce = secrets.token_hex(8)
        payload = (
            f"{tool}|{project}|{revision}|{expires}|{nonce}|{_canonical(arguments)}"
        )
        return f"{expires}.{nonce}.{self._sign(payload.encode())}"

    def redeem(
        self,
        token: str,
        tool: str,
        arguments: Mapping[str, object],
        *,
        project: str,
        revision: str,
    ) -> None:
        """Spend *token* or raise :class:`ConfirmationError`."""
        try:
            expires_text, nonce, signature = token.split(".", 2)
            expires = int(expires_text)
        except ValueError as exc:
            raise ConfirmationError(
                "Jeton de confirmation illisible : appelez l'outil sans "
                "confirm_token pour obtenir un aperçu et un nouveau jeton."
            ) from exc
        payload = (
            f"{tool}|{project}|{revision}|{expires}|{nonce}|{_canonical(arguments)}"
        )
        if not hmac.compare_digest(signature, self._sign(payload.encode())):
            raise ConfirmationError(
                "Ce jeton ne correspond pas à cette écriture : les arguments ont "
                "changé, ou le projet a été modifié depuis l'aperçu. Redemandez "
                "un aperçu."
            )
        now = time.time()
        with self._lock:
            self._spent = {key: end for key, end in self._spent.items() if end > now}
            if expires < now:
                raise ConfirmationError("Jeton expiré : redemandez un aperçu.")
            if signature in self._spent:
                raise ConfirmationError("Ce jeton a déjà servi.")
            self._spent[signature] = expires
