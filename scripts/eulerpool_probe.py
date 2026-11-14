#!/usr/bin/env python3
"""Probe the Eulerpool free plan on a few ISINs: what does it actually return?

Reads the key from the environment variable EULERPOOL_API_KEY -- it never opens a .env file itself
and never prints, logs or writes the key. Load it into your shell first, e.g.

    set -a; source .env; set +a
    python3 scripts/eulerpool_probe.py IE00B4L5Y983 IE00B53SZB19

Company endpoints (relative paths under /api/1), to see what free-plan fundamentals look like:

    python3 scripts/eulerpool_probe.py --get equity/profile/US67066G1040 equity/metrics/US67066G1040

Each response is archived verbatim under data/raw/eulerpool-<date>/ (public fund data, no personal
information), and a short summary is printed: HTTP status, remaining quota, field names, whether
weights add up, the first rows. Stdlib only.

What this tells you before any integration: are the endpoints open on the FREE key, do they
cover UCITS ISINs, and do the figures agree with the issuer factsheet we already hold.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.eulerpool.com/api/1"
ENDPOINTS = ("holdings", "sectors", "countries")
ROOT = Path(__file__).resolve().parent.parent


def fetch(path: str, key: str) -> tuple[int, dict, object]:
    # Authorization header rather than ?token=: a key in a URL ends up in logs and tracebacks.
    req = urllib.request.Request(f"{BASE}/{path}", headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
        "User-Agent": "personal-finance-agent/0.1 (personal use)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            status, headers = r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        body, status, headers = e.read().decode("utf-8", "replace"), e.code, dict(e.headers)
    try:
        return status, headers, json.loads(body)
    except json.JSONDecodeError:
        return status, headers, body[:300]


def rows_of(payload):
    """Find the list of rows whatever the envelope is called, without guessing field names."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("holdings", "sectors", "countries", "data", "items", "weights"):
            if isinstance(payload.get(k), list):
                return payload[k]
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def weight_of(row: dict):
    for k in ("weight", "percentage", "percent", "pct", "allocation"):
        if isinstance(row.get(k), (int, float)):
            return row[k]
    return None


def probe_paths(paths: list[str], key: str, out_dir: Path) -> int:
    """Try arbitrary relative paths (company endpoints) and show status, quota and a preview."""
    for path in paths:
        path = path.strip("/")
        status, headers, payload = fetch(path, key)
        slug = path.replace("/", "_")
        (out_dir / f"get-{slug}.json").write_text(
            json.dumps({"status": status, "payload": payload}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        remaining = headers.get("x-ratelimit-remaining") or headers.get("X-RateLimit-Remaining")
        print(f"\n- GET {path}: HTTP {status}  restant={remaining or '—'}")
        if status != 200:
            print(f"    réponse : {str(payload)[:240]}")
            continue
        if isinstance(payload, dict):
            print(f"    clés : {sorted(payload)[:30]}")
        elif isinstance(payload, list):
            print(f"    {len(payload)} éléments ; champs du premier : "
                  f"{sorted(payload[0]) if payload and isinstance(payload[0], dict) else '—'}")
        print(f"    aperçu : {json.dumps(payload, ensure_ascii=False)[:600]}")
    print(f"\nRéponses brutes archivées dans {out_dir.relative_to(ROOT)}/")
    return 0


def main(argv: list[str]) -> int:
    key = os.environ.get("EULERPOOL_API_KEY", "").strip()
    if not key:
        print("EULERPOOL_API_KEY absente de l'environnement.\n"
              "  set -a; source .env; set +a   puis relance.", file=sys.stderr)
        return 2
    out_dir = ROOT / "data" / "raw" / f"eulerpool-{dt.date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if argv and argv[0] == "--get":
        return probe_paths(argv[1:], key, out_dir)
    isins = argv or ["IE00B4L5Y983"]

    for isin in isins:
        print(f"\n=== {isin} ===")
        for ep in ENDPOINTS:
            status, headers, payload = fetch(f"etf/{ep}/{isin}", key)
            (out_dir / f"{ep}-{isin}.json").write_text(
                json.dumps({"status": status, "payload": payload}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            quota = {k: v for k, v in headers.items() if k.lower().startswith("x-ratelimit")}
            print(f"- {ep}: HTTP {status}  quota={quota or '—'}")
            if status != 200:
                print(f"    réponse : {str(payload)[:240]}")
                continue
            rows = rows_of(payload)
            if isinstance(payload, dict):
                print(f"    clés de premier niveau : {sorted(payload)}")
            print(f"    {len(rows)} lignes", end="")
            ws = [w for w in (weight_of(r) for r in rows if isinstance(r, dict)) if w is not None]
            if ws:
                print(f" · somme des poids = {sum(ws):.4f}", end="")
            print()
            for r in rows[:5]:
                print(f"      {json.dumps(r, ensure_ascii=False)[:160]}")
            if rows and isinstance(rows[0], dict):
                print(f"    champs d'une ligne : {sorted(rows[0])}")
    print(f"\nRéponses brutes archivées dans {out_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
