"""Eulerpool payloads -> normalised records. Pure functions: no network, no disk.

Everything the vendor gets wrong or leaves ambiguous is handled HERE, once, so no screen has to
know about it. The rules come from probing the free key on 2026-11-01:

  * units differ per endpoint -> everything leaves here as FRACTIONS (0.25 = 25 %):
      margins   fractions already        growth   ratios already (26.49 = +2 649 %)
      metrics   margins and dividend yield in PERCENT (71.07), ROE/ROA/ROIC/ROCE fractions
  * valuation multiples (pe, ps, pebit) come back as 0 for companies that obviously have earnings
    -> not stored at all; "n.d." is the honest value, zero is a lie that poisons any average
  * Altman Z of 9999 is a sentinel (no debt to divide by), not a score -> null + flag
  * vendor *models* (fair value, "expected return") are kept apart from facts, in `vendor_models`
"""
from __future__ import annotations

import datetime as dt
import html
import math
from typing import Any

ALTMAN_SENTINEL = 9000.0           # anything above this is a placeholder, not a score
STALE_DAYS = 15 * 31               # a fiscal-year figure older than ~15 months is flagged "ancien"
DESCRIPTION_MAX = 700

# Company endpoints, in the order they are fetched. `profile` first: a 404 there means the vendor
# does not cover the company and the other seven calls are skipped.
COMPANY_ENDPOINTS = {
    "profile": "equity/profile/{isin}",
    "metrics": "equity/metrics/{isin}",
    "margins": "equity/margins/{isin}",
    "growth": "equity/growth/{isin}",
    "aaqs": "equity/aaqs/{isin}",
    "esg": "equity/esg-rating/{isin}",
    "fair_value": "fair-value/by-isin/{isin}",
    "quality": "equity/quality-scores/{ticker}",       # by TICKER, not ISIN (vendor docs)
}

# Controversial-activity flags as the vendor names them. Their exact definitions are not documented,
# which is why the UI says "catégories du fournisseur" and never draws a conclusion from them.
ESG_EXPOSURE_FLAGS = (
    "adultContent", "alcoholic", "animalTesting", "coalEnergy", "firearms", "furLeather", "gambling",
    "gmo", "hazardousSubstances", "militaryContract", "nuclear", "palmOil", "pesticides", "tobacco",
    "catholic",
)


