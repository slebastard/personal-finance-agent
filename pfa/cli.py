"""CLI entry point:  python3 -m pfa <command>

  load-snapshot FILE        validate a canonical snapshot, copy it to data/snapshots/, load into SQLite
  load-instrument FILE...   validate instrument lookups, copy to data/instruments/, load into SQLite
  rebuild                   drop & rebuild the DB from data/snapshots, data/instruments, manual inputs
  setup [--import ARCHIVE] [--yes]   first-run setup on a fresh clone (folders, data import, DB, web build)
  export-data [-o FILE] [--no-raw]   ALL the user's data -> one zip archive (no secrets)
  import-data ARCHIVE [--overwrite] [--dry-run]   restore an archive, then rebuild the database
  auth-eulerpool [--from-env|--stdin|--status|--logout]   clé Eulerpool -> trousseau macOS
  enrich [--isin I] [--top 25] [--dry-run] [--refresh] [--status]   constituents + santé des sociétés (Eulerpool)
  fund-companies ISIN | lookthrough | company ISIN [--json]   company-level views (after enrich)
  instrument ISIN [--as-of D] [--json]   the per-line page's data: fiche, position, composition, history
  report [--as-of D] [--json|--section NAME]   deterministic analytics (agent's source of numbers)
  gaps                      instruments that need a Boursorama/justETF lookup (missing or stale)
  dashboard [--as-of D] [--open]   render dashboards/index.html (+ dated archive copy)
  simulate PLAN.json        what-if: apply buys/sells/deposits to the latest snapshot, print before/after
  validate FILE             dry-run validation (snapshot or instrument, auto-detected)
  auth [--status|--logout]  one-time OAuth device login; refresh token -> macOS keychain
  sync [--dry-run] [--force] [--no-dashboard]
                            fetch Finary -> archive raw -> map -> reconcile -> load (cron-ready)
  runs [--limit N] [--json] run history from the provenance ledger
  import-transactions FILE  import a Bankin' CSV export, classify flows, reconcile
  flows [--month M | --start D --end D] [--review] [--json]   cash-flow analytics
  export-reference          dump rules/taxonomy/targets as JSON for the TS server
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# reference/ ships with the code; ROOT may be redirected (PFA_ROOT) to another data tree
CODE_ROOT = Path(__file__).resolve().parent.parent

from . import (DASHBOARDS, DATA, DB_PATH, INSTRUMENTS, PROFILE, ROOT, SNAPSHOTS, analytics,
               db, flows, runs, schema)

STALE_DAYS = 120


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _warn(ws):
    for w in ws:
        print(f"  warning: {w}", file=sys.stderr)


def _load_manual_flows(con) -> None:
    manual = PROFILE / "manual_inputs.json"
    if not manual.exists():
        return
    doc = json.loads(manual.read_text(encoding="utf-8"))
    flows = doc.get("cash_flows", [])
    db.load_cash_flows(con, [f for f in flows if not str(f.get("account_id", "")).startswith("_")])
    # Finary never serves opened_at, so the fiscal opening dates are supplied by hand. Without them
    # `age_years` is null and the PEA 5-year / AV 8-year checks cannot be computed at all.
    opened = {k: v for k, v in (doc.get("account_opened_on") or {}).items()
              if not str(k).startswith("_")}
    if opened:
        with con:
            for account_id, date in opened.items():
                schema._date(date, f"account_opened_on[{account_id}]")   # fail loudly on a typo
                con.execute("UPDATE accounts SET opened_on=? WHERE id=?", (date, account_id))


def cmd_load_snapshot(args) -> int:
    doc, ws = schema.validate_snapshot(_read(args.file))
    _warn(ws)
    dest = SNAPSHOTS / f"{doc['as_of']}.json"
    if Path(args.file).resolve() != dest.resolve():
        _write(dest, _read(args.file))
    con = db.connect()
    db.load_snapshot(con, doc)
    _load_manual_flows(con)
    tot = sum(a["balance"] for a in doc["accounts"])
    print(f"loaded snapshot {doc['as_of']}: {len(doc['accounts'])} accounts, "
          f"{sum(len(a['holdings']) for a in doc['accounts'])} lines, total {tot:,.2f} €")
    return 0


def cmd_load_instrument(args) -> int:
    con = db.connect()
    # one lookup run covers the batch, so every instrument row resolves to exactly one run_id
    run = runs.new("lookup")
    db.upsert_run(con, {**run, "status": "ok"})
    loaded = 0
    for f in args.files:
        ins, ws = schema.validate_instrument(_read(f))
        if ins["ter"] is not None and ins["ter"] > 0.05:
            ws.append(f"ter={ins['ter']} looks like a percent; expected a fraction (0.0020 = 0.20%)")
        _warn(ws)
        dest = INSTRUMENTS / f"{ins['isin']}.json"
        if Path(f).resolve() != dest.resolve():
            _write(dest, _read(f))
        db.load_instrument(con, ins, run["run_id"])
        loaded += 1
        print(f"loaded instrument {ins['isin']} ({ins['name']}): dims={sorted(ins['breakdowns'])}")
    runs.append({**run, "status": "ok", "holdings_n": loaded})
    return 0


def cmd_import_transactions(args) -> int:
    from . import importers
    src = Path(args.file)
    fmt = args.format or importers.detect(src)
    rows = importers.FORMATS[fmt].parse(src)
    rules = flows.load_rules()
    flows.classify_all(rows, rules)

    if args.since:
        schema._date(args.since, "--since")
        rows = [r for r in rows if r["date"] >= args.since]

    con = db.connect()
    # match Bankin' account labels to Finary account ids, so the reconciliation can find balances
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM accounts")}
    folded = {flows.fold(n): i for i, n in names.items()}
    for r in rows:
        r["account_id"] = folded.get(flows.fold(r["account"]))
    unmatched = sorted({r["account"] for r in rows if not r["account_id"]})

    counts = {}
    for r in rows:
        counts[r["flow"]] = counts.get(r["flow"], 0) + 1
    print(f"{src.name}: {len(rows)} transactions ({fmt})")
    print("  natures: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if unmatched:
        print(f"  ⚠ comptes non rapprochés d'un compte Finary : {unmatched}")

    if args.dry_run:
        print("  --dry-run : rien n'a été écrit")
        return 0

    run = runs.new("transactions", transport=fmt)
    run.update(status="ok", accounts_n=len({r["account"] for r in rows}), holdings_n=len(rows))
    db.upsert_run(con, run)
    ins, upd = db.load_transactions(con, rows, run["run_id"])
    runs.append(run)
    db.write_transactions_jsonl(con, DATA / "transactions.jsonl")   # the portable, replayable source
    print(f"  chargé : {ins} nouvelles, {upd} mises à jour")

    dates = sorted(r["date"] for r in rows)
    agg = flows.aggregate(con, dates[0], dates[-1])
    q = agg["quality"]
    print(f"  non classé : {q['unclassified_amount_pct']*100:.1f} % du montant "
          f"({q['unclassified_count']} tx)")
    if q["reconciliation_gap"] is not None:
        print(f"  réconciliation Σ flux vs Δ solde : {q['reconciliation_gap']:+.2f} €")
    if q["months_with_suspicious_income"]:
        print(f"  ⚠ mois à revenu suspect : {', '.join(q['months_with_suspicious_income'])}")
    return 0


def cmd_flows(args) -> int:
    con = db.connect()
    if args.month:
        schema._date(args.month + "-01", "--month")
        y, m = (int(x) for x in args.month.split("-"))
        start = f"{args.month}-01"
        end = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
    else:
        bounds = con.execute("SELECT MIN(date), MAX(date) FROM transactions").fetchone()
        start = args.start or bounds[0]
        end = args.end or bounds[1]
    if not start:
        print("aucune transaction en base — lance `pfa import-transactions <export.csv>`",
              file=sys.stderr)
        return 1

    if args.review:
        cands = flows.review_candidates(con, start, end)
        print(json.dumps(cands, ensure_ascii=False, indent=2) if args.json
              else _fmt_review(cands, start, end))
        return 0

    agg = flows.aggregate(con, start, end)
    print(json.dumps(agg, ensure_ascii=False, indent=2) if args.json else _fmt_flows(agg))
    return 0


def _eur(v) -> str:
    return "—" if v is None else f"{v:,.0f} €".replace(",", " ")


def _fmt_flows(a: dict) -> str:
    o = [f"# Flux — {a['from']} → {a['to']}  ({a['months']:.1f} mois)", ""]
    for n in ("income", "spending", "refund", "internal", "provisional", "unclassified"):
        d = a["by_nature"][n]
        o.append(f"  {n:14s} {_eur(d['amount']):>12s}  {d['count']:>4d} tx")
    o += ["", f"  épargne nette  {_eur(a['net']):>12s}"
              + (f"   taux {a['savings_rate']*100:.1f} %" if a["savings_rate"] else ""),
          f"  par mois       {_eur(a['net']/a['months']):>12s}", "", "## Dépenses par catégorie"]
    for c in a["by_category"]:
        o.append(f"  {_eur(c['amount']):>12s}  {c['count']:>4d}  {c['category']}")
    o += ["", "## Mensuel", f"  {'mois':8s} {'revenus':>10s} {'conso':>10s} {'remb':>9s} {'net':>10s}"]
    for m in a["monthly"]:
        o.append(f"  {m['month']:8s} {_eur(m['income']):>10s} {_eur(m['spending']):>10s} "
                 f"{_eur(m['refund']):>9s} {_eur(m['net']):>10s}")
    q = a["quality"]
    o += ["", "## Qualité",
          f"  non classé : {q['unclassified_amount_pct']*100:.1f} % du montant "
          f"({q['unclassified_count']} tx)",
          f"  réconciliation : {('%+.2f €' % q['reconciliation_gap']) if q['reconciliation_gap'] is not None else 'hors bornes de snapshot'}"]
    if q["months_with_suspicious_income"]:
        o.append(f"  ⚠ revenu suspect : {', '.join(q['months_with_suspicious_income'])}")
    return "\n".join(o)


def _fmt_review(c: list, start: str, end: str) -> str:
    if not c:
        return f"Aucun candidat de recatégorisation entre {start} et {end}."
    o = [f"# Candidats de recatégorisation — {start} → {end}  ({len(c)})", ""]
    for r in c:
        o.append(f"  {r['date']}  {r['amount']:>+10.2f} €  [{r['flow']}]  {r['label'][:46]}")
        o.append(f"      {r['category']} / {r['subcategory']}")
        for w in r["why"]:
            o.append(f"      → {w}")
        o.append("")
    return "\n".join(o)


def cmd_export_reference(args) -> int:
    """Reference data as JSON so the TS server never re-declares a tax rule or a taxonomy alias."""
    from . import rules as rules_mod, taxonomy
    out = DATA / "generated"
    out.mkdir(parents=True, exist_ok=True)
    payloads = {
        "rules.json": {k: v for k, v in vars(rules_mod).items()
                       if k.isupper() or k == "VERIFIED_ON"},
        "taxonomy.json": {
            "gics": taxonomy.GICS, "regions": taxonomy.REGIONS,
            "sector_aliases": taxonomy._SECTOR_ALIASES,
            "country_aliases": taxonomy._COUNTRY_ALIASES,
            "region_of_country": taxonomy._REGION_OF,
            "region_aliases": taxonomy._REGION_ALIASES,
        },
        "targets.json": json.loads((PROFILE / "targets.json").read_text(encoding="utf-8")),
        "flow_natures.json": {"natures": list(flows.NATURES)},
        # enrichment: which fund borrows its constituents from which ETF, plus the teaching material
        "etf_proxies.json": {"funds": __import__("pfa.eulerpool.enrich", fromlist=["x"]).load_proxies()},
        "glossary.json": json.loads((CODE_ROOT / "reference" / "glossary.json").read_text(encoding="utf-8")),
        "learning_prompts.json": json.loads((CODE_ROOT / "reference" / "learning_prompts.json").read_text(encoding="utf-8")),
        # manual inputs the server needs to explain a figure, not to compute one
        "manual.json": {k: v for k, v in
                        json.loads((PROFILE / "manual_inputs.json").read_text(encoding="utf-8")).items()
                        if not k.startswith("_")},
    }
    for name, payload in payloads.items():
        _write(out / name, payload)
        print(f"wrote {out / name}")
    return 0


def cmd_auth_eulerpool(args) -> int:
    """Store the Eulerpool API key in the macOS keychain. The key is never printed or written to a file."""
    import getpass
    from .eulerpool import client as ec
    ks = ec.keychain()
    if args.logout:
        print("clé supprimée du trousseau" if ks.delete() else "aucune clé dans le trousseau")
        return 0
    if args.status:
        in_kc = bool(ks.get())
        in_env = bool(os.environ.get(ec.ENV_VAR, "").strip())
        print(f"clé Eulerpool : trousseau {'oui' if in_kc else 'non'} · variable d'environnement "
              f"{'oui' if in_env else 'non'}")
        return 0 if (in_kc or in_env) else 1
    if args.from_env:
        key = os.environ.get(ec.ENV_VAR, "").strip()
    elif args.stdin:
        key = sys.stdin.readline().strip()
    elif sys.stdin.isatty():
        key = getpass.getpass("Clé API Eulerpool (saisie masquée) : ").strip()
    else:
        print("pas de terminal : utilise --from-env (après `set -a; source .env; set +a`) ou --stdin",
              file=sys.stderr)
        return 2
    if not key:
        print("clé vide", file=sys.stderr)
        return 2
    # validate BEFORE storing: a wrong key stored silently would fail later, far from its cause
    status, _, remaining = ec.Client(key=key).get("equity/profile/US0378331005")
    if status != 200:
        print(f"clé refusée par Eulerpool (HTTP {status}) : rien n'a été stocké", file=sys.stderr)
        return 1
    ks.set(key)
    print(f"clé valide, stockée dans le {ks.name} (service {ec.KEYCHAIN_SERVICE})"
          + (f" · quota restant {remaining:,}".replace(",", " ") if remaining is not None else ""))
    return 0


def cmd_enrich(args) -> int:
    from .eulerpool import client as ec, enrich
    con = db.connect()
    if args.status:
        today = dt.date.today()
        _, held = enrich.held_funds(con)
        targets, skipped = enrich.plan_targets(held, enrich.load_proxies())
        for t in targets:
            d = enrich._read_json(enrich.HOLDINGS_DIR / f"{t['isin']}.json")
            if d:
                have = sum(1 for c in d["constituents"]
                           if (enrich._read_json(enrich.COMPANIES_DIR / f"{c['isin']}.json") or {}).get("covered"))
                age = (today - dt.date.fromisoformat(d["fetched_at"][:10])).days
                cc = d.get("crosscheck") or {}
                print(f"{t['isin']} {t['name'][:40]:40} {have}/{len(d['constituents'])} sociétés · "
                      f"top {d['top_n']} = {d['coverage_top']*100:.1f} % · données de {age} j"
                      + (" · ⚠ substitut hors seuil" if cc.get("warn") else ""))
            else:
                print(f"{t['isin']} {t['name'][:40]:40} pas encore enrichi")
        for s in skipped:
            print(f"{s['isin']} {s['name'][:40]:40} non couvert : {s['reason']}")
        try:
            cl = ec.Client()
            cl.get("equity/profile/US0378331005")
            print(f"quota restant : {cl.remaining:,} / {cl.limit:,}".replace(",", " "))
        except ec.EulerpoolError as e:
            print(f"quota : {e}")
        return 0
    if args.renormalize:
        enrich.renormalize(con)
        return 0
    client = None
    if not args.dry_run:
        try:
            client = ec.Client()
        except ec.EulerpoolError as e:
            print(e, file=sys.stderr)
            return 2
    try:
        s = enrich.run(con, client, top=args.top, force=args.refresh, dry_run=args.dry_run,
                       max_calls=args.max_calls, reserve=args.reserve,
                       only=set(args.isin) if args.isin else None)
    except ec.EulerpoolError as e:
        print(f"échec : {e}", file=sys.stderr)
        return 1
    if args.dry_run:
        print("  --dry-run : aucun appel réseau, rien n'a été écrit")
    return 1 if s.get("stopped") else 0


def _dump(obj, args) -> int:
    if obj is None:
        print("introuvable", file=sys.stderr)
        return 1
    print(json.dumps(obj, ensure_ascii=False, indent=None if args.json else 2, default=str))
    return 0


def cmd_fund_companies(args) -> int:
    from . import lookthrough
    return _dump(lookthrough.fund_companies(db.connect(), args.isin, args.as_of), args)


def cmd_lookthrough(args) -> int:
    from . import lookthrough
    return _dump(lookthrough.lookthrough(db.connect(), args.as_of), args)


def cmd_company(args) -> int:
    from . import lookthrough
    return _dump(lookthrough.company_view(db.connect(), args.isin, args.as_of), args)


def cmd_export_data(args) -> int:
    from . import portability as pt
    try:
        pt.export_data(ROOT, out=Path(args.output) if args.output else None, include_raw=not args.no_raw)
    except pt.ArchiveError as e:
        print(f"export impossible : {e}", file=sys.stderr)
        return 2
    return 0


def cmd_import_data(args) -> int:
    from . import portability as pt
    try:
        pt.import_data(Path(args.archive), ROOT, overwrite=args.overwrite, dry_run=args.dry_run)
    except pt.ImportConflict as e:
        print(e, file=sys.stderr)
        return 3
    except pt.ArchiveError as e:
        print(f"archive refusée : {e}", file=sys.stderr)
        return 2
    return 0


def cmd_setup(args) -> int:
    from . import portability as pt
    return pt.run_setup(ROOT, archive=Path(args.archive) if args.archive else None,
                        assume_yes=args.yes, build=not args.no_build)


def cmd_auth(args) -> int:
    from .finary import auth
    if args.status:
        print(json.dumps(auth.status(), indent=2, ensure_ascii=False))
        return 0
    if args.logout:
        print("refresh token supprimé" if auth.logout() else "aucun refresh token à supprimer")
        return 0
    from .sync import auth_login
    return auth_login()


def cmd_sync(args) -> int:
    from .sync import run_sync
    return run_sync(dry_run=args.dry_run, force=args.force, dashboard=not args.no_dashboard)


def cmd_runs(args) -> int:
    con = db.connect()
    rows = runs.recent(con, args.limit)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("aucun run enregistré (data/runs.jsonl absent ou `pfa rebuild` pas encore lancé)")
        return 0
    print(f"{'started':20s} {'kind':9s} {'status':8s} {'as_of':11s} {'total':>12s} {'écart':>9s}")
    for r in rows:
        tot = "—" if r["total_value"] is None else f"{r['total_value']:,.0f}".replace(",", " ")
        gap = "—" if r["recon_gap"] is None else f"{r['recon_gap']:+.2f}"
        print(f"{(r['started_at'] or '')[:19]:20s} {r['kind']:9s} {r['status']:8s} "
              f"{r['as_of'] or '—':11s} {tot:>12s} {gap:>9s}"
              + (f"  {r['error'][:60]}" if r["error"] else ""))
    return 0


def _carry_transactions(con, backup: Path | None) -> int:
    """Copy the old database's transactions into the rebuilt one, then delete the backup."""
    if backup is None or not backup.exists():
        return 0
    try:
        con.execute("ATTACH DATABASE ? AS old", (str(backup),))
        has = con.execute("SELECT 1 FROM old.sqlite_master WHERE type='table' AND name='transactions'").fetchone()
        n = 0
        if has:
            new_cols = [r[1] for r in con.execute("PRAGMA main.table_info(transactions)")]
            old_cols = {r[1] for r in con.execute("PRAGMA old.table_info(transactions)")}
            cols = [c for c in new_cols if c in old_cols]
            with con:
                con.execute(f"INSERT OR REPLACE INTO main.transactions({','.join(cols)}) "
                            f"SELECT {','.join(cols)} FROM old.transactions")
            n = con.execute("SELECT COUNT(*) FROM main.transactions").fetchone()[0]
        con.execute("DETACH DATABASE old")
    finally:
        backup.unlink(missing_ok=True)
    return n


