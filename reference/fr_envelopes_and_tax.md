# French envelopes & tax — working reference
VERIFIED_ON: 2026-10-10 (keep in sync with `pfa/rules.py`). Re-verify anything older than 6 months
or anything a decision hinges on. Official sources first: service-public.fr, impots.gouv.fr, info.gouv.fr, AMF.

## Livrets réglementés (tax-free, capital guaranteed, liquid)
| | Rate (since 2026-08-01) | Deposit ceiling |
|---|---|---|
| Livret A | 1.7 % | 22 950 € |
| LDDS | 1.7 % | 12 000 € |
| LEP (income-tested) | 2.5 % | 10 000 € |
Rates are revised by the government (normally Feb 1 / Aug 1). Interest is credited annually (quinzaines rule).
Use: emergency fund + short-term goals. Above the emergency-fund need, idle cash below inflation is a cost.

## PEA (Plan d'Épargne en Actions)
- Deposit ceiling 150 000 € (PEA classique); 225 000 € combined with PEA-PME.
- Eligible: EU/EEA equities and funds ≥ 75 % invested in them — many world/US ETFs are PEA-eligible via
  **synthetic replication** (swap). Check `pea_eligible` per instrument; not all ETFs are.
- Before 5 years: any withdrawal closes the plan (some exceptions); gains taxed at PFU.
- After 5 years: partial withdrawals allowed without closing; gains exempt from income tax, only
  prélèvements sociaux, at the rate in force **at withdrawal** (18.6 % from 2026 after the CSG increase).
- The 5-year clock starts at the first deposit → opening date matters most. Fill `opened_on`.

## Assurance-vie
- No deposit ceiling. Fonds euros (capital guaranteed, annual rate) + unités de compte (UC, not guaranteed).
- Gains taxed only on withdrawal (rachat), pro rata of gains in the amount withdrawn.
- After 8 years: annual allowance on gains of 4 600 € (single) / 9 200 € (couple), then 7.5 % IR on
  deposits ≤ 150 k€ (12.8 % above) + prélèvements sociaux.
- Prélèvements sociaux stay at **17.2 %** for assurance-vie (excluded from the 2026 CSG increase).
- Fees: contract management fees on UC (check Fortuneo Vie's current schedule and record it in
  `profile/manual_inputs.json → account_fees`) + the fund's own TER.
- Estate planning advantages (art. 990 I / 757 B CGI) — mention only if relevant.

## CTO / other income (for comparison)
- PFU 2026: 12.8 % IR + 18.6 % PS = 31.4 % on most capital income (CTO, taxable savings accounts,
  crypto, PEA < 5 y); 30 % remains for assurance-vie. Option for progressive scale possible.

## Rules of thumb the agent should apply
1. Emergency fund on Livret A/LDDS first (size from investor_profile.md).
2. Long-horizon equity → PEA first (tax efficiency after 5 y) while it has ceiling headroom.
3. Assurance-vie for what doesn't fit in the PEA, for non-EU assets not available synthetically,
   for fonds euros / bonds, and for estate planning; mind the 8-year clock and UC fees.
4. Compare total cost = fund TER + wrapper fees.
5. Never recommend selling inside a PEA < 5 y in a way that would close it, without flagging it.

## Sources (2026-10-10)
- Livret A / LDDS / LEP rates from 2026-08-01 — info.gouv.fr
- 2026 CSG increase (PS 18.6 %, AV excluded at 17.2 %, PEA taxed at rate at withdrawal) — nalo.fr, auguste-patrimoine.fr (verify on impots.gouv.fr)