def num(x: Any) -> float | None:
    """A finite float, or None. Strings like "9999.0000" are accepted; NaN and inf are not."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _frac_from_pct(x: Any) -> float | None:
    v = num(x)
    return None if v is None else v / 100.0


def _flag_bool(x: Any) -> bool | None:
    if isinstance(x, bool):
        return x
    if isinstance(x, str) and x.strip().lower() in ("true", "false"):
        return x.strip().lower() == "true"
    return None


def _clean_text(s: Any, limit: int | None = None) -> str | None:
    if not isinstance(s, str) or not s.strip():
        return None
    s = html.unescape(s).strip()
    return s if limit is None or len(s) <= limit else s[:limit].rstrip() + "…"


def _horizons(d: dict, prefix: str, suffixes=("1y", "3y", "5y", "10y"), sep="_") -> dict:
    return {s: num(d.get(f"{prefix}{sep}{s}")) for s in suffixes}


def _age_days(date: str | None, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(str(date)[:10])).days if date else None
    except ValueError:
        return None


def normalize_company(isin: str, raw: dict[str, Any], fetched_at: str) -> dict:
    """`raw` maps an endpoint name (COMPANY_ENDPOINTS) to its JSON payload, or None if unavailable."""
    today = dt.date.fromisoformat(fetched_at[:10])
    flags: list[dict] = []
    sources = [{"endpoint": COMPANY_ENDPOINTS[k].split("{")[0].rstrip("/"), "fetched_at": fetched_at,
                "ok": raw.get(k) is not None} for k in COMPANY_ENDPOINTS if k in raw]

    prof = raw.get("profile") or {}
    met = raw.get("metrics") or {}
    out: dict = {
        "isin": isin,
        "name": _clean_text(prof.get("name")) or isin,
        "ticker": met.get("ticker") or (raw.get("aaqs") or {}).get("ticker"),
        "country": prof.get("country"), "currency": prof.get("currency") or met.get("currency"),
        "sector": _clean_text(prof.get("sector")), "industry": _clean_text(prof.get("industry")),
        "employees": num(prof.get("employees")), "ipo": prof.get("ipo"),
        # vendor unit: millions of the listing currency (NVIDIA 5 016 545 = $5.0T)
        "market_cap_m": num(prof.get("mcap")) if num(prof.get("mcap")) is not None
        else num((met.get("valuation") or {}).get("marketCap")),
        "description": _clean_text(prof.get("description"), DESCRIPTION_MAX),
    }

    p, lev, per = met.get("profitability") or {}, met.get("leverage") or {}, met.get("perShare") or {}
    out["metrics"] = {
        "roe": num(p.get("roe")), "roa": num(p.get("roa")), "roic": num(p.get("roic")),
        "roce": num(p.get("roce")),
        "gross_margin": _frac_from_pct(p.get("grossMargin")),
        "operating_margin": _frac_from_pct(p.get("operatingMargin")),
        "net_margin": _frac_from_pct(p.get("netMargin")),
        "debt_to_equity": num(lev.get("debtToEquity")), "net_debt": num(lev.get("netDebt")),
        "dividend_yield": _frac_from_pct(per.get("dividendYield")), "eps": num(per.get("eps")),
    }

    mg = raw.get("margins") or {}
    out["margins"] = {"gross": _horizons(mg, "grossIncome"), "ebit": _horizons(mg, "ebit"),
                      "net": _horizons(mg, "netIncome")}

    gr = raw.get("growth") or {}

    def growth(prefix: str) -> dict:
        return {"total_3y": num(gr.get(f"{prefix}3Y")), "total_5y": num(gr.get(f"{prefix}5Y")),
                "total_10y": num(gr.get(f"{prefix}10Y")), "pa_3y": num(gr.get(f"{prefix}3YPA")),
                "pa_5y": num(gr.get(f"{prefix}5YPA")), "pa_10y": num(gr.get(f"{prefix}10YPA"))}
    out["growth"] = {"revenue": growth("revenue"), "ebit": growth("ebit"), "income": growth("income")}

    hist = [h for h in (met.get("historical") or []) if isinstance(h, dict) and h.get("year")]
    hist.sort(key=lambda h: h["year"])
    out["history"] = [{"year": int(h["year"]), "period": h.get("period"),
                       "revenue": num(h.get("revenue")), "ebit": num(h.get("ebit")),
                       "net_income": num(h.get("netIncome")), "eps": num(h.get("eps")),
                       "roe": num(h.get("roe")), "roic": num(h.get("roic"))}
                      for h in hist[-10:]]

    aq = raw.get("aaqs") or {}
    ql = raw.get("quality") or {}
    z = num(ql.get("altman_z"))
    altman_valid = z is not None and z < ALTMAN_SENTINEL
    if z is not None and not altman_valid:
        flags.append({"field": "quality.altman",
                      "reason": "valeur sentinelle (≥ 9 000) : score non calculable, écarté"})
    period = ql.get("period_date")
    age = _age_days(period, today)
    if age is not None and age > STALE_DAYS:
        flags.append({"field": "quality.piotroski",
                      "reason": f"période du {str(period)[:10]}, soit {age // 30} mois : donnée ancienne"})
    out["quality"] = {
        "aaqs": {"score": num(aq.get("score")),
                 "revenue_growth_3y_pa": num(aq.get("revenueGrowth3Y")),
                 "revenue_growth_10y_pa": num(aq.get("revenueGrowth10Y")),
                 "ebit_growth_3y_pa": num(aq.get("ebitGrowth3Y")),
                 "ebit_growth_10y_pa": num(aq.get("ebitGrowth10Y")),
                 "net_debt_to_ebit": num(aq.get("netDebtToEBIT")),
                 "ebit_max_drawdown_10y": num(aq.get("ebitMaxDrawdown10Y")),
                 "profit_continuity_10y": num(aq.get("profitContinuity10Y")),
                 "return_on_equity": num(aq.get("returnOnEquity")), "roce": num(aq.get("roce"))},
        "piotroski": {"score": num(ql.get("piotroski_score")),
                      "period_date": str(period)[:10] if period else None},
        "altman": {"z": z if altman_valid else None, "zone": ql.get("altman_zone") if altman_valid else None},
    }

    # Net debt / EBIT < 0 means net cash only when EBIT is positive; with a negative EBIT it is a loss-
    # making company and the ratio says nothing useful. The vendor does not tell the two apart.
    nd = out["quality"]["aaqs"]["net_debt_to_ebit"]
    om = out["metrics"]["operating_margin"]
    if nd is not None and om is not None and om <= 0:
        out["quality"]["aaqs"]["net_debt_to_ebit"] = None
        flags.append({"field": "quality.aaqs.net_debt_to_ebit",
                      "reason": f"marge d'exploitation ≤ 0 : le ratio ({nd:.1f}) n'a pas de sens, écarté"})

    es = raw.get("esg") or {}
    exposures = {k: _flag_bool(es.get(k)) for k in ESG_EXPOSURE_FLAGS if _flag_bool(es.get(k)) is not None}
    co2 = {"scope1": num(es.get("co2EmissionScope1")), "scope2": num(es.get("co2EmissionScope2")),
           "scope3": num(es.get("co2EmissionScope3")), "total": num(es.get("co2EmissionTotal"))}
    out["esg"] = {"environment": num(es.get("environmentScore")), "social": num(es.get("socialScore")),
                  "governance": num(es.get("governanceScore")), "total": num(es.get("totalESGScore")),
                  "co2": co2, "exposures": exposures} if es else None

    fv = raw.get("fair_value") or {}
    out["vendor_models"] = {
        "fair_value": num(fv.get("fairValue")), "fair_value_income": num(fv.get("fairValueIncome")),
        "fair_value_revenue": num(fv.get("fairValueRevenue")),
        "fair_value_dividend": num(fv.get("fairValueDividend")),
        "last_price": num(fv.get("lastPrice")), "upside": _frac_from_pct(fv.get("upside")),
        "expected_return": num(aq.get("expectedReturn")),
    } if (fv or aq) else None

    for name in ("metrics", "margins", "growth", "aaqs", "esg", "fair_value", "quality"):
        if name in raw and raw[name] is None:
            flags.append({"field": name, "reason": "indisponible chez le fournisseur"})
    out["covered"] = covered(raw)
    if not out["covered"]:
        flags.append({"field": "profile", "reason": "société hors couverture du fournisseur"})
    out["flags"] = flags
    out["sources"] = sources
    out["fetched_at"] = fetched_at
    return out


def covered(raw: dict[str, Any]) -> bool:
    """A company with no profile is simply not in the vendor's universe."""
    return bool(raw.get("profile"))


