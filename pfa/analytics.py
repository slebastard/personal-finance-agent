"""Deterministic analytics over the SQLite store. Every number the agent quotes should come from here."""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from . import PROFILE, rules, taxonomy
from .xirr import xirr

DEFAULT_ASSET_CLASS = {
    "stock": "equity", "cash": "cash", "fonds_euros": "fonds_euros", "bond": "bond",
    "scpi": "real_estate", "crypto": "crypto", "other": "other",
    # etf / fund: unknown until looked up -> 'equity' assumed but flagged
    "etf": "equity", "fund": "equity",
}
UNCLASSIFIED = "Unclassified"


def _load_json(name: str, default):
    p = PROFILE / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def snapshot_dates(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT as_of FROM snapshots ORDER BY as_of")]


def _instruments(con) -> dict[str, dict]:
    ins = {r["isin"]: dict(r) for r in con.execute("SELECT * FROM instruments")}
    for r in con.execute("SELECT * FROM instrument_breakdowns"):
        ins.setdefault(r["isin"], {}).setdefault("breakdowns", {}).setdefault(r["dimension"], {})[r["bucket"]] = r["weight"]
    return ins


def instruments_held(con, as_of: str) -> dict[str, dict]:
    """Full instrument records (meta + breakdowns) for the ISINs held at `as_of`.

    `report()` strips breakdowns off each position to keep the payload small; the per-instrument
    dashboard pages need them back, plus the cited sources and notes.
    """
    ins = _instruments(con)
    held = {r["isin"] for r in con.execute(
        "SELECT DISTINCT isin FROM holdings WHERE as_of=? AND isin IS NOT NULL", (as_of,))}
    out = {}
    for isin in held:
        meta = ins.get(isin)
        if not meta:
            continue
        d = dict(meta)
        d["performance"] = json.loads(d.get("performance") or "{}")
        d["sources"] = json.loads(d.get("sources") or "[]")
        d["breakdowns"] = meta.get("breakdowns", {})
        d["pea_eligible"] = None if d.get("pea_eligible") is None else bool(d["pea_eligible"])
        out[isin] = d
    return out


def positions(con, as_of: str) -> list[dict]:
    ins = _instruments(con)
    rows = con.execute(
        "SELECT h.*, a.name AS account_name, a.envelope, a.institution FROM holdings h "
        "JOIN accounts a ON a.id=h.account_id WHERE h.as_of=? ORDER BY h.value DESC", (as_of,)).fetchall()
    total = sum(r["value"] for r in rows) or 1.0
    out = []
    for r in rows:
        p = dict(r)
        meta = ins.get(r["isin"] or "", {})
        p["ter"] = meta.get("ter")
        p["pea_eligible"] = meta.get("pea_eligible")
        p["has_instrument_data"] = bool(meta.get("breakdowns"))
        p["instrument_fetched_at"] = meta.get("fetched_at")
        p["breakdowns"] = meta.get("breakdowns", {})
        p["weight"] = r["value"] / total
        if r["cost_basis"] not in (None, 0):
            p["pnl"] = r["value"] - r["cost_basis"]
            p["pnl_pct"] = p["pnl"] / r["cost_basis"]
        else:
            p["pnl"] = p["pnl_pct"] = None
        out.append(p)
    return out


def _asset_classes(p) -> tuple[dict[str, float], bool]:
    """Return ({asset_class: share}, assumed?)."""
    b = p["breakdowns"].get("asset_class")
    if b:
        return b, False
    kind = p["kind"]
    assumed = kind in ("etf", "fund", "other")
    return {DEFAULT_ASSET_CLASS.get(kind, "other"): 1.0}, assumed


def _geo_sector(p, dim: str) -> dict[str, float] | None:
    b = p["breakdowns"]
    if dim == "country":
        if "country" in b:
            agg = defaultdict(float)
            for k, w in b["country"].items():
                agg[taxonomy.country(k)] += w
            return dict(agg)
        if p["kind"] == "stock" and p["isin"]:   # domicile proxy for single stocks
            return {taxonomy.country({"FR": "France", "US": "United States", "NL": "Netherlands", "DE": "Germany",
                                      "IE": "Ireland", "GB": "United Kingdom", "CH": "Switzerland", "IT": "Italy",
                                      "ES": "Spain", "BE": "Belgium", "LU": "Luxembourg", "JP": "Japan",
                                      "CA": "Canada"}.get(p["isin"][:2], p["isin"][:2])): 1.0}
        return None
    if dim == "region":
        c = _geo_sector(p, "country")
        if c:
            agg = defaultdict(float)
            for k, w in c.items():
                agg[taxonomy.region_of_country(k) if k != "Other" else "Other"] += w
            # if the source also gives an explicit region breakdown, prefer it when country data is mostly 'Other'
            if "region" in b and agg.get("Other", 0) > 0.3:
                agg = defaultdict(float)
                for k, w in b["region"].items():
                    agg[taxonomy.region(k)] += w
            return dict(agg)
        if "region" in b:
            agg = defaultdict(float)
            for k, w in b["region"].items():
                agg[taxonomy.region(k)] += w
            return dict(agg)
        return None
    if dim == "sector":
        if "sector" in b:
            agg = defaultdict(float)
            for k, w in b["sector"].items():
                agg[taxonomy.sector(k)] += w
            return dict(agg)
        return None
    raise ValueError(dim)


def _rows(d: dict[str, float], total: float, order: list[str] | None = None) -> list[dict]:
    items = [(k, v) for k, v in d.items() if abs(v) >= 0.005]
    if order:
        items.sort(key=lambda kv: (kv[0] in (UNCLASSIFIED, "Other"), order.index(kv[0]) if kv[0] in order else 99, -kv[1]))
    else:
        items.sort(key=lambda kv: (kv[0] in (UNCLASSIFIED, "Other"), -kv[1]))
    return [{"bucket": k, "value": round(v, 2), "pct": (v / total if total else 0)} for k, v in items]


def exposure(con, as_of: str) -> dict:
    pos = positions(con, as_of)
    total = sum(p["value"] for p in pos)
    asset = defaultdict(float)
    assumed_ac = []
    risky_total = 0.0
    dims = {"region": defaultdict(float), "country": defaultdict(float), "sector": defaultdict(float)}
    missing = {"region": [], "sector": []}
    for p in pos:
        ac, assumed = _asset_classes(p)
        if assumed:
            assumed_ac.append(p["name"])
        for k, w in ac.items():
            asset[k] += p["value"] * w
        # look-through geography & sectors apply to the equity sleeve
        eq_val = p["value"] * ac.get("equity", 0.0)
        if eq_val <= 0:
            continue
        risky_total += eq_val
        for dim in dims:
            b = _geo_sector(p, dim)
            if not b:
                dims[dim][UNCLASSIFIED] += eq_val
                if dim in missing:
                    missing[dim].append({"name": p["name"], "isin": p["isin"], "value": round(eq_val, 2)})
                continue
            for k, w in b.items():
                dims[dim][k] += eq_val * w
    country_rows = _rows(dims["country"], risky_total)
    head, tail = country_rows[:12], country_rows[12:]
    if tail:
        other = sum(r["value"] for r in tail)
        head.append({"bucket": "Other (tail)", "value": round(other, 2), "pct": other / risky_total})
    return {
        "as_of": as_of,
        "total_value": round(total, 2),
        "equity_value": round(risky_total, 2),
        "asset_class": _rows(asset, total),
        "region": _rows(dims["region"], risky_total, taxonomy.REGIONS),
        "country": head,
        "sector": _rows(dims["sector"], risky_total, taxonomy.GICS),
        "data_gaps": {
            "asset_class_assumed": assumed_ac,
            "no_geography": missing["region"],
            "no_sector": missing["sector"],
            "coverage_geo_pct": 1 - dims["region"].get(UNCLASSIFIED, 0) / risky_total if risky_total else 1,
            "coverage_sector_pct": 1 - dims["sector"].get(UNCLASSIFIED, 0) / risky_total if risky_total else 1,
        },
    }


def exposure_detail(con, as_of: str, watch: dict[str, list[str]] | None = None) -> dict:
    """Where the look-through exposure comes from: per envelope, and line by line for chosen buckets.

    `watch` maps a dimension to the buckets to unpack, default = the ones a user typically worries about
    (United States, Information Technology). Percentages are of the TOTAL equity sleeve, so that the
    contributions of every line add up to the headline figure in `exposure()`.
    """
    watch = watch or {"country": ["United States"], "sector": ["Information Technology"]}
    pos = positions(con, as_of)
    eq_total = 0.0
    env: dict[str, dict] = {}
    contrib: dict[str, list] = {f"{d}:{b}": [] for d, bs in watch.items() for b in bs}
    for p in pos:
        ac, _ = _asset_classes(p)
        eq = p["value"] * ac.get("equity", 0.0)
        if eq <= 0:
            continue
        eq_total += eq
        e = env.setdefault(p["envelope"], {"equity_value": 0.0, "country": defaultdict(float),
                                           "sector": defaultdict(float)})
        e["equity_value"] += eq
        for dim in ("country", "sector"):
            b = _geo_sector(p, dim)
            if not b:
                e[dim][UNCLASSIFIED] += eq
                continue
            for k, w in b.items():
                e[dim][k] += eq * w
        for dim, buckets in watch.items():
            b = _geo_sector(p, dim) or {}
            for bucket in buckets:
                amt = eq * b.get(bucket, 0.0)
                if amt > 0:
                    contrib[f"{dim}:{bucket}"].append({
                        "name": p["name"], "isin": p["isin"], "envelope": p["envelope"],
                        "equity_value": round(eq, 2), "exposure_eur": round(amt, 2),
                        "share_of_line": b.get(bucket, 0.0)})
    for rows in contrib.values():
        rows.sort(key=lambda r: -r["exposure_eur"])
        for r in rows:
            r["pct_of_equity"] = r["exposure_eur"] / eq_total if eq_total else 0.0
    return {
        "as_of": as_of, "equity_value": round(eq_total, 2),
        "by_envelope": {k: {"equity_value": round(v["equity_value"], 2),
                            "country": _rows(v["country"], v["equity_value"])[:8],
                            "sector": _rows(v["sector"], v["equity_value"], taxonomy.GICS)}
                        for k, v in env.items()},
        "contributors": contrib,
    }


def instrument_view(con, isin: str, as_of: str | None = None) -> dict | None:
    """Everything the per-line page shows, for one ISIN: the sourced fiche, my position(s), the
    look-through composition (% of the fund AND euros I hold), and the value history across snapshots.

    Returns None when I hold no such ISIN at `as_of` -- a page for a line I do not own would invite
    reading a fund fiche as a portfolio fact.
    """
    dates = snapshot_dates(con)
    as_of = as_of or (dates[-1] if dates else None)
    if as_of is None:
        return None
    pos = positions(con, as_of)
    lines = [p for p in pos if p["isin"] == isin]
    if not lines:
        return None
    meta = instruments_held(con, as_of).get(isin, {})
    total = sum(p["value"] for p in pos) or 1.0
    value = sum(p["value"] for p in lines)
    costs = [p["cost_basis"] for p in lines if p["cost_basis"] is not None]
    cost = sum(costs) if costs else None
    pnl = round(value - cost, 2) if cost else None
    ter = meta.get("ter")

    first = lines[0]
    ac, _assumed = _asset_classes(first)
    eq_value = value * ac.get("equity", 0.0)
    expo = exposure(con, as_of)

    def fund_rows(d: dict[str, float] | None, base: float, order=None):
        if not d:
            return []
        rows = _rows({k: base * w for k, w in d.items()}, base, order)
        return [{"bucket": r["bucket"], "weight": r["pct"], "eur": r["value"]} for r in rows]

    composition = {
        "equity_value": round(eq_value, 2),
        "asset_class": [{"bucket": k, "weight": w, "eur": round(value * w, 2)}
                        for k, w in sorted(ac.items(), key=lambda kv: -kv[1])],
        "country": fund_rows(_geo_sector(first, "country"), eq_value),
        "region": fund_rows(_geo_sector(first, "region"), eq_value, taxonomy.REGIONS),
        "sector": fund_rows(_geo_sector(first, "sector"), eq_value, taxonomy.GICS),
        # the portfolio-wide equity average, used as a reference mark on the bars
        "portfolio_region": [{"bucket": r["bucket"], "pct": r["pct"]} for r in expo["region"]],
        "portfolio_sector": [{"bucket": r["bucket"], "pct": r["pct"]} for r in expo["sector"]],
    }
    hist = [dict(r) for r in con.execute(
        "SELECT as_of, SUM(value) AS value, SUM(quantity) AS quantity FROM holdings "
        "WHERE isin=? GROUP BY as_of ORDER BY as_of", (isin,))]
    for h in hist:
        h["value"] = round(h["value"], 2)
        h["unit_price"] = round(h["value"] / h["quantity"], 4) if h["quantity"] else None

    return {
        "as_of": as_of, "isin": isin, "name": first["name"], "kind": first["kind"],
        "has_instrument_data": bool(meta),
        "issuer": meta.get("issuer"), "index": meta.get("index"),
        "replication": meta.get("replication"), "ter": ter, "sri": meta.get("sri"),
        "pea_eligible": meta.get("pea_eligible"), "notes": meta.get("notes"),
        "fetched_at": meta.get("fetched_at"),
        "sources": meta.get("sources") or [],
        "performance": meta.get("performance") or {},
        "position": {
            "value": round(value, 2), "weight": value / total,
            "cost_basis": None if cost is None else round(cost, 2),
            "pnl": pnl, "pnl_pct": (pnl / cost) if pnl is not None and cost else None,
            "fee_eur_per_year": round(value * ter, 2) if ter else None,
            "lines": [{"account_name": p["account_name"], "envelope": p["envelope"],
                       "quantity": p["quantity"], "unit_price": p["unit_price"],
                       "cost_basis": p["cost_basis"], "value": round(p["value"], 2),
                       "pnl": None if p["pnl"] is None else round(p["pnl"], 2)} for p in lines],
        },
        "composition": composition,
        "history": hist,
    }


def by_envelope(con, as_of: str) -> list[dict]:
    rows = con.execute(
        "SELECT a.envelope, SUM(v.balance) AS value FROM account_values v JOIN accounts a ON a.id=v.account_id "
        "WHERE v.as_of=? GROUP BY a.envelope ORDER BY value DESC", (as_of,)).fetchall()
    total = sum(r["value"] for r in rows) or 1
    return [{"bucket": r["envelope"], "value": round(r["value"], 2), "pct": r["value"] / total} for r in rows]


def accounts_summary(con, as_of: str) -> list[dict]:
    manual = _load_json("manual_inputs.json", {})
    fees = manual.get("account_fees", {})
    out = []
    for a in con.execute(
            "SELECT a.*, v.balance FROM accounts a JOIN account_values v ON v.account_id=a.id WHERE v.as_of=? "
            "ORDER BY v.balance DESC", (as_of,)):
        h = con.execute("SELECT SUM(value) v, SUM(cost_basis) c, COUNT(*) n, "
                        "SUM(CASE WHEN cost_basis IS NULL THEN 1 ELSE 0 END) nc "
                        "FROM holdings WHERE as_of=? AND account_id=? AND kind NOT IN ('cash')", (as_of, a["id"])).fetchone()
        pnl = (h["v"] - h["c"]) if (h["c"] and h["nc"] == 0) else None
        years = None
        if a["opened_on"]:
            years = (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(a["opened_on"])).days / 365.25
        out.append({
            "id": a["id"], "name": a["name"], "envelope": a["envelope"], "institution": a["institution"],
            "balance": round(a["balance"], 2), "unrealized_pnl": None if pnl is None else round(pnl, 2),
            "unrealized_pnl_pct": (pnl / h["c"]) if pnl is not None and h["c"] else None,
            "age_years": None if years is None else round(years, 2),
            "contract_fee": fees.get(a["id"]),
        })
    return out


def history(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT as_of, total_value FROM snapshots ORDER BY as_of"):
        env = {e["bucket"]: e["value"] for e in by_envelope(con, r["as_of"])}
        out.append({"as_of": r["as_of"], "total": r["total_value"], "by_envelope": env})
    return out


def returns(con, as_of: str) -> dict:
    """Money-weighted return per account and overall between the first snapshot and as_of,
    using recorded cash flows (deposits > 0 in DB = money in; converted to investor convention)."""
    dates = [d for d in snapshot_dates(con) if d <= as_of]
    res = {"from": dates[0] if dates else None, "to": as_of, "accounts": {}, "total": None, "notes": []}
    if len(dates) < 2:
        res["notes"].append("Need >= 2 snapshots for period returns; showing unrealized P&L vs cost basis only.")
        return res
    start = dates[0]
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(as_of)
    all_flows = []
    for a in con.execute("SELECT id FROM accounts"):
        v0 = con.execute("SELECT balance FROM account_values WHERE as_of=? AND account_id=?", (start, a["id"])).fetchone()
        v1 = con.execute("SELECT balance FROM account_values WHERE as_of=? AND account_id=?", (as_of, a["id"])).fetchone()
        if not v1:
            continue
        flows = [(d0, -(v0["balance"] if v0 else 0.0))]
        for f in con.execute("SELECT date, amount FROM cash_flows WHERE account_id=? AND date>? AND date<=?",
                             (a["id"], start, as_of)):
            flows.append((dt.date.fromisoformat(f["date"]), -f["amount"]))
        flows.append((d1, v1["balance"]))
        net_in = -sum(x for _, x in flows[:-1])
        gain = v1["balance"] - net_in
        r = xirr(flows)
        res["accounts"][a["id"]] = {"start_value": v0["balance"] if v0 else 0.0, "end_value": v1["balance"],
                                    "net_contributions": round(net_in - (v0["balance"] if v0 else 0), 2),
                                    "gain": round(gain, 2), "mwr_annualized": r,
                                    "flows_recorded": len(flows) - 2}
        all_flows += flows
    # aggregate: merge flows by date
    agg = defaultdict(float)
    for d, x in all_flows:
        agg[d] += x
    res["total"] = xirr(sorted(agg.items()))
    if not con.execute("SELECT 1 FROM cash_flows LIMIT 1").fetchone():
        res["notes"].append("No cash flows recorded: returns include contributions. Add deposits to "
                            "profile/manual_inputs.json -> cash_flows, then `python3 -m pfa rebuild`.")
    return res


def fees(con, as_of: str) -> dict:
    pos = positions(con, as_of)
    manual = _load_json("manual_inputs.json", {})
    acc_fee = manual.get("account_fees", {})
    fund_fees = 0.0
    covered = 0.0
    investable = 0.0
    wrapper = 0.0
    for p in pos:
        if p["kind"] in ("cash",):
            continue
        investable += p["value"]
        if p["ter"] is not None:
            fund_fees += p["value"] * p["ter"]
            covered += p["value"]
        f = acc_fee.get(p["account_id"])
        if f and p["kind"] != "fonds_euros":
            wrapper += p["value"] * f
    return {
        "fund_fees_eur_per_year": round(fund_fees, 2),
        "weighted_ter_on_covered": (fund_fees / covered) if covered else None,
        "ter_coverage_pct": covered / investable if investable else None,
        "wrapper_fees_eur_per_year": round(wrapper, 2),
    }


def envelope_checks(con, as_of: str) -> list[dict]:
    manual = _load_json("manual_inputs.json", {})
    out = []
    for a in accounts_summary(con, as_of):
        env = a["envelope"]
        if env in ("livret_a", "ldds", "lep"):
            ceiling = {"livret_a": rules.LIVRET_A_CEILING, "ldds": rules.LDDS_CEILING, "lep": rules.LEP_CEILING}[env]
            out.append({"account": a["name"], "check": "ceiling", "value": a["balance"], "limit": ceiling,
                        "headroom": round(max(ceiling - a["balance"], 0), 2),
                        "rate": rules.REGULATED_RATES.get(env),
                        "note": "Ceiling applies to deposits; capitalised interest may push balance above it."})
        if env == "pea":
            contrib = manual.get("pea_contributions_total", {}).get(a["id"])
            out.append({"account": a["name"], "check": "pea_ceiling", "value": contrib,
                        "limit": rules.PEA_CONTRIB_CEILING,
                        "headroom": None if contrib is None else round(rules.PEA_CONTRIB_CEILING - contrib, 2),
                        "note": None if contrib is not None else "Set pea_contributions_total in profile/manual_inputs.json"})
            if a["age_years"] is not None:
                out.append({"account": a["name"], "check": "pea_5y", "value": a["age_years"],
                            "limit": rules.PEA_TAX_MATURITY_YEARS, "ok": a["age_years"] >= rules.PEA_TAX_MATURITY_YEARS})
        if env == "assurance_vie" and a["age_years"] is not None:
            out.append({"account": a["name"], "check": "av_8y", "value": a["age_years"],
                        "limit": rules.AV_TAX_MATURITY_YEARS, "ok": a["age_years"] >= rules.AV_TAX_MATURITY_YEARS})
    return out


def perimeter_changes(con, as_of: str, previous: str | None) -> dict:
    """Accounts that entered or left the perimeter between two snapshots.

    Without this, a closed account reads as a loss: when a current account was closed the total fell
    by a small amount while a much larger balance of perimeter simply left, so the two effects were indistinguishable.
    Detection is automatic (a balance present at `previous` and absent at `as_of`); the *reason* is
    optional context from profile/manual_inputs.json -> closed_accounts.
    """
    out = {"gone": [], "new": [], "note": None}
    if not previous:
        return out
    closed = (_load_json("manual_inputs.json", {}).get("closed_accounts") or {})
    prev = {r["account_id"]: r["balance"] for r in con.execute(
        "SELECT account_id, balance FROM account_values WHERE as_of=?", (previous,))}
    cur = {r["account_id"]: r["balance"] for r in con.execute(
        "SELECT account_id, balance FROM account_values WHERE as_of=?", (as_of,))}
    names = {r["id"]: dict(r) for r in con.execute("SELECT id, name, envelope, institution FROM accounts")}

    for aid in prev.keys() - cur.keys():
        meta = closed.get(aid) or {}
        out["gone"].append({
            "id": aid, "name": names.get(aid, {}).get("name"),
            "envelope": names.get(aid, {}).get("envelope"),
            "institution": names.get(aid, {}).get("institution"),
            "last_balance": round(prev[aid], 2), "last_seen": previous,
            "closed_on": meta.get("closed_on"),
            "reason": meta.get("note") or ("clôturé" if meta else None),
            "transferred_to": meta.get("transferred_to"),
        })
    for aid in cur.keys() - prev.keys():
        out["new"].append({"id": aid, "name": names.get(aid, {}).get("name"),
                           "envelope": names.get(aid, {}).get("envelope"),
                           "balance": round(cur[aid], 2)})

    if out["gone"] or out["new"]:
        delta = round(sum(g["last_balance"] for g in out["gone"])
                      - sum(n["balance"] for n in out["new"]), 2)
        unexplained = [g["name"] or g["id"] for g in out["gone"] if not g["closed_on"]]
        amount = f"{delta:+,.2f}".replace(",", " ")      # format the number, not the sentence
        out["note"] = (f"Le périmètre a changé entre {previous} et {as_of} : {amount} EUR de comptes "
                       f"sortis du périmètre, à ne pas lire comme une performance.")
        if unexplained:
            out["note"] += (" Comptes disparus sans clôture déclarée : " + ", ".join(unexplained)
                            + " — synchronisation cassée ou clôture à enregistrer dans "
                              "profile/manual_inputs.json -> closed_accounts.")
    return out


def receivables(con, as_of: str, total_value: float) -> dict:
    """Money handed over that comes back (rental deposit). Shown BESIDE the Finary total, never in it:
    the total reconciles to the cent with Finary's overview and a hand-entered estimate must not
    contaminate that. The amount paid is read from the transaction, never retyped."""
    items = []
    for r in _load_json("manual_inputs.json", {}).get("receivables") or []:
        tx = con.execute("SELECT date, amount FROM transactions WHERE id=?",
                         (r.get("transaction_id"),)).fetchone()
        if tx and tx["date"] > as_of:
            continue                      # not yet paid at this snapshot
        paid = round(-tx["amount"], 2) if tx else None
        exp = r.get("expected_refund")
        items.append({
            "id": r["id"], "label": r["label"], "kind": r.get("kind"),
            "paid_on": tx["date"] if tx else None, "paid": paid,
            "expected_refund": exp,
            "expected_retention": round(paid - exp, 2) if paid is not None and exp is not None else None,
            "expected_refund_date": r.get("expected_refund_date"),
            "note": r.get("note") if tx else "transaction introuvable : relancer import-transactions",
        })
    exp_total = round(sum(i["expected_refund"] or 0 for i in items), 2)
    return {"items": items,
            "total_paid": round(sum(i["paid"] or 0 for i in items), 2),
            "total_expected_refund": exp_total,
            "total_with_receivables": round(total_value + exp_total, 2)}


def drift(expo: dict) -> dict:
    targets = _load_json("targets.json", {})
    out = {}
    for dim in ("asset_class", "region", "sector"):
        t = targets.get(dim)
        if not t:
            continue
        actual = {r["bucket"]: r["pct"] for r in expo[dim]}
        out[dim] = [{"bucket": k, "target": v, "actual": actual.get(k, 0.0), "drift": actual.get(k, 0.0) - v}
                    for k, v in t.items() if not k.startswith("_")]
    return out


def concentration(con, as_of: str) -> dict:
    pos = [p for p in positions(con, as_of) if p["kind"] not in ("cash", "fonds_euros")]
    tot = sum(p["value"] for p in pos) or 1
    ws = sorted((p["value"] / tot for p in pos), reverse=True)
    stocks = [p for p in pos if p["kind"] == "stock"]
    return {
        "n_positions": len(pos),
        "top1_pct": ws[0] if ws else 0,
        "top5_pct": sum(ws[:5]),
        "hhi": sum(w * w for w in ws),
        "max_single_stock": max(((p["name"], p["value"] / tot) for p in stocks), key=lambda x: x[1], default=None),
    }


def report(con, as_of: str | None = None) -> dict:
    dates = snapshot_dates(con)
    if not dates:
        raise SystemExit("No snapshot loaded yet. Run the /snapshot skill or `python3 -m pfa load-snapshot <file>`.")
    as_of = as_of or dates[-1]
    prev = [d for d in dates if d < as_of]
    expo = exposure(con, as_of)
    total = expo["total_value"]
    prev_total = con.execute("SELECT total_value FROM snapshots WHERE as_of=?", (prev[-1],)).fetchone()[0] if prev else None
    pos = positions(con, as_of)
    for p in pos:
        p.pop("breakdowns", None)
    return {
        "as_of": as_of,
        "previous_as_of": prev[-1] if prev else None,
        "total_value": total,
        "change_vs_previous": None if prev_total is None else round(total - prev_total, 2),
        "envelopes": by_envelope(con, as_of),
        "accounts": accounts_summary(con, as_of),
        "positions": pos,
        "instruments": instruments_held(con, as_of),
        "exposure": expo,
        "exposure_detail": exposure_detail(con, as_of),
        "drift_vs_targets": drift(expo),
        "perimeter_changes": perimeter_changes(con, as_of, prev[-1] if prev else None),
        "receivables": receivables(con, as_of, total),
        "concentration": concentration(con, as_of),
        "fees": fees(con, as_of),
        "returns": returns(con, as_of),
        "envelope_checks": envelope_checks(con, as_of),
        "history": history(con),
        "rules_verified_on": rules.VERIFIED_ON,
    }
