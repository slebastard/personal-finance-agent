"""Canonical formats + validation (no third-party deps).

Two files are written by the agent and validated here:

1. Snapshot  — data/snapshots/YYYY-MM-DD.json  (mapped from Finary MCP output)
2. Instrument — data/instruments/<ISIN>.json   (from Boursorama / justETF lookups)

See README.md for annotated examples.
"""
from __future__ import annotations

import datetime as dt
import re

ENVELOPES = {
    "livret_a", "ldds", "lep", "livret_other",   # regulated / savings accounts
    "pea", "pea_pme",                            # equity savings plans
    "assurance_vie", "per",                      # insurance wrappers / retirement
    "cto",                                       # compte-titres ordinaire
    "current", "crypto", "real_estate", "other",
}
CASH_LIKE_ENVELOPES = {"livret_a", "ldds", "lep", "livret_other", "current"}

HOLDING_KINDS = {"etf", "stock", "fund", "fonds_euros", "bond", "cash", "scpi", "crypto", "other"}

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

DIMENSIONS = ("asset_class", "region", "country", "sector")
ASSET_CLASSES = {"equity", "bond", "cash", "fonds_euros", "real_estate", "commodity", "crypto", "other"}


class ValidationError(ValueError):
    pass


def _date(v, where):
    try:
        return dt.date.fromisoformat(str(v))
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"{where}: invalid ISO date {v!r}") from e


def _num(v, where, allow_none=False, min_=None):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValidationError(f"{where}: expected number, got {v!r}")
    if min_ is not None and v < min_:
        raise ValidationError(f"{where}: must be >= {min_}, got {v}")
    return float(v)


def isin_checksum_ok(isin: str) -> bool:
    """Luhn check on the ISIN digit expansion."""
    if not ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def validate_snapshot(doc: dict) -> tuple[dict, list[str]]:
    """Return (normalized_doc, warnings). Raises ValidationError on hard errors."""
    warnings: list[str] = []
    if not isinstance(doc, dict):
        raise ValidationError("snapshot must be a JSON object")
    as_of = _date(doc.get("as_of"), "as_of").isoformat()
    if doc.get("currency", "EUR") != "EUR":
        raise ValidationError("only EUR snapshots are supported (convert upstream)")
    accounts = doc.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValidationError("accounts must be a non-empty list")

    seen = set()
    out_accounts = []
    for i, a in enumerate(accounts):
        w = f"accounts[{i}]"
        aid = str(a.get("id") or "").strip()
        if not aid:
            raise ValidationError(f"{w}.id required (stable id from Finary)")
        if aid in seen:
            raise ValidationError(f"{w}.id duplicated: {aid}")
        seen.add(aid)
        env = a.get("envelope")
        if env not in ENVELOPES:
            raise ValidationError(f"{w}.envelope must be one of {sorted(ENVELOPES)}, got {env!r}")
        balance = _num(a.get("balance"), f"{w}.balance")
        holdings_in = a.get("holdings") or []
        holdings = []
        for j, h in enumerate(holdings_in):
            hw = f"{w}.holdings[{j}]"
            kind = h.get("kind", "other")
            if kind not in HOLDING_KINDS:
                raise ValidationError(f"{hw}.kind must be one of {sorted(HOLDING_KINDS)}")
            isin = (h.get("isin") or "").strip().upper() or None
            if isin and not isin_checksum_ok(isin):
                warnings.append(f"{hw}: ISIN {isin} fails checksum — check mapping")
            key = isin or f"{aid}:{kind}:{(h.get('name') or j)}"
            holdings.append({
                "key": key,
                "isin": isin,
                "name": str(h.get("name") or key),
                "kind": kind,
                "quantity": _num(h.get("quantity"), f"{hw}.quantity", allow_none=True),
                "unit_price": _num(h.get("unit_price"), f"{hw}.unit_price", allow_none=True),
                "value": _num(h.get("value"), f"{hw}.value"),
                "cost_basis": _num(h.get("cost_basis"), f"{hw}.cost_basis", allow_none=True),
            })
        # Cash-like accounts or uninvested cash: synthesize a cash line so totals reconcile.
        hsum = sum(h["value"] for h in holdings)
        residual = round(balance - hsum, 2)
        if not holdings:
            kind = "cash" if env in CASH_LIKE_ENVELOPES else "other"
            holdings.append({"key": f"{aid}:balance", "isin": None, "name": f"{a.get('name')} (solde)",
                             "kind": kind, "quantity": None, "unit_price": None,
                             "value": balance, "cost_basis": None})
        elif abs(residual) >= 1:
            if residual > 0:
                holdings.append({"key": f"{aid}:cash", "isin": None, "name": "Liquidités",
                                 "kind": "cash", "quantity": None, "unit_price": None,
                                 "value": residual, "cost_basis": None})
            else:
                warnings.append(f"{w}: holdings exceed balance by {-residual:.2f} € — balance kept as-is")
        out_accounts.append({
            "id": aid,
            "name": str(a.get("name") or aid),
            "institution": str(a.get("institution") or ""),
            "envelope": env,
            "opened_on": _date(a["opened_on"], f"{w}.opened_on").isoformat() if a.get("opened_on") else None,
            "balance": balance,
            "holdings": holdings,
        })

    flows = []
    for k, f in enumerate(doc.get("cash_flows") or []):
        fw = f"cash_flows[{k}]"
        if f.get("account_id") not in seen:
            raise ValidationError(f"{fw}.account_id unknown: {f.get('account_id')!r}")
        flows.append({"account_id": f["account_id"], "date": _date(f.get("date"), fw).isoformat(),
                      "amount": _num(f.get("amount"), f"{fw}.amount"), "note": f.get("note")})

    # run_id travels inside the snapshot so `pfa rebuild` can restore provenance after dropping the DB
    run_id = doc.get("run_id")
    if run_id is not None and not str(run_id).strip():
        raise ValidationError("run_id must be a non-empty string when present")
    return {"as_of": as_of, "source": doc.get("source", "finary-mcp"), "currency": "EUR",
            "run_id": str(run_id) if run_id else None,
            "accounts": out_accounts, "cash_flows": flows}, warnings


