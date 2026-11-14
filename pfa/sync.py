"""`pfa sync` — the deterministic replacement for the /snapshot skill's fetch-and-map steps.

Pipeline: fetch -> archive raw verbatim -> map to canonical -> reconcile -> validate -> load,
with every financial row attached to a run_id and the run appended to data/runs.jsonl.

Raw payloads are archived before anything is mapped, and never edited afterwards. Finary has no
history API, so a payload not kept is gone for good — if a mapping bug surfaces months later, the
raw archive is the only way to re-derive the truth.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import DASHBOARDS, LOGS, PROFILE, RAW, SNAPSHOTS, db, runs, schema
from .finary import auth, client, mapping

RECON_TOLERANCE = 0.005          # 0.5 % — beyond this the perimeter is wrong, not just rounded
ACCOUNT_MAP = "account_map.json"


class SyncError(RuntimeError):
    pass


class _Log:
    """Tee to stdout and data/logs/<date>.log — a cron job is silent otherwise."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")
        self.path = path

    def __call__(self, msg: str = "") -> None:
        print(msg)
        self.fh.write(msg + "\n")
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def load_account_map() -> dict:
    p = PROFILE / ACCOUNT_MAP
    if not p.exists():
        raise SyncError(
            f"{p} absent. Crée-le — Finary ne distingue pas les enveloppes, cette correspondance "
            f'est une décision :\n{{\n  "accounts": {{ "<uuid de compte>": "pea" }},\n  "ignore": []\n}}')
    return json.loads(p.read_text(encoding="utf-8"))


def _write_raw(raw_dir: Path, name: str, payload: dict) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")


def fetch(token: str, log) -> tuple[dict, dict[str, dict], dict | None, dict | None, str]:
    """Returns (assets_doc, holdings_by_asset, overview, users_me, transport)."""
    rest = client.RestClient(token)
    mcp = client.McpClient(token)

    users_me = None
    transport = "rest+mcp"
    try:
        users_me = rest.users_me()
        log("  REST /v1/users/me : OK — le jeton OAuth est accepté par l'API REST")
    except client.RestUnauthorized as e:
        transport = "mcp"
        log(f"  REST /v1/users/me : refusé ({e}) — repli intégral sur MCP (perte de `opened_at`)")

    if transport == "rest+mcp":
        assets = rest.assets()
        source = rest
    else:
        assets = mcp.accounts()
        source = mcp
    ids = [a["id"] for a in assets.get("data", [])]
    log(f"  {len(ids)} comptes")

    holdings = {}
    for aid in ids:
        holdings[aid] = source.holdings(aid)

    overview = None
    try:
        overview = mcp.portfolio_overview()
        log("  MCP get_portfolio_overview : OK (total faisant autorité récupéré)")
    except client.FinaryError as e:
        log(f"  MCP get_portfolio_overview indisponible ({e}) — réconciliation interne seulement")

    return assets, holdings, overview, users_me, transport


def run_sync(*, dry_run: bool = False, force: bool = False, dashboard: bool = True) -> int:
    account_map = load_account_map()
    run = runs.new("snapshot")
    log = _Log(LOGS / "sync.log")
    log(f"\n=== run {run['run_id']} — {run['started_at']} ===")

    try:
        token = auth.access_token()
        assets, holdings, overview, users_me, transport = fetch(token, log)
        run["transport"] = transport

        snapshot, warns, oldest_sync = mapping.build_snapshot(
            assets, holdings, account_map, run["run_id"],
            source="finary-rest" if transport == "rest+mcp" else "finary-mcp")
        as_of = snapshot["as_of"]
        run.update(as_of=as_of, oldest_sync=oldest_sync,
                   accounts_n=len(snapshot["accounts"]),
                   holdings_n=sum(len(a["holdings"]) for a in snapshot["accounts"]))
        log(f"  as_of = {as_of} (dérivé de la synchro la plus ancienne : {oldest_sync or 'aucune'})")
        for w in warns:
            log(f"  ⚠ {w}")

        # archive raw only once as_of is known, so the directory is named by valuation date
        raw_dir = RAW / as_of
        run["raw_dir"] = str(raw_dir)
        if users_me:
            _write_raw(raw_dir, "users-me.json", users_me)
        _write_raw(raw_dir, "assets.json", assets)
        for aid, doc in holdings.items():
            _write_raw(raw_dir, f"holdings-{aid}.json", doc)
        if overview:
            _write_raw(raw_dir, "portfolio-overview.json", overview)
        log(f"  brut archivé dans {raw_dir}")

        rec = mapping.reconcile(snapshot, overview)
        run.update(total_value=rec["total"], overview_total=rec["overview_total"],
                   recon_gap=rec["gap"])
        log(f"  total mappé     : {rec['total']:,.2f} €".replace(",", " "))
        if rec["overview_total"] is not None:
            log(f"  total Finary    : {rec['overview_total']:,.2f} €".replace(",", " "))
            log(f"  écart           : {rec['gap']:+,.2f} € ({rec['gap_pct'] * 100:+.4f} %)"
                .replace(",", " "))
        for p in rec["holdings_exceed_balance"]:
            log(f"  ⚠ {p['name']} : les lignes dépassent le solde de {-p['residual']:.2f} €")

        if rec["gap_pct"] is not None and rec["gap_pct"] > RECON_TOLERANCE and not force:
            raise SyncError(
                f"écart de réconciliation {rec['gap_pct'] * 100:.2f} % > "
                f"{RECON_TOLERANCE * 100:.1f} % — erreur de mapping probable, snapshot NON chargé. "
                f"Inspecte {raw_dir}, ou relance avec --force si l'écart est compris et accepté.")

        if dry_run:
            log("  --dry-run : snapshot non écrit, base non modifiée")
            run["status"] = "ok"
            runs.append(run)
            return 0

        doc, vwarns = schema.validate_snapshot(snapshot)
        for w in vwarns:
            log(f"  ⚠ {w}")
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        (SNAPSHOTS / f"{as_of}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        con = db.connect()
        run["status"] = "ok"
        db.upsert_run(con, run)                  # the run must exist before rows reference it
        db.load_snapshot(con, doc)
        log(f"  chargé : {run['accounts_n']} comptes, "
            f"{sum(len(a['holdings']) for a in doc['accounts'])} lignes")

        runs.append(run)

        if dashboard:
            from .cli import cmd_dashboard
            from argparse import Namespace
            cmd_dashboard(Namespace(as_of=None, open=False))
        log(f"=== run {run['run_id']} : OK ===")
        return 0

    except Exception as e:                        # noqa: BLE001 — every failure must reach the ledger
        run["status"] = "failed"
        run["error"] = f"{type(e).__name__}: {e}"
        runs.append(run)
        try:
            db.upsert_run(db.connect(), run)
        except Exception:                         # noqa: BLE001 — DB may be the thing that broke
            pass
        log(f"  ÉCHEC : {run['error']}")
        log(f"=== run {run['run_id']} : FAILED ===")
        print(f"\nsync failed: {run['error']}", file=sys.stderr)
        return 1
    finally:
        log.close()


def auth_login() -> int:
    tok = auth.browser_login()
    st = auth.store()
    print(f"\n  Authentifié. Refresh token stocké dans le {st.name}.")
    print(f"  Access token valable {tok.get('expires_in', 86400) // 3600} h ; "
          f"les prochains runs le renouvelleront seuls.")
    return 0
