"""`pfa enrich`: held funds -> constituents (top N) -> company health records.

Budget model. The free plan is 100 000 units a month. Measured on 2026-11-01: a company endpoint
costs ~1 unit, `etf/holdings` costs 1 600-4 200. So the expensive step is guarded by the remaining
quota read from the response headers, and everything is cached on disk (holdings 30 days, company
records 30 days) so a re-run costs next to nothing.

Everything here is idempotent: the JSON files under data/etf_holdings/ and data/companies/ are the
source of truth, the SQLite tables mirror them, and `pfa rebuild` replays them.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .. import DATA, PROFILE, RAW, db, runs, taxonomy
from . import normalize as N
from .client import Client, EulerpoolError, QuotaExhausted

HOLDINGS_DIR = DATA / "etf_holdings"
COMPANIES_DIR = DATA / "companies"
PROXIES_FILE = PROFILE / "etf_proxies.json"

TTL_DAYS = {"holdings": 30, "company": 30}
RESERVE = 20_000               # 20 % of the free plan is left untouched
HOLDINGS_COST = 4_500          # worst observed: 4 181 units for a 1 266-line ETF
COMPANY_CALLS = len(N.COMPANY_ENDPOINTS)
CROSSCHECK_CALLS = 2           # sectors + countries of the PROXY; the held fund's side is our own fiche
CROSSCHECK_WARN_PTS = 3.0      # a substitute drifting more than this from the held fund is flagged


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)                       # atomic: a crash never leaves half a file


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_proxies(path: Path | None = None) -> dict:
    doc = _read_json(path or PROXIES_FILE) or {}
    return {k: v for k, v in (doc.get("funds") or {}).items() if not k.startswith("_")}


def fresh(doc: dict | None, kind: str, today: dt.date) -> bool:
    if not doc or not doc.get("fetched_at"):
        return False
    try:
        return (today - dt.date.fromisoformat(doc["fetched_at"][:10])).days < TTL_DAYS[kind]
    except ValueError:
        return False


def held_funds(con) -> tuple[str | None, dict[str, str]]:
    """{isin: name} of funds (etf/fund lines) in the latest snapshot."""
    row = con.execute("SELECT MAX(as_of) FROM snapshots").fetchone()
    as_of = row[0] if row else None
    if not as_of:
        return None, {}
    out: dict[str, str] = {}
    for r in con.execute("SELECT isin, name FROM holdings WHERE as_of=? AND isin IS NOT NULL "
                         "AND kind IN ('etf','fund') ORDER BY value DESC", (as_of,)):
        out.setdefault(r["isin"], r["name"])
    return as_of, out


def plan_targets(held: dict[str, str], proxies: dict, only: set[str] | None = None):
    """Split held funds into those we can enrich (with their holdings source) and the rest."""
    targets, skipped = [], []
    for isin, name in held.items():
        if only and isin not in only:
            continue
        cfg = proxies.get(isin)
        if cfg is None:
            skipped.append({"isin": isin, "name": name,
                            "reason": "absent de profile/etf_proxies.json"})
        elif cfg.get("kind") in ("none", "to_find"):
            skipped.append({"isin": isin, "name": name, "reason": cfg.get("note") or cfg["kind"]})
        else:
            source = cfg.get("holdings_from") or isin
            targets.append({"isin": isin, "name": name, "cfg": cfg, "source": source,
                            "kind": cfg.get("kind", "self" if source == isin else "physical_proxy")})
    return targets, skipped


class Archive:
    """Raw responses, verbatim, so the database can always be rebuilt and a vendor change audited."""

    def __init__(self, today: dt.date):
        self.dir = RAW / f"eulerpool-{today.isoformat()}"

    def save(self, path: str, status: int, payload) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9_.-]", "_", path.strip("/").replace("/", "_"))
        (self.dir / f"{slug}.json").write_text(
            json.dumps({"status": status, "payload": payload}, ensure_ascii=False, indent=1),
            encoding="utf-8")


class Budget:
    def __init__(self, client: Client, reserve: int, max_calls: int | None):
        self.client, self.reserve, self.max_calls = client, reserve, max_calls

    def allow(self, cost: int) -> str | None:
        """None if the call may go ahead, otherwise the reason to stop."""
        if self.max_calls is not None and self.client.calls >= self.max_calls:
            return f"plafond --max-calls ({self.max_calls}) atteint"
        rem = self.client.remaining
        if rem is not None and rem - cost < self.reserve:
            return (f"quota restant {rem:,} : sous la réserve de {self.reserve:,} "
                    f"(+ coût estimé {cost:,})").replace(",", " ")
        return None


def _fiche_table(con, isin: str, dimension: str, normalise) -> dict[str, float]:
    """The held fund's breakdown from OUR cited issuer fiche, in percentage points, folded through the taxonomy."""
    out: dict[str, float] = {}
    for r in con.execute("SELECT bucket, weight FROM instrument_breakdowns WHERE isin=? AND dimension=?",
                         (isin, dimension)):
        b = normalise(r["bucket"])
        out[b] = out.get(b, 0.0) + float(r["weight"]) * 100.0
    return out


