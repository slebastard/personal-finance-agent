"""OAuth against Finary's authorization server (Clerk), stdlib only.

Verified against the live metadata on 2026-10-17:

  protected resource   https://public-api.finary.com/.well-known/oauth-protected-resource/mcp
  authorization server https://clerk.finary.com
  grants               authorization_code, refresh_token, device_code  (NO client_credentials)
                       BUT: dynamic client registration silently DROPS device_code — a DCR client
                       comes back with ["authorization_code","refresh_token"] whatever is asked,
                       even with application_type=native and device_code as the only grant. The
                       device endpoint then rejects it ("does not have the device_code grant"), so
                       the device flow is unusable for a self-registered client. Hence the loopback
                       authorization-code flow below.
  scopes               openid, profile, email, offline_access, {public,private}_metadata
  auth methods         client_secret_basic, none, client_secret_post   (-> public client, no secret)
  PKCE                 S256
  access token TTL     1 day;  refresh token: "never expires" per Clerk docs

No `client_credentials` means a human must authorise once; `offline_access` means that one
authorisation can then last indefinitely, which is what makes an unattended cron possible.

Authorization code + PKCE with a loopback redirect. Clerk rejects `http://` redirect URIs for
`application_type: web` but accepts them for `native`, which is what lets a CLI catch the redirect
on 127.0.0.1 without serving HTTPS. One browser round-trip, once; `offline_access` then keeps the
refresh token alive so cron never needs a human again.

The refresh token is the only durable secret and it grants read access to the whole portfolio, so
it lives in the macOS keychain by default rather than in a file.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path

from .. import DATA

RESOURCE_METADATA = "https://public-api.finary.com/.well-known/oauth-protected-resource/mcp"
CLIENT_FILE = DATA / "oauth_client.json"
SCOPES = "openid profile email offline_access"
CALLBACK_PORT = int(os.environ.get("PFA_CALLBACK_PORT", "8765"))
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
KEYCHAIN_SERVICE = "pfa-finary"
USER_AGENT = "pfa/1.0 (personal finance agent; stdlib urllib)"

# RFC 8707 audience binding. Clerk advertises scoped access, and the MCP auth spec expects the
# token to be bound to the resource. If a request ever fails with `invalid_target`, drop this.
RESOURCE = "https://public-api.finary.com/mcp"


class AuthError(RuntimeError):
    pass


# --------------------------------------------------------------------------- transport

def _request(url: str, *, form=None, body_json=None, headers=None, method=None, timeout=30) -> dict:
    """GET, or POST either form-encoded or JSON. OAuth errors carry their detail in the body.

    The two encodings are not interchangeable and the distinction is explicit on purpose:
    OAuth token/device endpoints take `application/x-www-form-urlencoded` (RFC 6749 §4.1.3), while
    dynamic client registration takes a JSON *document* (RFC 7591 §3.1). Form-encoding a payload
    that contains `redirect_uris` flattens the list into its Python repr and the server rejects it
    with a confusing "['http://…'] is not a valid redirect URI".
    """
    body = None
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body_json is not None:
        body = json.dumps(body_json).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise AuthError(f"{url} -> HTTP {e.code}: {raw[:300]}") from e
        payload["_http_status"] = e.code
        return payload
    except urllib.error.URLError as e:
        raise AuthError(f"{url} unreachable: {e.reason}") from e


# --------------------------------------------------------------------------- credential store

class KeychainStore:
    """macOS keychain via the `security` CLI. No dependency, encrypted at rest by the OS."""

    name = "trousseau macOS"

    def __init__(self, service: str = KEYCHAIN_SERVICE):
        self.service = service
        self.account = os.environ.get("USER") or "pfa"

    def get(self) -> str | None:
        p = subprocess.run(["security", "find-generic-password", "-s", self.service,
                            "-a", self.account, "-w"], capture_output=True, text=True)
        return p.stdout.strip() or None if p.returncode == 0 else None

    def set(self, token: str) -> None:
        # -U updates in place; a single `security` invocation is the atomic unit here
        p = subprocess.run(["security", "add-generic-password", "-s", self.service,
                            "-a", self.account, "-w", token, "-U"], capture_output=True, text=True)
        if p.returncode != 0:
            raise AuthError(f"keychain write failed: {p.stderr.strip()}")

    def delete(self) -> bool:
        p = subprocess.run(["security", "delete-generic-password", "-s", self.service,
                            "-a", self.account], capture_output=True, text=True)
        return p.returncode == 0


class FileStore:
    """0600 file. Portability escape hatch (Linux, remote server) — plaintext at rest."""

    name = "fichier"

    def __init__(self, path: Path):
        self.path = Path(path)

    def get(self) -> str | None:
        if not self.path.exists():
            return None
        return (json.loads(self.path.read_text(encoding="utf-8")).get("refresh_token") or None)

    def set(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"refresh_token": token}), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)          # atomic: a crash never leaves a half-written token

    def delete(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


def store():
    override = os.environ.get("PFA_CREDENTIALS_FILE")
    return FileStore(Path(override)) if override else KeychainStore()


# --------------------------------------------------------------------------- discovery

def discover() -> dict:
    """Resolve the authorization server's endpoints from the protected resource's metadata."""
    pr = _request(RESOURCE_METADATA, method="GET")
    servers = pr.get("authorization_servers") or []
    if not servers:
        raise AuthError("no authorization_servers advertised by Finary's resource metadata")
    meta = _request(servers[0].rstrip("/") + "/.well-known/oauth-authorization-server", method="GET")
    for key in ("token_endpoint", "authorization_endpoint", "registration_endpoint"):
        if key not in meta:
            raise AuthError(f"authorization server does not advertise {key}")
    return meta


# --------------------------------------------------------------------------- client registration

def load_client() -> dict | None:
    if CLIENT_FILE.exists():
        return json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    return None


def register_client(meta: dict) -> dict:
    """Dynamic client registration (RFC 7591). Public client: no secret is issued or stored.

    `application_type: native` is what makes Clerk accept an `http://127.0.0.1` redirect URI; with
    the default (`web`) it answers "is not a valid redirect URI". device_code is not requested
    because Clerk's DCR drops it regardless — see the module docstring.
    """
    res = _request(meta["registration_endpoint"], body_json={
        "client_name": "pfa (personal finance agent)",
        "application_type": "native",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPES,
    })
    if "client_id" not in res:
        raise AuthError(f"client registration refused: {res.get('error_description') or res}")
    granted = res.get("grant_types") or []
    if "refresh_token" not in granted:
        raise AuthError(f"client registered without the refresh_token grant ({granted}) — "
                        "unattended refresh would be impossible")
    rec = {"client_id": res["client_id"],
           "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "redirect_uri": REDIRECT_URI,
           "token_endpoint": meta["token_endpoint"],
           "authorization_endpoint": meta["authorization_endpoint"],
           "issuer": meta.get("issuer")}
    CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


# --------------------------------------------------------------------------- browser login

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot loopback receiver for the authorization code."""

    result: dict = {}

    def do_GET(self):                                     # noqa: N802 (stdlib naming)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in q.items()}
        ok = "code" in type(self).result
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("Authentification réussie — tu peux fermer cet onglet."
               if ok else f"Échec : {type(self).result.get('error_description') or type(self).result}")
        self.wfile.write(f"<html><body style='font-family:system-ui;padding:3rem'>"
                         f"<p>{msg}</p></body></html>".encode())

    def log_message(self, *a):                            # keep the CLI output clean
        pass


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def browser_login(on_prompt=print, timeout: int = 300) -> dict:
    """One-time interactive authorisation. Returns the token response; stores the refresh token."""
    meta = discover()
    client = load_client() or register_client(meta)
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)

    try:
        server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    except OSError as e:
        raise AuthError(f"cannot listen on 127.0.0.1:{CALLBACK_PORT} ({e}). "
                        f"Set PFA_CALLBACK_PORT to a free port and re-register "
                        f"(delete {CLIENT_FILE}).") from e
    _CallbackHandler.result = {}
    threading.Thread(target=server.handle_request, daemon=True).start()

    url = client["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client["client_id"],
        "redirect_uri": client.get("redirect_uri", REDIRECT_URI), "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": RESOURCE})
    on_prompt("\n  Ouvre cette page pour autoriser l'accès (lecture seule) :\n")
    on_prompt(f"    {url}\n")
    try:
        webbrowser.open(url)
    except Exception:                                     # noqa: BLE001 — headless is fine
        pass
    on_prompt(f"  En attente du retour sur {client.get('redirect_uri', REDIRECT_URI)} …")

    deadline = time.time() + timeout
    while not _CallbackHandler.result and time.time() < deadline:
        time.sleep(0.3)
    server.server_close()
    res = _CallbackHandler.result
    if not res:
        raise AuthError("no callback received before timeout — authorisation aborted")
    if res.get("error"):
        raise AuthError(f"authorisation refused: {res['error']} — {res.get('error_description', '')}")
    if res.get("state") != state:
        raise AuthError("state mismatch on the callback — aborting rather than trusting it")

    tok = _request(client["token_endpoint"], form={
        "grant_type": "authorization_code", "code": res["code"],
        "redirect_uri": client.get("redirect_uri", REDIRECT_URI),
        "client_id": client["client_id"], "code_verifier": verifier, "resource": RESOURCE})
    if tok.get("error"):
        raise AuthError(f"code exchange failed: {tok['error']} — {tok.get('error_description', '')}")
    if not tok.get("refresh_token"):
        raise AuthError("no refresh_token returned — was offline_access granted?")
    store().set(tok["refresh_token"])
    return tok


