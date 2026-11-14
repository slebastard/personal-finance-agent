"""Company-level look-through: which companies stand behind my funds, and how healthy are they.

Every figure the web app shows about companies is computed HERE (Python is the oracle; the Nest
server mirrors these formulas and a parity test compares them). The client only formats.

Definitions, so a reader can check any number:

  equity_eur(fund)        value of my lines in the fund x the fund's equity share
  exposure(company, fund) equity_eur(fund) x the company's weight in the fund's constituent list
  coverage_top(fund)      sum of the weights of the listed constituents (e.g. 37.2 % for a top 25)
  identified_eur          sum over funds of equity_eur x coverage_top = sum of every company exposure
  weighted mean (metric)  sum(w x) / sum(w) over the constituents that HAVE the metric. A missing
                          value is excluded, never counted as zero; the weight share that has it is
                          reported next to every mean (`coverage`).
  weighted quantile       the smallest value whose cumulative weight reaches q x total weight
                          (values ascending); p25 / p50 / p75 are reported as the dispersion.

Funds with no constituent list (active funds, bonds, no physical twin) are reported as NOT covered,
with their equity euros: the gap is a first-class figure, not a footnote.
"""
from __future__ import annotations

import json

from . import analytics
from .eulerpool import enrich as _enrich

METRICS = {
    "roe": ("metrics", "roe"),
    "roic": ("metrics", "roic"),
    "operating_margin": ("metrics", "operating_margin"),
    "net_margin": ("metrics", "net_margin"),
    "net_debt_to_ebit": ("quality", "aaqs", "net_debt_to_ebit"),
    "revenue_growth_3y_pa": ("growth", "revenue", "pa_3y"),
    "aaqs_score": ("quality", "aaqs", "score"),
    "esg_total": ("esg", "total"),
}
QUALITY_BUCKETS = ("0–2", "2–4", "4–6", "6–8", "8–10")


def _dig(doc: dict | None, path: tuple):
    cur = doc
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None


