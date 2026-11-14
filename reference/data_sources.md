# Public data sources for instrument look-ups

## Boursorama (primary, the project's default preference)
- No public API. Find the page with WebSearch: `site:boursorama.com <ISIN>` (or the fund name).
  Typical paths: `/bourse/trackers/cours/<symbol>/` (ETF), `/bourse/opcvm/cours/<id>/` (funds),
  `/cours/<symbol>/` (stocks). Sub-pages often include composition, performance and fees.
- Useful for: price & performance (1y/3y/5y), fees (frais courants), fund category, SRI, Morningstar
  rating, top holdings, sector/geographic allocation for many OPCVM, PEA eligibility mentions.

## justETF (ETF breakdowns)
- `https://www.justetf.com/fr/etf-profile.html?isin=<ISIN>` — TER, replication (physical/synthetic),
  fund domicile, PEA eligibility filter, **country & sector breakdowns** (top 10 + "Autres").
- For synthetic (swap) PEA ETFs, the breakdown shown is the **index exposure** — that's what we want.

## Issuer factsheets / KID (tie-breaker)
- Amundi, iShares, BNP Paribas AM, Lyxor/Amundi, etc. Monthly factsheet PDFs have full allocations.

## Single stocks
- Country = listing/HQ country (ISIN prefix is a proxy). Sector: Boursorama "secteur" field → GICS
  mapping in `pfa/taxonomy.py`. For multinationals you may note revenue geography in `notes`, but keep
  the breakdown = HQ country for consistency.

## Fonds euros
- Record the yearly served rate (taux servi net de frais) in the journal / instrument notes; no breakdown.

## Recording
Always put URLs + date in `sources`, and the date in `fetched_at`. Weights may be % or fractions.
