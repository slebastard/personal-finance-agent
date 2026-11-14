"""Finary data access: REST for the portfolio, MCP for the one figure REST does not expose.

The public REST API has exactly four endpoints (verified 2026-10-17 against the OpenAPI 3.1 spec
served at https://public-api.finary.com/docs):

    GET /v1/users/me
    GET /v1/profiles
    GET /v1/assets                       filter[profile], filter[type]
    GET /v1/assets/{asset_id}/holdings   page[limit], page[offset]

Probing /v1/portfolio/overview, /v1/allocation, /v1/net-worth and friends returns 404 while
/v1/assets returns 401 — so the authoritative portfolio total genuinely has no REST equivalent.
`get_portfolio_overview` is therefore read over MCP, which is plain JSON-RPC over HTTP POST and
needs no agent. That total is what the reconciliation step compares against.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import API_BASE, MCP_URL
from .auth import USER_AGENT


class FinaryError(RuntimeError):
    pass


class RestUnauthorized(FinaryError):
    """The OAuth token was refused by /v1/* — the caller should fall back to MCP."""


def _get(url: str, token: str, timeout: int = 45) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if e.code in (401, 403):
            raise RestUnauthorized(f"{url} -> HTTP {e.code}: {raw[:200]}") from e
        if e.code == 429:
            raise FinaryError(f"rate limited by Finary (retry-after "
                              f"{e.headers.get('Retry-After', '?')}s)") from e
        raise FinaryError(f"{url} -> HTTP {e.code}: {raw[:300]}") from e
    except urllib.error.URLError as e:
        raise FinaryError(f"{url} unreachable: {e.reason}") from e


class RestClient:
    def __init__(self, token: str, base: str = API_BASE):
        self.token = token
        self.base = base.rstrip("/")

    def users_me(self) -> dict:
        return _get(f"{self.base}/v1/users/me", self.token)

    def profiles(self) -> dict:
        return _get(f"{self.base}/v1/profiles", self.token)

    def assets(self) -> dict:
        return _get(f"{self.base}/v1/assets", self.token)

    def holdings(self, asset_id: str, page_size: int = 100) -> dict:
        """All holdings for an asset, following `meta.has_more` and merging the pages.

        `included[]` is de-duplicated on (type, id): securities repeat across pages.
        """
        out: dict | None = None
        offset = 0
        while True:
            q = urllib.parse.urlencode({"page[limit]": page_size, "page[offset]": offset})
            page = _get(f"{self.base}/v1/assets/{asset_id}/holdings?{q}", self.token)
            if out is None:
                out = page
            else:
                out["data"].extend(page.get("data", []))
                seen = {(r.get("type"), r.get("id")) for r in out.get("included", [])}
                for r in page.get("included", []):
                    if (r.get("type"), r.get("id")) not in seen:
                        out.setdefault("included", []).append(r)
                        seen.add((r.get("type"), r.get("id")))
            meta = page.get("meta") or {}
            if not meta.get("has_more"):
                break
            offset += page_size
        return out or {"data": [], "included": []}


class McpClient:
    """Minimal JSON-RPC client for the MCP endpoint — enough to call one read-only tool."""

    def __init__(self, token: str, url: str = MCP_URL):
        self.token = token
        self.url = url
        self._id = 0

    def _rpc(self, method: str, params: dict | None = None, timeout: int = 60) -> dict:
        self._id += 1
        req = urllib.request.Request(self.url, method="POST", data=json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            raise FinaryError(f"MCP {method} -> HTTP {e.code}: {raw[:300]}") from e
        except urllib.error.URLError as e:
            raise FinaryError(f"MCP endpoint unreachable: {e.reason}") from e

        payload = _parse_rpc_body(body)
        if payload.get("error"):
            raise FinaryError(f"MCP {method} error: {payload['error']}")
        return payload.get("result") or {}

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Call a tool and return its parsed JSON payload."""
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        for block in res.get("content") or []:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError as e:
                    raise FinaryError(f"tool {name} returned non-JSON text") from e
        if "structuredContent" in res:
            return res["structuredContent"]
        raise FinaryError(f"tool {name} returned no readable content")

    def portfolio_overview(self) -> dict:
        return self.call_tool("get_portfolio_overview")

    def accounts(self) -> dict:
        return self.call_tool("accounts")

    def holdings(self, account_id: str) -> dict:
        return self.call_tool("holdings", {"account_id": account_id})


def _parse_rpc_body(body: str) -> dict:
    """Accept both a plain JSON response and an SSE stream (streamable-HTTP transport)."""
    body = body.strip()
    if body.startswith("{"):
        return json.loads(body)
    for line in body.splitlines():                     # text/event-stream: data: {...}
        line = line.strip()
        if line.startswith("data:"):
            chunk = line[5:].strip()
            if chunk and chunk != "[DONE]":
                try:
                    msg = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if "result" in msg or "error" in msg:
                    return msg
    raise FinaryError(f"unparseable MCP response: {body[:200]}")
