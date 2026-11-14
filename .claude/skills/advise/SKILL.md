---
name: advise
description: Envelope-aware investment guidance — where to put new savings, how to rebalance toward targets, whether to switch a fund — grounded in the deterministic report, the investor profile and cited public data. Use when the user asks what to do with money, how to invest further, whether to buy/sell/switch something, or to set their target allocation.
---

# /advise [amount] [question] — investment guidance

Guidance, not regulated advice: present options with trade-offs; the user decides and executes.

1. **Profile.** Read `profile/investor_profile.md`. If key fields are blank (horizon, risk tolerance,
   emergency fund, monthly savings, goals), ask the user — at most 4 questions in one go — and write the
   answers back to the file with today's date. If `profile/targets.json` still has placeholder values,
   propose targets that fit the profile and confirm them before using them.

2. **State.** `python3 -m pfa report --json` (offer `/snapshot` if stale; `/lookup` if gaps matter).
   Read `reference/fr_envelopes_and_tax.md`; re-verify any rule older than 6 months that the advice
   depends on.

3. **Reason in this order:**
   a. Safety: emergency fund sized vs profile, Livret A/LDDS headroom & rate vs inflation.
   b. Envelope choice: PEA (headroom, 5-year clock, eligibility via synthetic ETFs) → assurance-vie
      (8-year clock, UC fees, fonds euros rate) → others. Tax consequences of any sale.
   c. Allocation: drift vs targets (asset class, region, sector); prefer directing *new money* to
      underweights over selling (no tax event, no PEA closure risk).
   d. Instrument choice: compare 2–3 candidates on TER, replication, tracking, size, PEA eligibility,
      index — run `/lookup` on each candidate and cite sources. Prefer broad, low-cost index funds
      unless the profile says otherwise. Check overlap with existing holdings.
   e. Concentration & risk: single-stock limits, currency exposure, home bias.

4. **Quantify with code.** Write the proposed moves to a plan file (format in `pfa/simulate.py`
   docstring; scratch location e.g. `$TMPDIR/plan.json`, or `journal/plans/<today>-<topic>.json` if
   worth keeping) and run `python3 -m pfa simulate <plan>` — it returns before/after envelopes,
   exposure, drift, fees and concentration without touching the real data. Run `/lookup` first for
   any new ISIN so its breakdown counts. For projections use Finary's `simulate_compound_interest`
   or a short script — state the assumed return and that it is illustrative.

5. **Answer** with: recommendation (amounts per envelope/instrument, as a table), why, what it changes
   (before → after weights from step 4), risks/trade-offs, alternatives considered, and what would
   change the recommendation. Then save it to `journal/<today>-advice-<topic>.md`, including sources.