def estimate(targets: list[dict], today: dt.date, top: int) -> dict:
    """What a run would cost, from the files already on disk. No network."""
    sources_needed: set[str] = set()
    known: set[str] = set()
    unknown_sources = 0
    for t in targets:
        doc = _read_json(HOLDINGS_DIR / f"{t['isin']}.json")
        if fresh(doc, "holdings", today) and doc.get("top_requested") == top:
            known |= {c["isin"] for c in doc["constituents"]}
        else:
            if t["source"] not in sources_needed:
                unknown_sources += 1
            sources_needed.add(t["source"])
    fund_checks = sum(1 for t in targets if t["kind"] == "physical_proxy" and t["source"] in sources_needed)
    stale_known = [i for i in known if not fresh(_read_json(COMPANIES_DIR / f"{i}.json"), "company", today)]
    n_new = len(stale_known) + unknown_sources * top
    calls = len(sources_needed) + fund_checks * CROSSCHECK_CALLS + n_new * COMPANY_CALLS
    quota = len(sources_needed) * HOLDINGS_COST + fund_checks * CROSSCHECK_CALLS + n_new * COMPANY_CALLS
    return {"holdings_to_fetch": sorted(sources_needed), "companies_to_fetch": n_new,
            "calls": calls, "quota_upper_bound": quota}


def _fetch_company(client: Client, archive: Archive, isin: str, ticker_hint: str | None,
                   budget: Budget) -> dict:
    """Up to eight calls. A 404 on `profile` ends it: the vendor simply does not cover the company."""
    raw: dict = {}
    ticker = ticker_hint
    for name, tpl in N.COMPANY_ENDPOINTS.items():
        if name == "quality":
            ticker = (raw.get("metrics") or {}).get("ticker") or (raw.get("aaqs") or {}).get("ticker") or ticker
            if not ticker:
                raw[name] = None
                continue
        stop = budget.allow(1)
        if stop:
            raise QuotaExhausted(stop)
        path = tpl.format(isin=isin, ticker=ticker)
        status, payload, _ = client.get(path)
        archive.save(path, status, payload)
        raw[name] = payload if status == 200 and isinstance(payload, (dict, list)) else None
        if name == "profile" and raw[name] is None:
            for rest in list(N.COMPANY_ENDPOINTS)[1:]:
                raw[rest] = None
            break
    return raw