def cmd_rebuild(args) -> int:
    # Transactions are NOT derived from any JSON that rebuild replays (they come from Bankin' CSV
    # exports imported by hand), so dropping the file would silently delete them. Carry them over.
    backup = None
    if DB_PATH.exists():
        backup = DB_PATH.with_suffix(".db.rebuild-backup")
        shutil.copy2(DB_PATH, backup)
        DB_PATH.unlink()
    con = db.connect()
    runs.replay(con)                      # runs first: snapshot rows reference them
    n_s = n_i = 0
    for p in sorted(SNAPSHOTS.glob("*.json")):
        doc, ws = schema.validate_snapshot(_read(p))
        _warn(ws)
        db.load_snapshot(con, doc)
        n_s += 1
    # instruments replayed from disk get a synthetic lookup run, so they too resolve to one run_id
    ins_run = None
    # `_`-prefixed files are build helpers / archived intermediates, not instruments
    for p in sorted(x for x in INSTRUMENTS.glob("*.json") if not x.name.startswith("_")):
        ins, ws = schema.validate_instrument(_read(p))
        if ins_run is None:
            ins_run = {"run_id": f"rebuild-lookup-{ins['fetched_at']}", "kind": "lookup",
                       "status": "imported", "as_of": ins["fetched_at"],
                       "error": "instruments replayed from data/instruments/ by rebuild"}
            db.upsert_run(con, ins_run)
        db.load_instrument(con, ins, ins_run["run_id"])
        n_i += 1
    _load_manual_flows(con)
    from .eulerpool import enrich as _enrich
    n_eh, n_ec = _enrich.replay_from_disk(con)
    n_r = runs.replay(con)
    db.load_transactions_jsonl(con, DATA / "transactions.jsonl")      # portable source first…
    _carry_transactions(con, backup)                                 # …then whatever the old file held
    n_tx = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print(f"rebuilt {DB_PATH.name}: {n_s} snapshots, {n_i} instruments, {n_eh} fund lists, "
          f"{n_ec} companies, {n_r} runs, {n_tx} transactions")
    return 0


