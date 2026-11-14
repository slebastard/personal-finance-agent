"""Raw Finary REST payloads -> canonical snapshot (see README.md#canonical-snapshot).

Only arithmetic and lookups live here; no network, no I/O. That makes the whole mapping testable
against archived fixtures, which is the point of replacing the agent step with a script.

Two rules worth stating because they are deliberate, not accidental:

  * An account whose id is absent from profile/account_map.json raises. Finary has no envelope
    concept (PEA, assurance-vie and compte-titres are all `account_type: investment`), so the
    envelope cannot be inferred from the payload. Guessing from the account label would be a
    silent, durable error in every downstream figure; a new account is a decision.
  * A holding type we do not know how to value raises too, rather than being dropped. Silently
    skipping money is worse than failing.
"""
from __future__ import annotations

import datetime as dt

# Finary security_type -> canonical holding kind
SECURITY_KIND = {"etf": "etf", "fund": "fund", "stock": "stock", "bond": "bond"}

# Holding resource types we know how to value. `fiat-holdings` is deliberately omitted from the
# snapshot: the loader synthesises a "Liquidités" line from balance - sum(holdings).
SUPPORTED_HOLDINGS = {"security-holdings", "fond-euro-holdings", "fiat-holdings"}


class MappingError(RuntimeError):
    pass


def _index(included: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r.get("type"), r.get("id")): r for r in included or []}


def _institution_of(asset: dict, idx: dict) -> tuple[str, dict | None]:
    """Resolve asset -> institution_connection -> institution. Returns (name, connection)."""
    ref = (asset.get("relationships") or {}).get("institution_connection", {}).get("data")
    if not ref:
        return "", None                      # manually added account: no connection, never stale
    conn = idx.get(("institution-connections", ref["id"]))
    if not conn:
        return "", None
    inst_ref = (conn.get("relationships") or {}).get("institution", {}).get("data") or {}
    inst = idx.get(("institutions", inst_ref.get("id", "")))
    return ((inst or {}).get("attributes", {}).get("name", ""), conn)


def valuation_date(assets_doc: dict, account_ids: set[str]) -> tuple[str, str | None, list[str]]:
    """as_of = date of the OLDEST successful sync among the accounts we keep.

    Not `date.today()`: the figures are only as current as the last bank sync. A cron running at
    06:00 against a connection last synced yesterday at 10:21 is reporting yesterday's valuation,
    and `as_of` must say so. Manually added accounts have no connection and are excluded from the
    minimum — they are never stale, they are exactly as current as the user left them.
    """
    warnings: list[str] = []
    idx = _index(assets_doc.get("included", []))
    syncs = []
    for a in assets_doc.get("data", []):
        if a["id"] not in account_ids:
            continue
        _, conn = _institution_of(a, idx)
        if conn:
            ts = (conn.get("attributes") or {}).get("last_successful_sync_at")
            if ts:
                syncs.append(ts)
    if not syncs:
        today = dt.date.today().isoformat()
        warnings.append("no bank connection reported a successful sync — as_of falls back to today; "
                        "the valuation date is unverified")
        return today, None, warnings
    oldest = min(syncs)
    return oldest[:10], oldest, warnings


def sync_warnings(assets_doc: dict, account_ids: set[str]) -> list[str]:
    """Connections whose values may be out of date — relayed, never silently accepted."""
    out = []
    idx = _index(assets_doc.get("included", []))
    seen: set[str] = set()
    for a in assets_doc.get("data", []):
        if a["id"] not in account_ids:
            continue
        name, conn = _institution_of(a, idx)
        if not conn or conn["id"] in seen:
            continue
        seen.add(conn["id"])
        at = conn.get("attributes") or {}
        state, status = at.get("state"), at.get("sync_status")
        if status and status != "success":
            out.append(f"{name or 'connexion'} : synchronisation en échec ({status}"
                       + (f" / {state}" if state else "") + ") — valeurs potentiellement périmées")
        elif not at.get("last_successful_sync_at"):
            out.append(f"{name or 'connexion'} : jamais synchronisée avec succès")
    return out