def run(con, client: Client | None, *, top: int = 25, force: bool = False, dry_run: bool = False,
        max_calls: int | None = None, reserve: int = RESERVE, only: set[str] | None = None,
        today: dt.date | None = None, log=print) -> dict:
    today = today or dt.date.today()
    as_of, held = held_funds(con)
    if not held:
        raise EulerpoolError("aucun fonds détenu : lance d'abord `python3 -m pfa sync`")
    proxies = load_proxies()
    targets, skipped = plan_targets(held, proxies, only)
    est = estimate(targets, today, top)

    log(f"Fonds détenus au {as_of} : {len(held)} · enrichissables : {len(targets)} · non couverts : {len(skipped)}")
    for s in skipped:
        log(f"  – {s['isin']} {s['name'][:48]} : {s['reason']}")
    log(f"Estimation : {est['calls']} appels, ≤ {est['quota_upper_bound']:,} unités de quota "
        f"({len(est['holdings_to_fetch'])} liste(s) de lignes à récupérer, "
        f"{est['companies_to_fetch']} société(s))".replace(",", " "))
    summary = {"as_of": as_of, "targets": len(targets), "skipped": skipped, "estimate": est,
               "funds": {}, "calls": 0, "stopped": None}
    if dry_run or not targets:
        return summary

    assert client is not None
    budget = Budget(client, reserve, max_calls)
    if client.remaining is None:
        client.get("equity/profile/US0378331005")      # one unit, to learn the quota BEFORE the costly calls
    archive = Archive(today)
    run_rec = runs.new("enrich", transport="eulerpool")
    db.upsert_run(con, {**run_rec, "status": "running", "as_of": as_of})
    now = runs.now()
    side_cache: dict[str, list] = {}         # sectors/countries per ISIN, shared across funds

    def breakdown(kind: str, isin: str):
        key = f"{kind}/{isin}"
        if key not in side_cache:
            stop = budget.allow(1)
            if stop:
                raise QuotaExhausted(stop)
            path = f"etf/{kind}/{isin}"
            status, payload, _ = client.get(path)
            archive.save(path, status, payload)
            side_cache[key] = payload if status == 200 and isinstance(payload, list) else []
        return side_cache[key]

    def crosscheck_for(t: dict) -> dict:
        sec = N.crosscheck_tables(
            _fiche_table(con, t["isin"], "sector", taxonomy.sector),
            N.breakdown_table(breakdown("sectors", t["source"]), "industry", taxonomy.sector))
        cty = N.crosscheck_tables(
            _fiche_table(con, t["isin"], "country", taxonomy.country),
            N.breakdown_table(breakdown("countries", t["source"]), "country", taxonomy.country))
        return {"sector_max_gap_pts": sec, "country_max_gap_pts": cty,
                "warn": any(x is not None and x > CROSSCHECK_WARN_PTS for x in (sec, cty)),
                "threshold_pts": CROSSCHECK_WARN_PTS,
                "oracle": "fiche émetteur du fonds détenu (data/instruments)"}

    holdings_cache: dict[str, list] = {}     # one expensive call per proxy, not per fund
    docs: dict[str, dict] = {}
    try:
        for t in targets:
            existing = _read_json(HOLDINGS_DIR / f"{t['isin']}.json")
            if not force and fresh(existing, "holdings", today) and existing.get("top_requested") == top:
                if t["kind"] == "physical_proxy" and not (existing.get("crosscheck") or {}).get("oracle"):
                    # documents written before the crosscheck used the issuer fiche: recompute it from two
                    # cheap calls instead of re-buying the holdings list
                    existing["crosscheck"] = crosscheck_for(t)
                    _write_json(HOLDINGS_DIR / f"{t['isin']}.json", existing)
                    db.load_etf_holdings(con, existing, run_rec["run_id"])
                docs[t["isin"]] = existing
                continue
            if t["source"] not in holdings_cache:
                stop = budget.allow(HOLDINGS_COST)
                if stop:
                    raise QuotaExhausted(stop)
                path = f"etf/holdings/{t['source']}"
                status, payload, _ = client.get(path)
                archive.save(path, status, payload)
                if status != 200 or not isinstance(payload, list):
                    summary["funds"][t["isin"]] = {"error": f"holdings HTTP {status}: {str(payload)[:120]}"}
                    holdings_cache[t["source"]] = []
                else:
                    holdings_cache[t["source"]] = payload
            rows = holdings_cache[t["source"]]
            if not rows:
                continue
            doc = N.normalize_holdings(t["isin"], t["source"], t["kind"], rows, top, now,
                                       index=t["cfg"].get("index"))
            doc["fund_name"] = t["name"]
            if t["kind"] == "physical_proxy":
                doc["crosscheck"] = crosscheck_for(t)
            _write_json(HOLDINGS_DIR / f"{t['isin']}.json", doc)
            db.load_etf_holdings(con, doc, run_rec["run_id"])
            docs[t["isin"]] = doc

        # companies, most important first so a budget stop leaves the biggest names covered
        weight: dict[str, float] = {}
        ticker: dict[str, str | None] = {}
        for d in docs.values():
            for c in d["constituents"]:
                weight[c["isin"]] = max(weight.get(c["isin"], 0.0), c["weight"])
                ticker.setdefault(c["isin"], c.get("ticker"))
        todo = []
        for isin in sorted(weight, key=lambda i: -weight[i]):
            rec = _read_json(COMPANIES_DIR / f"{isin}.json")
            if force or not fresh(rec, "company", today):
                todo.append(isin)
            else:
                db.load_company(con, rec, run_rec["run_id"])
        fetched = 0
        summary["errors"] = []
        for isin in todo:
            try:
                raw = _fetch_company(client, archive, isin, ticker.get(isin), budget)
            except QuotaExhausted:
                raise
            except Exception as e:                      # noqa: BLE001 — one bad company must not abort the run
                summary["errors"].append({"isin": isin, "error": f"{type(e).__name__}: {e}"})
                log(f"  ✗ {isin} ({ticker.get(isin)}) ignorée : {type(e).__name__}: {e}")
                continue
            rec = N.normalize_company(isin, raw, now)
            rec["name"] = rec["name"] if rec["name"] != isin else next(
                (c["name"] for d in docs.values() for c in d["constituents"] if c["isin"] == isin), isin)
            _write_json(COMPANIES_DIR / f"{isin}.json", rec)
            db.load_company(con, rec, run_rec["run_id"])
            fetched += 1
        summary["companies_fetched"] = fetched
    except QuotaExhausted as e:
        summary["stopped"] = str(e)
        log(f"⚠ arrêt : {e}. Relance plus tard : le cache évite de refaire ce qui est fait.")
    finally:
        summary["calls"] = client.calls
        summary["remaining_quota"] = client.remaining
        funds_n = sum(1 for k in docs)
        runs.append({**run_rec, "status": "ok" if not summary["stopped"] else "failed", "as_of": as_of,
                     "accounts_n": funds_n, "holdings_n": summary.get("companies_fetched", 0),
                     "error": (summary["stopped"] or f"{client.calls} appels, quota restant {client.remaining}")})
        db.upsert_run(con, {**run_rec, "status": "ok" if not summary["stopped"] else "failed",
                            "as_of": as_of, "accounts_n": funds_n,
                            "holdings_n": summary.get("companies_fetched", 0),
                            "error": summary["stopped"]})
    for isin, d in docs.items():
        have = sum(1 for c in d["constituents"] if (_read_json(COMPANIES_DIR / f"{c['isin']}.json") or {}).get("covered"))
        summary["funds"][isin] = {"name": d.get("fund_name"), "proxy": d["proxy_isin"],
                                  "companies": f"{have}/{len(d['constituents'])}",
                                  "coverage_top": d["coverage_top"], "crosscheck": d.get("crosscheck")}
        cc = d.get("crosscheck") or {}
        log(f"  ✓ {isin} {str(d.get('fund_name'))[:40]} ← {d['proxy_isin']} : {have}/{len(d['constituents'])} sociétés, "
            f"top {d['top_n']} = {d['coverage_top']*100:.1f} % du fonds"
            + (f" · écart au substitut : secteurs {cc['sector_max_gap_pts']:.1f} pt, pays {cc['country_max_gap_pts']:.1f} pt"
               + (" ⚠ AU-DESSUS DU SEUIL" if cc.get("warn") else "")
               if cc.get("sector_max_gap_pts") is not None and cc.get("country_max_gap_pts") is not None
               else (" · substitut non contrôlé (pas de fiche émetteur du fonds)" if cc else "")))
    if summary.get("errors"):
        log(f"{len(summary['errors'])} société(s) ignorée(s) : relance `enrich` après correction.")
    log(f"Appels : {client.calls} · quota restant : {client.remaining}")
    return summary