def _fmt_report(r: dict) -> str:
    eur = lambda v: "—" if v is None else f"{v:,.0f} €".replace(",", " ")  # noqa: E731
    pct = lambda v: "—" if v is None else f"{v*100:.1f}%"  # noqa: E731
    lines = [f"# Portfolio report — {r['as_of']}", f"Total: {eur(r['total_value'])}"
             + (f"  (Δ {eur(r['change_vs_previous'])} vs {r['previous_as_of']})" if r["previous_as_of"] else "")]
    lines.append("\n## Envelopes")
    lines += [f"- {e['bucket']}: {eur(e['value'])} ({pct(e['pct'])})" for e in r["envelopes"]]
    for dim in ("asset_class", "region", "sector"):
        lines.append(f"\n## {dim} (look-through{'' if dim == 'asset_class' else ', equity sleeve'})")
        lines += [f"- {x['bucket']}: {pct(x['pct'])} ({eur(x['value'])})" for x in r["exposure"][dim]]
    g = r["exposure"]["data_gaps"]
    lines.append(f"\nCoverage — geography {pct(g['coverage_geo_pct'])}, sectors {pct(g['coverage_sector_pct'])}")
    f = r["fees"]
    lines.append(f"Fees — funds {eur(f['fund_fees_eur_per_year'])}/yr (TER {pct(f['weighted_ter_on_covered'])} "
                 f"on {pct(f['ter_coverage_pct'])} covered), wrappers {eur(f['wrapper_fees_eur_per_year'])}/yr")
    c = r["concentration"]
    lines.append(f"Concentration — {c['n_positions']} lines, top1 {pct(c['top1_pct'])}, top5 {pct(c['top5_pct'])}")
    if r["drift_vs_targets"]:
        lines.append("\n## Drift vs targets")
        for dim, rows in r["drift_vs_targets"].items():
            lines += [f"- {dim}/{x['bucket']}: {pct(x['actual'])} vs {pct(x['target'])} ({x['drift']*100:+.1f} pts)" for x in rows]
    pc = r.get("perimeter_changes") or {}
    if pc.get("note"):
        lines.append("\n## Perimeter change")
        lines.append(pc["note"])
        for g in pc.get("gone", []):
            tag = f"closed {g['closed_on']}" if g.get("closed_on") else "NOT declared closed"
            lines.append(f"- out: {g['name']} ({g['envelope']}) — last {eur(g['last_balance'])} "
                         f"on {g['last_seen']} · {tag}")
        for n in pc.get("new", []):
            lines.append(f"- in: {n['name']} ({n['envelope']}) — {eur(n['balance'])}")
    rc = r.get("receivables") or {}
    if rc.get("items"):
        lines.append("\n## Créances (hors total Finary)")
        for i in rc["items"]:
            lines.append(f"- {i['label']}: payé {eur(i['paid'])} le {i['paid_on']} · "
                         f"restitution attendue {eur(i['expected_refund'])} "
                         f"(retenue {eur(i['expected_retention'])}) · "
                         f"date {i['expected_refund_date'] or 'inconnue'}")
        lines.append(f"Total + créances : {eur(rc['total_with_receivables'])}")
    lines.append("\n## Envelope checks")
    for e in r["envelope_checks"]:
        lines.append(f"- {e['account']} · {e['check']}: " + json.dumps({k: v for k, v in e.items() if k not in ('account', 'check')}, ensure_ascii=False))
    for n in r["returns"]["notes"]:
        lines.append(f"\nNote: {n}")
    return "\n".join(lines)