# --------------------------------------------------------------------------- access tokens

def access_token() -> str:
    """Exchange the stored refresh token for a 1-day access token.

    Clerk does not document whether refresh tokens rotate. A rotated token is therefore persisted
    *before* this returns, so an interrupted run can never leave us holding a token the server has
    already invalidated.
    """
    client = load_client()
    if not client:
        raise AuthError("no OAuth client registered — run `python3 -m pfa auth` first")
    st = store()
    refresh = st.get()
    if not refresh:
        raise AuthError(f"no refresh token in the {st.name} — run `python3 -m pfa auth` first")

    tok = _request(client["token_endpoint"], form={
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": client["client_id"], "resource": RESOURCE})
    if tok.get("error"):
        raise AuthError(f"refresh failed: {tok['error']} — {tok.get('error_description', '')}. "
                        "Run `python3 -m pfa auth` to re-authorise.")
    if tok.get("refresh_token") and tok["refresh_token"] != refresh:
        st.set(tok["refresh_token"])        # persist the rotation before using the access token
    if not tok.get("access_token"):
        raise AuthError(f"no access_token in the refresh response: {tok}")
    return tok["access_token"]


def status() -> dict:
    client = load_client()
    st = store()
    return {"client_registered": bool(client),
            "client_id": (client or {}).get("client_id"),
            "credential_store": st.name,
            "refresh_token_present": bool(st.get())}


def logout() -> bool:
    return store().delete()