# --------------------------------------------------------------------------- ETF holdings

def normalize_holdings(fund_isin: str, proxy_isin: str, kind: str, rows: list[dict], top_n: int,
                       fetched_at: str, index: str | None = None) -> dict:
    """Top-N constituents by weight. Weights are FRACTIONS of the proxy ETF (vendor gives percent).

    Rows without an ISIN cannot be joined to a company record; they are counted in `n_total` and
    in the coverage denominator (the weights still sum to the whole fund) but cannot be ranked
    into the top N.
    """
    usable = [r for r in rows if isinstance(r, dict) and r.get("isin") and num(r.get("percent")) is not None]
    usable.sort(key=lambda r: -float(r["percent"]))
    top = usable[:top_n]
    updated = sorted({str(r.get("updated_at"))[:10] for r in rows if r.get("updated_at")})
    return {
        "fund_isin": fund_isin, "proxy_isin": proxy_isin, "kind": kind, "index": index,
        "top_requested": top_n,
        "etf_symbol": next((r.get("etf_symbol") for r in rows if r.get("etf_symbol")), None),
        "as_of": updated[-1] if updated else None,
        "n_total": len(rows), "top_n": len(top),
        "coverage_top": sum(float(r["percent"]) for r in top) / 100.0,
        "weights_sum": sum(float(r["percent"]) for r in rows if num(r.get("percent")) is not None) / 100.0,
        "constituents": [{"rank": i + 1, "isin": r["isin"], "name": _clean_text(r.get("name")) or r["isin"],
                          "ticker": r.get("symbol"), "weight": float(r["percent"]) / 100.0}
                         for i, r in enumerate(top)],
        "source": {"endpoint": f"etf/holdings/{proxy_isin}", "fetched_at": fetched_at},
        "fetched_at": fetched_at,
    }


def breakdown_table(rows: list[dict], key: str, normalise) -> dict[str, float]:
    """Vendor breakdown rows -> {normalised bucket: percentage points}, summing buckets that fold together."""
    out: dict[str, float] = {}
    for r in rows:
        if isinstance(r, dict) and num(r.get("exposure")) is not None:
            b = normalise(str(r.get(key)))
            out[b] = out.get(b, 0.0) + float(r["exposure"])
    return out


def crosscheck_tables(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Largest absolute gap, in percentage points, between two NORMALISED breakdowns.

    Measures how good a physical ETF is as a stand-in for a synthetic one. The held fund's side comes
    from the issuer fiche already in data/instruments/ (cited, and the better oracle): the vendor's
    own `etf/sectors|countries` for a synthetic fund is sometimes its collateral basket rather than
    its index (measured 2026-11-14 on the Stoxx 600 and one Nasdaq-100 swap ETF), so it cannot be the
    reference. Both sides are folded through pfa/taxonomy.py first: raw vendor labels differ
    ("Technology" vs "Information Technology"), and comparing them unfolded produced a bogus 32-point gap.
    """
    if not a or not b:
        return None
    return max(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))