def _slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", path.strip("/").replace("/", "_"))


def _latest_raw(path: str) -> dict | None:
    """The newest archived response for an endpoint path, across every eulerpool-<date> folder."""
    f = f"{_slug(path)}.json"
    for d in sorted(RAW.glob("eulerpool-*"), reverse=True):
        doc = _read_json(d / f)
        if doc is not None:
            return doc
    return None


def renormalize(con, log=print) -> int:
    """Rebuild every company record from the ARCHIVED raw responses: no call, no quota.

    This is what the raw archive is for. When a normalisation rule changes (a new sentinel, a
    corrected unit), the data is fixed by replaying, not by paying the vendor again.
    """
    run_id = None
    n = 0
    for p in sorted(COMPANIES_DIR.glob("*.json")) if COMPANIES_DIR.exists() else []:
        old = _read_json(p)
        if not old or not old.get("isin"):
            continue
        isin = old["isin"]
        raw: dict = {}
        ticker = old.get("ticker")
        for name, tpl in N.COMPANY_ENDPOINTS.items():
            if name == "quality" and not ticker:
                raw[name] = None
                continue
            d = _latest_raw(tpl.format(isin=isin, ticker=ticker))
            raw[name] = d["payload"] if d and d.get("status") == 200 and isinstance(d.get("payload"), (dict, list)) else None
            if name == "metrics" and raw[name]:
                ticker = raw[name].get("ticker") or ticker
        rec = N.normalize_company(isin, raw, old["fetched_at"])
        if rec["name"] == isin:
            rec["name"] = old.get("name", isin)
        _write_json(p, rec)
        if run_id is None:
            run_id = f"renormalize-{runs.now()[:10]}"
            db.upsert_run(con, {"run_id": run_id, "kind": "enrich", "status": "imported", "as_of": runs.now()[:10],
                                "error": "records rebuilt from the archived raw responses (no API call)"})
        db.load_company(con, rec, run_id)
        n += 1
    log(f"{n} fiche(s) société recalculées depuis l'archive brute (0 appel)")
    return n


