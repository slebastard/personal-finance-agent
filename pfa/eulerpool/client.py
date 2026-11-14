"""Thin Eulerpool HTTP client (stdlib). Reads the key from the keychain, never from a project file.

The key is sent in an `Authorization: Bearer` header rather than `?token=`: a key in a URL ends up
in tracebacks, proxies and shell history. It is never printed, logged or archived.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..finary.auth import KeychainStore

BASE = "https://api.eulerpool.com/api/1"
KEYCHAIN_SERVICE = "pfa-eulerpool"
ENV_VAR = "EULERPOOL_API_KEY"
USER_AGENT = "personal-finance-agent/0.1 (personal use)"


class EulerpoolError(RuntimeError):
    pass


class QuotaExhausted(EulerpoolError):
    pass


class MissingKey(EulerpoolError):
    pass


def keychain() -> KeychainStore:
    return KeychainStore(KEYCHAIN_SERVICE)


def api_key() -> str:
    """Keychain first; the environment variable is a fallback for one-off runs."""
    key = keychain().get() or os.environ.get(ENV_VAR, "").strip()
    if not key:
        raise MissingKey("aucune clé Eulerpool : lance `python3 -m pfa auth-eulerpool` "
                         "(ou exporte EULERPOOL_API_KEY pour un essai ponctuel)")
    return key


class Client:
    """`get(path) -> (status, payload, remaining)`. `remaining` is the monthly quota left, or None."""

    def __init__(self, key: str | None = None, base: str = BASE, timeout: int = 40):
        self._key = key or api_key()
        self.base = base
        self.timeout = timeout
        self.calls = 0
        self.remaining: int | None = None
        self.limit: int | None = None

    def get(self, path: str) -> tuple[int, object, int | None]:
        # percent-encode each segment: a ticker like "NOVO B.CO" contains a space (found on the first run)
        safe_path = "/".join(urllib.parse.quote(seg, safe="") for seg in path.strip("/").split("/"))
        req = urllib.request.Request(f"{self.base}/{safe_path}", headers={
            "Authorization": f"Bearer {self._key}", "Accept": "application/json",
            "User-Agent": USER_AGENT})
        self.calls += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, body, headers = r.status, r.read().decode("utf-8", "replace"), r.headers
        except urllib.error.HTTPError as e:
            status, body, headers = e.code, e.read().decode("utf-8", "replace"), e.headers
        rem = headers.get("X-RateLimit-Remaining")
        if rem is not None and str(rem).isdigit():
            self.remaining = int(rem)
        lim = headers.get("X-RateLimit-Limit")
        if lim is not None and str(lim).isdigit():
            self.limit = int(lim)
        if status == 429:
            raise QuotaExhausted("quota Eulerpool épuisé (429) — reprise au prochain mois ou plan supérieur")
        if status == 401:
            raise EulerpoolError("clé Eulerpool refusée (401)")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body[:300]
        return status, payload, self.remaining