def cmd_instrument(args) -> int:
    con = db.connect()
    v = analytics.instrument_view(con, args.isin, args.as_of)
    if v is None:
        print(f"aucune ligne {args.isin} détenue à cette date", file=sys.stderr)
        return 1
    print(json.dumps(v, ensure_ascii=False, indent=None if args.json else 2, default=str))
    return 0


def cmd_report(args) -> int:
    con = db.connect()
    r = analytics.report(con, args.as_of)
    if args.section:
        r = r[args.section]
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    elif args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        print(_fmt_report(r))
    return 0


def cmd_gaps(args) -> int:
    con = db.connect()
    dates = analytics.snapshot_dates(con)
    if not dates:
        print("no snapshot loaded")
        return 1
    today = dt.date.today()
    todo = []
    for p in analytics.positions(con, dates[-1]):
        if not p["isin"] or p["kind"] in ("cash", "fonds_euros"):
            continue
        reason = None
        if not p["has_instrument_data"]:
            reason = "missing"
        elif p["instrument_fetched_at"] and (today - dt.date.fromisoformat(p["instrument_fetched_at"])).days > STALE_DAYS:
            reason = f"stale (> {STALE_DAYS} days)"
        if reason:
            todo.append({"isin": p["isin"], "name": p["name"], "kind": p["kind"], "value": round(p["value"], 2),
                         "reason": reason})
    seen, uniq = set(), []
    for t in todo:
        if t["isin"] not in seen:
            seen.add(t["isin"])
            uniq.append(t)
    print(json.dumps(uniq, ensure_ascii=False, indent=2))
    return 0