def replay_from_disk(con) -> tuple[int, int]:
    """`pfa rebuild`: reload every holdings/company document under one synthetic run."""
    n_h = n_c = 0
    run_id = None
    for p in sorted(HOLDINGS_DIR.glob("*.json")) if HOLDINGS_DIR.exists() else []:
        doc = _read_json(p)
        if doc and doc.get("fund_isin"):
            if run_id is None:
                run_id = f"rebuild-enrich-{doc['fetched_at'][:10]}"
                db.upsert_run(con, {"run_id": run_id, "kind": "enrich", "status": "imported",
                                    "as_of": doc["fetched_at"][:10],
                                    "error": "documents replayed from data/etf_holdings + data/companies"})
            db.load_etf_holdings(con, doc, run_id)
            n_h += 1
    for p in sorted(COMPANIES_DIR.glob("*.json")) if COMPANIES_DIR.exists() else []:
        doc = _read_json(p)
        if doc and doc.get("isin"):
            if run_id is None:
                run_id = f"rebuild-enrich-{doc['fetched_at'][:10]}"
                db.upsert_run(con, {"run_id": run_id, "kind": "enrich", "status": "imported",
                                    "as_of": doc["fetched_at"][:10],
                                    "error": "documents replayed from data/etf_holdings + data/companies"})
            db.load_company(con, doc, run_id)
            n_c += 1
    return n_h, n_c