def quality_bucket(score: float) -> int:
    """AAQS is 0-10; five buckets of width 2, the top bucket closed at 10."""
    return min(int(score // 2), 4)


def weighted_stats(pairs: list[tuple[float, float | None]], denominator: float | None = None) -> dict:
    """`pairs` = (weight, value-or-None). See the module docstring for the definitions."""
    have = sorted(((x, w) for w, x in pairs if x is not None and w > 0), key=lambda p: p[0])
    total_all = denominator if denominator is not None else sum(w for w, _ in pairs)
    w_have = sum(w for _, w in have)
    if not have or w_have <= 0:
        return {"mean": None, "p25": None, "p50": None, "p75": None, "coverage": 0.0, "n": 0}

    def q(p: float) -> float:
        target, cum = p * w_have, 0.0
        for x, w in have:
            cum += w
            if cum >= target - 1e-12:
                return x
        return have[-1][0]
    return {"mean": sum(w * x for x, w in have) / w_have,
            "p25": q(0.25), "p50": q(0.50), "p75": q(0.75),
            "coverage": (w_have / total_all) if total_all else 0.0, "n": len(have)}


def _company(con, isin: str) -> dict | None:
    r = con.execute("SELECT data FROM companies WHERE isin=?", (isin,)).fetchone()
    return json.loads(r["data"]) if r else None


def _summary(rec: dict | None) -> dict:
    """The few fields a table row needs, so a list of 25 does not ship 25 full records."""
    if not rec:
        return {"covered": False, "sector": None, "country": None, "market_cap_m": None,
                "currency": None, "flags": 0, **{m: None for m in METRICS},
                "piotroski": None}
    return {"covered": bool(rec.get("covered", True)), "sector": rec.get("sector"),
            "country": rec.get("country"), "market_cap_m": rec.get("market_cap_m"),
            "currency": rec.get("currency"), "flags": len(rec.get("flags") or []),
            **{m: _dig(rec, p) for m, p in METRICS.items()},
            "piotroski": _dig(rec, ("quality", "piotroski", "score"))}


def _fund_equity(pos: list[dict], isin: str) -> tuple[float, float, str | None]:
    """(value of my lines, equity euros, name) for one held ISIN."""
    lines = [p for p in pos if p["isin"] == isin]
    if not lines:
        return 0.0, 0.0, None
    ac, _ = analytics._asset_classes(lines[0])
    value = sum(p["value"] for p in lines)
    return value, value * ac.get("equity", 0.0), lines[0]["name"]


def _not_covered_reason(cfg: dict) -> str:
    """Why a fund has no constituent list: by declaration (active fund, no twin), or simply not run yet."""
    if cfg.get("kind") in ("none", "to_find") or not cfg:
        return cfg.get("note") or "absent de profile/etf_proxies.json"
    return "pas encore enrichi : lance `python3 -m pfa enrich`"


def _holdings_doc(con, fund_isin: str) -> dict | None:
    r = con.execute("SELECT data FROM etf_holdings WHERE fund_isin=?", (fund_isin,)).fetchone()
    return json.loads(r["data"]) if r else None


def fund_companies(con, fund_isin: str, as_of: str | None = None) -> dict | None:
    dates = analytics.snapshot_dates(con)
    as_of = as_of or (dates[-1] if dates else None)
    if not as_of:
        return None
    pos = analytics.positions(con, as_of)
    value, eq, name = _fund_equity(pos, fund_isin)
    if name is None:
        return None
    cfg = _enrich.load_proxies().get(fund_isin) or {}
    doc = _holdings_doc(con, fund_isin)
    if doc is None:
        return {"as_of": as_of, "fund_isin": fund_isin, "fund_name": name, "covered": False,
                "reason": _not_covered_reason(cfg),
                "proxy": {"kind": cfg.get("kind"), "isin": cfg.get("holdings_from"),
                          "index": cfg.get("index")}}
    rows, pairs = [], {m: [] for m in METRICS}
    dist = [0.0] * 5
    for c in doc["constituents"]:
        rec = _company(con, c["isin"])
        s = _summary(rec)
        rows.append({"rank": c["rank"], "isin": c["isin"], "name": (rec or {}).get("name") or c["name"],
                     "ticker": c.get("ticker"), "weight": c["weight"], "eur": round(eq * c["weight"], 2),
                     **s})
        for m in METRICS:
            pairs[m].append((c["weight"], s[m]))
        if s["aaqs_score"] is not None:
            dist[quality_bucket(s["aaqs_score"])] += c["weight"]
    cov = doc["coverage_top"]
    with_data = sum(r["weight"] for r in rows if r["covered"])
    return {
        "as_of": as_of, "fund_isin": fund_isin, "fund_name": name, "covered": True,
        "proxy": {"kind": doc.get("kind"), "isin": doc.get("proxy_isin"), "index": doc.get("index"),
                  "note": cfg.get("note"), "crosscheck": doc.get("crosscheck")},
        "holdings_as_of": doc.get("as_of"), "fetched_at": doc.get("fetched_at"),
        "n_total": doc["n_total"], "top_n": doc["top_n"], "coverage_top": cov,
        "equity_value": round(eq, 2), "position_value": round(value, 2),
        "constituents": rows,
        "companies_with_data": sum(1 for r in rows if r["covered"]),
        "weight_with_data": with_data,
        "health": {m: weighted_stats(pairs[m], denominator=cov) for m in METRICS},
        "quality_distribution": [{"bucket": QUALITY_BUCKETS[i], "weight": dist[i]} for i in range(5)],
        "source": doc.get("source"),
    }


def _held_funds_with_equity(con, as_of: str) -> list[dict]:
    pos = analytics.positions(con, as_of)
    seen, out = set(), []
    for p in pos:
        if p["isin"] and p["kind"] in ("etf", "fund") and p["isin"] not in seen:
            seen.add(p["isin"])
            value, eq, name = _fund_equity(pos, p["isin"])
            if eq > 0:
                out.append({"isin": p["isin"], "name": name, "equity": eq})
    return out


def lookthrough(con, as_of: str | None = None, limit: int = 200) -> dict | None:
    dates = analytics.snapshot_dates(con)
    as_of = as_of or (dates[-1] if dates else None)
    if not as_of:
        return None
    expo = analytics.exposure(con, as_of)
    equity_total = expo["equity_value"]
    proxies = _enrich.load_proxies()
    funds, not_covered = [], []
    companies: dict[str, dict] = {}
    holdings: dict[str, dict] = {}
    for f in _held_funds_with_equity(con, as_of):
        doc = _holdings_doc(con, f["isin"])
        cfg = proxies.get(f["isin"]) or {}
        if doc is None:
            not_covered.append({"isin": f["isin"], "name": f["name"], "equity_value": round(f["equity"], 2),
                                "reason": _not_covered_reason(cfg)})
            continue
        holdings[f["isin"]] = {c["isin"]: c["weight"] for c in doc["constituents"]}
        funds.append({"isin": f["isin"], "name": f["name"], "color_slot": cfg.get("color_slot"),
                      "index": doc.get("index"), "proxy_isin": doc.get("proxy_isin"),
                      "equity_value": round(f["equity"], 2), "coverage_top": doc["coverage_top"],
                      "identified_eur": round(f["equity"] * doc["coverage_top"], 2)})
        for c in doc["constituents"]:
            eur = f["equity"] * c["weight"]
            e = companies.setdefault(c["isin"], {"isin": c["isin"], "name": c["name"], "ticker": c.get("ticker"),
                                                 "exposure_raw": 0.0, "funds": []})
            e["exposure_raw"] += eur
            e["funds"].append({"fund_isin": f["isin"], "fund_name": f["name"], "weight": c["weight"],
                               "eur": round(eur, 2)})
    identified = sum(f["equity"] * next(x["coverage_top"] for x in funds if x["isin"] == f["isin"])
                     for f in _held_funds_with_equity(con, as_of) if f["isin"] in holdings)
    rows = []
    for e in sorted(companies.values(), key=lambda e: -e["exposure_raw"]):
        rec = _company(con, e["isin"])
        s = _summary(rec)
        rows.append({"isin": e["isin"], "name": (rec or {}).get("name") or e["name"], "ticker": e["ticker"],
                     "exposure_eur": round(e["exposure_raw"], 2),
                     "pct_of_equity": (e["exposure_raw"] / equity_total) if equity_total else 0.0,
                     "funds": e["funds"], "n_funds": len(e["funds"]), **s})
    top10 = sum(e["exposure_raw"] for e in sorted(companies.values(), key=lambda e: -e["exposure_raw"])[:10])

    overlaps = []
    ids = sorted(holdings)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = holdings[ids[i]], holdings[ids[j]]
            common = set(a) & set(b)
            if common:
                overlaps.append({"a": ids[i], "b": ids[j], "common": len(common),
                                 "overlap_weight": sum(min(a[k], b[k]) for k in common)})
    # health weighted by MY exposure (euros), not by any fund's weights
    pairs = {m: [(e["exposure_raw"], _summary(_company(con, e["isin"]))[m]) for e in companies.values()]
             for m in METRICS}
    dist = [0.0] * 5
    for e in companies.values():
        sc = _summary(_company(con, e["isin"]))["aaqs_score"]
        if sc is not None:
            dist[quality_bucket(sc)] += e["exposure_raw"]
    return {
        "as_of": as_of, "equity_value": round(equity_total, 2),
        "identified_eur": round(identified, 2),
        "identified_pct": (identified / equity_total) if equity_total else 0.0,
        "funds": funds, "funds_not_covered": not_covered,
        "companies": rows[:limit], "n_companies": len(rows),
        "n_shared": sum(1 for e in companies.values() if len(e["funds"]) >= 2),
        "top10_pct_of_equity": (top10 / equity_total) if equity_total else 0.0,
        "top10_pct_of_identified": (top10 / identified) if identified else 0.0,
        "overlaps": overlaps,
        "quality": {m: weighted_stats(pairs[m], denominator=identified) for m in METRICS},
        "quality_distribution": [{"bucket": QUALITY_BUCKETS[i],
                                  "weight": (dist[i] / identified) if identified else 0.0} for i in range(5)],
    }


def company_view(con, isin: str, as_of: str | None = None) -> dict | None:
    rec = _company(con, isin)
    if rec is None:
        return None
    lt = lookthrough(con, as_of, limit=10_000)
    held = next((c for c in (lt["companies"] if lt else []) if c["isin"] == isin), None)
    return {"as_of": lt["as_of"] if lt else None, "company": rec,
            "held": None if held is None else {
                "exposure_eur": held["exposure_eur"], "pct_of_equity": held["pct_of_equity"],
                "funds": held["funds"]}}
