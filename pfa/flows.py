"""Cash-flow classification and aggregation.

Why a classification layer exists at all: Bankin' categorises *what* a transaction is (Food &
Dining, Home…) but not *what nature of flow* it is. Observed on real exports — it can file an account
closure as a salary:

    12/10/2026  +8 000,00 €   Incomes / Salaries   "Vir Jean Dupont Cloture"

Taking its sub-categories at face value overstated monthly savings by 2x and produced months with
near-zero income, which is impossible for a salaried person. The label, not the category, carries
the truth — so rules match on the label first, and the Bankin' sub-category is only a weak prior.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from collections import defaultdict

from . import PROFILE

# "provisional": money handed over that comes back (a rental deposit). Neither consumption nor
# savings -- counting it as spending understated the savings capacity by ~200 EUR/month -- and it
# is mirrored by a receivable in manual_inputs.json so the Portfolio tab can show it.
NATURES = ("income", "spending", "internal", "refund", "provisional", "unclassified")
RULES_FILE = "flow_rules.json"
DEFAULT_REVIEW_THRESHOLD = 2000.0
INCONSISTENCY_FLOOR = 150.0      # below this, a mis-filed category costs nothing

# Only used when no rule matches and the amount is below the review threshold.
_FALLBACK = {True: "income", False: "spending"}


class FlowError(RuntimeError):
    pass


def fold(s: str) -> str:
    """Case- and accent-insensitive, for matching labels written by banks in any style."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def load_rules(path=None) -> dict:
    p = path or (PROFILE / RULES_FILE)
    if not p.exists():
        return {"rules": [], "amount_review_threshold": DEFAULT_REVIEW_THRESHOLD}
    doc = json.loads(p.read_text(encoding="utf-8"))
    rules = [r for r in doc.get("rules", []) if not str(r.get("id", "")).startswith("_")]
    for r in rules:
        if r.get("flow") not in NATURES:
            raise FlowError(f"rule {r.get('id')!r}: flow must be one of {NATURES}")
        if not (r.get("match_label") or r.get("match_subcategory") or r.get("match_category")):
            raise FlowError(f"rule {r.get('id')!r}: needs a match_* criterion")
        if r.get("period") and not {"day_lte", "shift_months"} <= set(r["period"]):
            raise FlowError(f"rule {r.get('id')!r}: period needs day_lte and shift_months")
    return {"rules": rules,
            "amount_review_threshold": float(doc.get("amount_review_threshold",
                                                     DEFAULT_REVIEW_THRESHOLD))}


def classify(tx: dict, rules: dict) -> tuple[str, str | None]:
    """Return (flow, rule_id). Label rules win over category rules; first match wins.

    Two deliberate behaviours:
      * no match -> 'unclassified' is NOT used for small amounts; they fall back to income/spending
        by sign, because flagging 1 500 coffee purchases would drown the review list;
      * no match AND |amount| above the review threshold -> forced 'unclassified'. Empirically the
        biggest one-off items in a window would otherwise be silently counted as consumption,
        which is almost certainly wrong.
    """
    label, sub, cat = fold(tx["label"]), tx.get("subcategory") or "", tx.get("category") or ""
    for r in rules["rules"]:
        pat = r.get("match_label")
        if pat is not None:
            hit = (re.search(pat, label) if r.get("regex") else fold(pat) in label)
            if hit:
                return r["flow"], r["id"]
    for r in rules["rules"]:
        if r.get("match_subcategory") and fold(r["match_subcategory"]) == fold(sub):
            return r["flow"], r["id"]
        if r.get("match_category") and fold(r["match_category"]) == fold(cat):
            return r["flow"], r["id"]
    if abs(tx["amount"]) >= rules["amount_review_threshold"]:
        return "unclassified", None
    return _FALLBACK[tx["amount"] > 0], None