def cmd_dashboard(args) -> int:
    from .dashboard import instrument_page, render
    con = db.connect()
    r = analytics.report(con, args.as_of)
    DASHBOARDS.mkdir(parents=True, exist_ok=True)
    (DASHBOARDS / "archive").mkdir(exist_ok=True)
    pages = DASHBOARDS / "instruments"
    pages.mkdir(exist_ok=True)
    out = DASHBOARDS / "index.html"
    out.write_text(render(r), encoding="utf-8")
    # the dated copy sits one level down, so its links back up need the ../ prefix
    (DASHBOARDS / "archive" / f"{r['as_of']}.html").write_text(render(r, "../"), encoding="utf-8")
    for isin in r["instruments"]:
        (pages / f"{isin}.html").write_text(instrument_page(isin, r), encoding="utf-8")
    print(f"wrote {out} (+ {len(r['instruments'])} fiches dans {pages}/)")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)
    return 0


def cmd_simulate(args) -> int:
    from .simulate import run
    con = db.connect()
    res = run(con, _read(args.plan))
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_validate(args) -> int:
    d = _read(args.file)
    fn = schema.validate_snapshot if "accounts" in d else schema.validate_instrument
    _, ws = fn(d)
    _warn(ws)
    print("valid")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pfa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("load-snapshot"); s.add_argument("file"); s.set_defaults(fn=cmd_load_snapshot)
    s = sub.add_parser("load-instrument"); s.add_argument("files", nargs="+"); s.set_defaults(fn=cmd_load_instrument)
    s = sub.add_parser("rebuild"); s.set_defaults(fn=cmd_rebuild)
    s = sub.add_parser("export-data")
    s.add_argument("-o", "--output", help="chemin de l'archive (défaut : exports/pfa-export-<date>.zip)")
    s.add_argument("--no-raw", action="store_true", help="sans les réponses brutes d'API (archive plus légère)")
    s.set_defaults(fn=cmd_export_data)
    s = sub.add_parser("import-data")
    s.add_argument("archive")
    s.add_argument("--overwrite", action="store_true", help="remplacer les fichiers existants (anciens sauvegardés)")
    s.add_argument("--dry-run", action="store_true", help="valider l'archive et montrer ce qui serait écrit")
    s.set_defaults(fn=cmd_import_data)
    s = sub.add_parser("setup")
    s.add_argument("--import", dest="archive", help="archive de données à importer (sinon : question)")
    s.add_argument("--yes", action="store_true", help="non interactif : réponses par défaut, pas d'import sans --import")
    s.add_argument("--no-build", action="store_true", help="ne pas compiler l'application web")
    s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("auth-eulerpool")
    s.add_argument("--from-env", action="store_true", help="lit EULERPOOL_API_KEY dans l'environnement")
    s.add_argument("--stdin", action="store_true", help="lit la clé sur l'entrée standard")
    s.add_argument("--status", action="store_true"); s.add_argument("--logout", action="store_true")
    s.set_defaults(fn=cmd_auth_eulerpool)
    s = sub.add_parser("enrich")
    s.add_argument("--isin", action="append", help="limiter à ce fonds détenu (répétable)")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--refresh", action="store_true", help="ignorer le cache")
    s.add_argument("--dry-run", action="store_true", help="estimer le coût sans appeler l'API")
    s.add_argument("--max-calls", type=int)
    s.add_argument("--reserve", type=int, default=20000, help="quota à ne pas entamer")
    s.add_argument("--status", action="store_true", help="état du cache et quota restant")
    s.add_argument("--renormalize", action="store_true",
                   help="recalculer les fiches depuis l'archive brute, sans aucun appel")
    s.set_defaults(fn=cmd_enrich)
    for name, fn in (("fund-companies", cmd_fund_companies), ("company", cmd_company)):
        s = sub.add_parser(name); s.add_argument("isin"); s.add_argument("--as-of")
        s.add_argument("--json", action="store_true"); s.set_defaults(fn=fn)
    s = sub.add_parser("lookthrough"); s.add_argument("--as-of"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_lookthrough)
    s = sub.add_parser("instrument"); s.add_argument("isin"); s.add_argument("--as-of")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_instrument)
    s = sub.add_parser("report"); s.add_argument("--as-of"); s.add_argument("--json", action="store_true")
    s.add_argument("--section", choices=["envelopes", "accounts", "positions", "exposure", "drift_vs_targets",
                                         "concentration", "fees", "returns", "envelope_checks", "history",
                                         "receivables", "perimeter_changes", "exposure_detail"])
    s.set_defaults(fn=cmd_report)
    s = sub.add_parser("gaps"); s.set_defaults(fn=cmd_gaps)
    s = sub.add_parser("dashboard"); s.add_argument("--as-of"); s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_dashboard)
    s = sub.add_parser("simulate"); s.add_argument("plan"); s.set_defaults(fn=cmd_simulate)
    s = sub.add_parser("validate"); s.add_argument("file"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("auth")
    s.add_argument("--status", action="store_true"); s.add_argument("--logout", action="store_true")
    s.set_defaults(fn=cmd_auth)
    s = sub.add_parser("sync")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-dashboard", action="store_true")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("import-transactions")
    s.add_argument("file"); s.add_argument("--format", choices=["bankin-csv"])
    s.add_argument("--since", help="ignore les transactions antérieures (ex. 2025-03-01)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_import_transactions)
    s = sub.add_parser("flows")
    s.add_argument("--month"); s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--review", action="store_true"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_flows)
    s = sub.add_parser("export-reference"); s.set_defaults(fn=cmd_export_reference)
    s = sub.add_parser("runs"); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_runs)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except schema.ValidationError as e:
        print(f"validation error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — surface a clean message, not a traceback, to cron
        from .finary.auth import AuthError
        from .finary.client import FinaryError
        from .finary.mapping import MappingError
        from .sync import SyncError
        if isinstance(e, (AuthError, FinaryError, MappingError, SyncError)):
            print(f"{type(e).__name__}: {e}", file=sys.stderr)
            return 1
        raise