def _normalize_weights(d: dict, where: str, warnings: list[str]) -> dict[str, float]:
    """Accepts weights as fractions (0-1) or percents (0-100). Pads to 1 with 'Other'."""
    if not isinstance(d, dict) or not d:
        return {}
    vals = {str(k).strip(): _num(v, f"{where}.{k}", min_=0) for k, v in d.items()}
    total = sum(vals.values())
    if total > 1.5:  # percents
        vals = {k: v / 100 for k, v in vals.items()}
        total /= 100
    if total > 1.02:
        warnings.append(f"{where}: weights sum to {total:.3f} > 1 — rescaled")
        vals = {k: v / total for k, v in vals.items()}
    elif total < 0.98:
        vals["Other"] = vals.get("Other", 0) + (1 - total)
    return vals


def validate_instrument(doc: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    isin = str(doc.get("isin") or "").upper()
    if not isin_checksum_ok(isin):
        raise ValidationError(f"invalid ISIN {isin!r}")
    kind = doc.get("kind", "other")
    if kind not in HOLDING_KINDS:
        raise ValidationError(f"kind must be one of {sorted(HOLDING_KINDS)}")
    b_in = doc.get("breakdowns") or {}
    breakdowns = {}
    for dim in DIMENSIONS:
        if dim in b_in:
            breakdowns[dim] = _normalize_weights(b_in[dim], f"breakdowns.{dim}", warnings)
    unknown = set(b_in) - set(DIMENSIONS)
    if unknown:
        warnings.append(f"ignored breakdown dimensions: {sorted(unknown)}")
    if "asset_class" in breakdowns:
        bad = set(breakdowns["asset_class"]) - ASSET_CLASSES
        if bad:
            raise ValidationError(f"asset_class buckets must be in {sorted(ASSET_CLASSES)}; got {sorted(bad)}")
    else:
        warnings.append("no asset_class breakdown — defaulting from kind")
    if not doc.get("sources"):
        warnings.append("no sources[] — add the URLs you read so numbers are traceable")
    fetched = doc.get("fetched_at") or dt.date.today().isoformat()
    perf = doc.get("performance") or {}
    return {
        "isin": isin,
        "name": str(doc.get("name") or isin),
        "kind": kind,
        "ter": _num(doc.get("ter"), "ter", allow_none=True),
        "pea_eligible": doc.get("pea_eligible"),
        "replication": doc.get("replication"),
        "index": doc.get("index"),
        "issuer": doc.get("issuer"),
        "sri": doc.get("sri"),
        "performance": {k: _num(v, f"performance.{k}", allow_none=True) for k, v in perf.items()},
        "breakdowns": breakdowns,
        "sources": doc.get("sources") or [],
        "fetched_at": _date(fetched, "fetched_at").isoformat(),
        "notes": doc.get("notes"),
    }, warnings
