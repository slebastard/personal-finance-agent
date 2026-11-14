---
name: review
description: Produce a portfolio review — performance (P&L, money-weighted returns vs benchmarks), look-through asset-class/geographic/sector exposure, concentration, fees, envelope status and drift vs targets — and save it to the journal. Use when the user asks how their investments are doing, what their exposure is, or for a monthly/quarterly review.
---

# /review — performance & exposure review

1. **Freshness.** `python3 -m pfa report --section history`. If the latest snapshot is > 7 days old,
   offer `/snapshot` first. If `pfa gaps` is non-empty, say coverage is partial (or run `/lookup`).

2. **Numbers:** `python3 -m pfa report --json`. Every figure you cite comes from this output.

3. **Benchmarks (public data).** For the period covered by `returns.from → returns.to`, fetch the
   return of 1–2 relevant references (e.g. MSCI World / ACWI ETF in EUR via Boursorama or justETF; the
   Livret A rate from `pfa/rules.py` for cash; the Fortuneo Vie fonds euros served rate). Cite them.

4. **Write** `journal/<today>-review.md` with these sections (concise, tables welcome):
   - **Snapshot** — total, Δ, split by envelope.
   - **Perimeter** — read `perimeter_changes` BEFORE commenting on Δ. An account that left the
     perimeter (closed, or a dropped connection) shows up there with the balance it last had. Never
     report that amount as a gain or a loss: subtract it from Δ and say so explicitly. If `gone[]`
     has an entry with `closed_on: null`, treat it as a suspected broken sync and flag it rather
     than assuming money vanished.
   - **Performance** — unrealized P&L by line & account, MWR per account and overall vs benchmarks.
     If no cash flows are recorded, state that period returns include deposits.
   - **Exposure** — asset class; region & sector of the equity sleeve; top countries; coverage %.
     Point out concentrations (single stock > 10 %, one country > 65 %, one sector > 30 %) and
     home bias (France vs its ~3 % weight in world indices).
   - **Costs** — fund TER + wrapper fees in €/year; most expensive lines.
   - **Envelopes** — Livret A ceiling, PEA ceiling headroom and 5-year status, AV 8-year status.
   - **Drift vs targets** (if `profile/targets.json` set).
   - **Watch list** — 3 bullets max of things worth acting on (no execution details; that's /advise).

5. `python3 -m pfa dashboard`, then reply with a 5–8 line summary and the journal path.