def period_month(tx: dict, rules: dict) -> str | None:
    """Month a flow BELONGS to, when the rule that decided it says it differs from the cash date.

    Bankin' has a "billing month" but its CSV export does not carry it (verified: same dates before
    and after the correction). A salary for month M is paid on the last working day of M, or in the
    first days of M+1 when that day falls on a weekend -- 2025-12-01, 2026-03-03 and 2026-05-04
    are November's, February's and April's. The rule declares `period: {day_lte, shift_months}`.
    Returns None when the cash month is already the right one.
    """
    for r in rules["rules"]:
        if r["id"] != tx.get("rule_id") or not r.get("period"):
            continue
        p = r["period"]
        d = dt.date.fromisoformat(tx["date"])
        if d.day <= int(p["day_lte"]):
            idx = d.year * 12 + d.month - 1 + int(p["shift_months"])
            return f"{idx // 12:04d}-{idx % 12 + 1:02d}"
    return None


def classify_all(rows: list[dict], rules: dict) -> list[dict]:
    for r in rows:
        r["flow"], r["rule_id"] = classify(r, rules)
        r["period_month"] = period_month(r, rules)
    return rows


# --------------------------------------------------------------------------- aggregation

def _months_between(a: str, b: str) -> float:
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return max((d1 - d0).days / 30.44, 1 / 30.44)


def _month_of(r: dict) -> str:
    """Month a row is attributed to in monthly series: income follows its billing period, every
    other nature its cash date. Window totals and reconciliation always use the cash date."""
    return (r.get("period_month") or r["date"][:7]) if r["flow"] == "income" else r["date"][:7]


def aggregate(con, start: str, end: str) -> dict:
    """Flow aggregates for [start, end] inclusive. Every figure here, none in the client."""
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM transactions WHERE date>=? AND date<=? ORDER BY date", (start, end))]

    by_nature = {n: {"amount": 0.0, "count": 0} for n in NATURES}
    cats: dict[str, dict] = {}
    monthly: dict[str, dict] = {}
    for r in rows:
        n = r["flow"]
        by_nature[n]["amount"] = round(by_nature[n]["amount"] + r["amount"], 2)
        by_nature[n]["count"] += 1

        if n == "spending":
            c = cats.setdefault(r["category"] or "(sans catégorie)",
                                {"category": r["category"] or "(sans catégorie)",
                                 "amount": 0.0, "count": 0, "_subs": {}})
            c["amount"] = round(c["amount"] + r["amount"], 2)
            c["count"] += 1
            sk = r["subcategory"] or "(sans sous-catégorie)"
            sub = c["_subs"].setdefault(sk, {"subcategory": sk, "amount": 0.0, "count": 0})
            sub["amount"] = round(sub["amount"] + r["amount"], 2)
            sub["count"] += 1

        mk = _month_of(r)
        m = monthly.setdefault(mk, {"month": mk, "income": 0.0,
                                    "spending": 0.0, "refund": 0.0, "internal": 0.0,
                                    "provisional": 0.0, "unclassified": 0.0, "net": 0.0})
        m[n] = round(m[n] + r["amount"], 2)

    for m in monthly.values():
        m["net"] = round(m["income"] + m["spending"] + m["refund"], 2)

    by_category = sorted(cats.values(), key=lambda c: c["amount"])
    for c in by_category:
        c["subcategories"] = sorted(c.pop("_subs").values(), key=lambda s: s["amount"])

    income = by_nature["income"]["amount"]
    net = round(income + by_nature["spending"]["amount"] + by_nature["refund"]["amount"], 2)
    return {
        "from": start, "to": end,
        "months": round(_months_between(start, end), 2),
        "by_nature": by_nature,
        "by_category": by_category,
        "monthly": [monthly[k] for k in sorted(monthly)],
        "net": net,
        "savings_rate": round(net / income, 4) if income else None,
        "quality": quality(con, rows, start, end),
    }