def _holding_rows(doc: dict, account_id: str) -> list[dict]:
    rows = []
    idx = _index(doc.get("included", []))
    for h in doc.get("data", []):
        htype = h.get("type")
        at = h.get("attributes") or {}
        if htype == "fiat-holdings":
            continue                               # loader synthesises the cash line
        if htype == "fond-euro-holdings":
            rows.append({"isin": None, "name": at.get("name") or "Fonds euros",
                         "kind": "fonds_euros", "quantity": None, "unit_price": None,
                         "value": round(float(at["current_value"]), 2), "cost_basis": None})
            continue
        if htype == "security-holdings":
            ref = (h.get("relationships") or {}).get("security", {}).get("data") or {}
            sec = (idx.get(("securities", ref.get("id", ""))) or {}).get("attributes")
            if not sec:
                raise MappingError(f"account {account_id}: security {ref.get('id')} missing from "
                                   "included[] — cannot map the line without its ISIN")
            qty = float(at["quantity"])
            buy = at.get("buying_price")
            rows.append({
                "isin": sec.get("isin"), "name": sec.get("name") or sec.get("isin"),
                "kind": SECURITY_KIND.get(sec.get("security_type"), "other"),
                "quantity": qty,
                "unit_price": round(float(sec["current_price"]), 4) if sec.get("current_price") else None,
                "value": round(float(at["current_value"]), 2),
                # cost_basis is the TOTAL invested; Finary serves the PRU as a per-unit buying_price
                "cost_basis": round(qty * float(buy), 2) if buy is not None else None,
            })
            continue
        raise MappingError(
            f"account {account_id}: unsupported holding type {htype!r}. Add it to mapping.py or put "
            f"the account in the `ignore` list of profile/account_map.json — refusing to drop it "
            f"silently.")
    return rows


def build_snapshot(assets_doc: dict, holdings_by_asset: dict[str, dict], account_map: dict,
                   run_id: str, source: str = "finary-rest") -> tuple[dict, list[str], str | None]:
    """Returns (snapshot, warnings, oldest_sync)."""
    envelopes = account_map.get("accounts") or {}
    ignored = set(account_map.get("ignore") or [])
    warnings: list[str] = []

    kept = [a for a in assets_doc.get("data", []) if a["id"] not in ignored]
    unknown = [a for a in kept if a["id"] not in envelopes]
    if unknown:
        lines = "\n".join(f'    "{a["id"]}": "<enveloppe>",   // {a["attributes"].get("name")} '
                          f'({a["attributes"].get("account_type")})' for a in unknown)
        raise MappingError(
            f"{len(unknown)} compte(s) absent(s) de profile/account_map.json. Finary ne distingue "
            f"pas les enveloppes (PEA, AV et CTO sont tous `investment`), donc elles ne peuvent pas "
            f"être devinées. Ajoute :\n{lines}\n  ou liste l'id dans `ignore`.")

    account_ids = {a["id"] for a in kept}
    as_of, oldest_sync, w = valuation_date(assets_doc, account_ids)
    warnings += w
    warnings += sync_warnings(assets_doc, account_ids)

    idx = _index(assets_doc.get("included", []))
    accounts = []
    for a in kept:
        at = a["attributes"]
        if (at.get("currency") or "EUR") != "EUR":
            raise MappingError(f"account {a['id']} ({at.get('name')}) is in {at['currency']}; "
                               "snapshots are EUR-only — convert upstream or ignore the account")
        institution, _ = _institution_of(a, idx)
        holdings = _holding_rows(holdings_by_asset.get(a["id"], {}), a["id"])
        accounts.append({
            "id": a["id"],
            "name": at.get("name") or a["id"],
            "institution": institution,
            "envelope": envelopes[a["id"]],
            # declared by the OpenAPI schema but not actually served on synced accounts (2026-10-17);
            # kept because it costs nothing if Finary starts populating it
            "opened_on": (at.get("opened_at") or "")[:10] or None,
            "balance": round(float(at["balance"]), 2),
            "holdings": holdings,
        })

    snapshot = {"as_of": as_of, "source": source, "currency": "EUR", "run_id": run_id,
                "accounts": accounts, "cash_flows": []}
    return snapshot, warnings, oldest_sync


def reconcile(snapshot: dict, overview: dict | None) -> dict:
    """Internal consistency, plus a comparison against Finary's own authoritative total.

    The internal check is what catches mapping mistakes (a dropped account, a double-counted
    holding); the external one catches a whole perimeter being wrong.
    """
    total = round(sum(a["balance"] for a in snapshot["accounts"]), 2)
    per_account = []
    for a in snapshot["accounts"]:
        hsum = round(sum(h["value"] for h in a["holdings"]), 2)
        per_account.append({"id": a["id"], "name": a["name"], "balance": a["balance"],
                            "holdings_sum": hsum, "residual": round(a["balance"] - hsum, 2)})
    overspent = [p for p in per_account if p["residual"] < -1]

    overview_total = None
    if overview:
        bs = overview.get("balance_sheet") or {}
        raw = bs.get("owned_gross_assets_effective")
        if raw is not None:
            overview_total = round(float(raw), 2)
    gap = None if overview_total is None else round(total - overview_total, 2)
    gap_pct = None if not overview_total else abs(gap) / overview_total

    return {"total": total, "overview_total": overview_total, "gap": gap, "gap_pct": gap_pct,
            "per_account": per_account,
            "holdings_exceed_balance": overspent}