def quality(con, rows: list[dict], start: str, end: str) -> dict:
    """Two measures that replace judgement, plus the reconciliation against real balances."""
    total_abs = sum(abs(r["amount"]) for r in rows) or 1.0
    unc = sum(abs(r["amount"]) for r in rows if r["flow"] == "unclassified")

    # Σ flows must equal Δ balance when the window is bounded by two snapshots. This validates
    # COMPLETENESS (a truncated export, a missing month), not the classification itself:
    # reclassifying a row does not change the sum. Computed per account and summed, because an
    # export normally covers several accounts.
    gap = None
    per_account = {}
    for acc in sorted({r["account_id"] for r in rows if r["account_id"]}):
        bounds = con.execute(
            "SELECT MIN(as_of), MAX(as_of) FROM account_values WHERE account_id=? "
            "AND as_of>=? AND as_of<=?", (acc, start, end)).fetchone()
        if not (bounds and bounds[0] and bounds[1] and bounds[0] != bounds[1]):
            continue
        v0, v1 = (con.execute(
            "SELECT balance FROM account_values WHERE account_id=? AND as_of=?",
            (acc, b)).fetchone()[0] for b in bounds)
        flux = sum(r["amount"] for r in rows
                   if r["account_id"] == acc and bounds[0] < r["date"] <= bounds[1])
        per_account[acc] = {"from": bounds[0], "to": bounds[1],
                            "gap": round(flux - (v1 - v0), 2)}
    if per_account:
        gap = round(sum(a["gap"] for a in per_account.values()), 2)

    # A salaried month cannot have near-zero external income. Salaries are attributed to their
    # billing month (period_month), so a payroll slipping into the next month no longer leaves a hole;
    # only TWO CONSECUTIVE low months remain a real anomaly.
    per_month: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["flow"] == "income":
            per_month[_month_of(r)] += r["amount"]
    months = sorted(per_month)
    median = sorted(per_month.values())[len(per_month) // 2] if per_month else 0.0
    low = {m for m in months if median and per_month[m] < 0.25 * median}
    # the final month is excluded: an export cut mid-month has simply not been paid yet
    suspicious = sorted(m for i, m in enumerate(months)
                        if m in low and i + 1 < len(months)
                        and (months[i - 1] in low if i else False))

    return {
        "reconciliation_gap": gap,
        "unclassified_amount_pct": round(unc / total_abs, 4),
        "unclassified_count": sum(1 for r in rows if r["flow"] == "unclassified"),
        "months_with_suspicious_income": suspicious,
        "reconciliation_by_account": per_account,
    }


def review_candidates(con, start: str, end: str) -> list[dict]:
    """Transactions likely miscategorised in Bankin'. The script narrows, the agent judges.

    Every signal below was observed on a real export; none is hypothetical.
    """
    rules = load_rules()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM transactions WHERE date>=? AND date<=? ORDER BY ABS(amount) DESC",
        (start, end))]
    # NOT "vir"/"virement": in French banking those cover every transfer, including perfectly
    # ordinary payments to third parties. Only these words actually suggest a move between the
    # user's OWN accounts.
    transfer_words = ("cloture", "clôture", "remplissage", "vidange", "vrst", "versement",
                      "vir intl", "s/ pea", "epargne", "épargne")
    out = []

    # a label seen with several categories across the file is inconsistent somewhere
    seen: dict[str, set] = defaultdict(set)
    for r in con.execute("SELECT label, category FROM transactions"):
        seen[fold(r["label"])].add(r["category"])

    for r in rows:
        why = []
        lab = fold(r["label"])
        # a row an explicit rule already decided is a deliberate choice, not a candidate --
        # without this the salary rows flooded the list with 355 entries
        decided = bool(r["rule_id"])
        if not decided and abs(r["amount"]) >= INCONSISTENCY_FLOOR \
                and any(w in lab for w in transfer_words) \
                and r["flow"] in ("income", "spending"):
            why.append("libellé de virement classé en revenu/dépense")
        if r["flow"] == "unclassified":
            why.append(f"non classé (montant ≥ {rules['amount_review_threshold']:.0f} €)")
        if not decided and (r["subcategory"] or "") == "Salaries" and "vir" not in lab \
                and "paie" not in lab and "salaire" not in lab:
            why.append("sous-catégorie Salaries sans libellé de paie")
        if not decided and (r["subcategory"] or "") == "Refunds" and abs(r["amount"]) >= 1500:
            why.append("remboursement de la taille d'un salaire")
        # an inconsistency floor: the same café filed under two food sub-categories is noise, and
        # without this floor the list came back with 327 entries nobody would read
        if not decided and abs(r["amount"]) >= INCONSISTENCY_FLOOR \
                and len(seen.get(lab, ())) > 1:
            why.append(f"même libellé classé de {len(seen[lab])} façons différentes")
        if why:
            out.append({**{k: r[k] for k in ("id", "date", "label", "amount", "category",
                                            "subcategory", "flow", "rule_id")},
                        "why": why})
    return out
