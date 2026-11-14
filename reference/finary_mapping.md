# Finary → canonical snapshot mapping notes

## Two transports (vérifié le 2026-10-17)

`pfa sync` lit **l'API REST publique** en principal et le **MCP** pour une seule figure.

### REST — `https://public-api.finary.com`
Spec OpenAPI 3.1 servie à `/docs` (UI Scalar). Auth : `Authorization: Bearer <token>`.
En-têtes de quota sur chaque réponse, `429` + `Retry-After` au dépassement.
**Quatre endpoints, et c'est tout** :

```
GET /v1/users/me
GET /v1/profiles
GET /v1/assets                       filter[profile], filter[type]
GET /v1/assets/{asset_id}/holdings   page[limit], page[offset]
```

Sondé et **absent** (404, alors que `/v1/assets` répond 401) : `/v1/portfolio`,
`/v1/portfolio/overview`, `/v1/overview`, `/v1/balance-sheet`, `/v1/net-worth`, `/v1/allocation`,
`/v1/goals`, `/v1/budget`, `/v1/institution-connections`. Le 401-vs-404 est un test d'existence fiable.

### MCP — `https://public-api.finary.com/mcp`
JSON-RPC sur HTTP POST ; un script peut en être le client, aucun agent requis.
Utilisé **uniquement** pour `get_portfolio_overview` : le total faisant autorité
(`balance_sheet.owned_gross_assets_effective`) n'a aucun équivalent REST. C'est la référence de
l'étape de réconciliation.
Autres outils disponibles : `accounts`, `holdings`, `goals`, `profiles`, `get_me`,
`get_budget_overview`, `search_spending`, `simulate_compound_interest`.

**Les réponses `holdings` du MCP ont exactement la forme JSON:API du REST** — d'où un mapper unique
et un repli MCP quasi gratuit si le jeton était refusé sur `/v1/*`.

## OAuth (Clerk)

Découverte : `/.well-known/oauth-protected-resource/mcp` → `https://clerk.finary.com`.

| | |
|---|---|
| Grants annoncés | `authorization_code`, `refresh_token`, `device_code` — **pas de `client_credentials`** |
| Grants réellement accordés par la DCR | `authorization_code`, `refresh_token` **uniquement** — `device_code` est retiré silencieusement, même demandé seul et en `application_type: native`. L'endpoint device rejette alors le client. Le device flow exige un client créé via le dashboard Clerk. |
| Scopes | `openid profile email offline_access` (+ `{public,private}_metadata`) |
| Enregistrement | DCR actif sur `/oauth/register`. `redirect_uris` obligatoire. Le corps doit être un **document JSON** (RFC 7591 §3.1), pas du form-urlencoded : sinon la liste `redirect_uris` est aplatie en sa repr Python et Clerk répond « ['http://…'] is not a valid redirect URI ». `application_type: "native"` est utilisé (RFC 8252 pour une appli CLI) et accepte `http://127.0.0.1:PORT/...` ; le comportement en `web` n'a pas été testé avec un corps JSON correct. |
| Flux utilisé | `authorization_code` + PKCE S256, redirection loopback `http://127.0.0.1:8765/callback` |
| Auth client | `none` accepté → client public, aucun secret |
| Access token | **1 jour** |
| Refresh token | **sans expiration** (doc Clerk) ; rotation non documentée |

Sans `client_credentials`, une autorisation humaine est obligatoire **une fois** ; avec
`offline_access`, elle suffit ensuite indéfiniment — c'est ce qui rend le cron possible.

Exact response shapes are discovered on first use — **update this file** with what you learn
(field names for account type, ISIN, quantity, buy price/PRU, current value, opening date), so later
snapshots map consistently.

## Response shapes (confirmed 2026-10-10, first snapshot)

JSON:API style — `data[]` + `included[]`, every numeric field is a **string**, so cast to float.

`accounts` → `data[].attributes`: `name`, `account_type` (checking / saving / investment), `currency`,
`balance` (full value, string, many decimals), `total_owned_value_eur`, `owners[]`. Institution is a
two-hop lookup: `relationships.institution_connection.data.id` → `included` institution-connection →
`relationships.institution` → `included` institution → `attributes.name`.
Sync freshness lives on the institution-connection (`sync_status`, `last_successful_sync_at`).

`holdings(account_id)` → `data[].attributes` with three `type`s seen so far:
| `type` | fields | maps to |
|---|---|---|
| `security-holdings` | `quantity`, `buying_price` (= **PRU**, per unit), `current_value` | holding, see below |
| `fond-euro-holdings` | `name`, `current_value` (no ISIN, no quantity, no buying price) | `kind: fonds_euros`, `isin: null`, `cost_basis: null` |
| `fiat-holdings` | `quantity`, `current_value` | **omit** — loader synthesizes `Liquidités` from balance − Σ holdings |

Instrument metadata is in `included[]` where `type == "securities"`, keyed by
`data[].relationships.security.data.id`: `isin`, `name`, `security_type` (etf / fund / stock),
`current_price` → `unit_price`, plus `expense_ratio` (TER as a fraction) and `subscription_fees_ratio`
— useful cross-checks for `/lookup`, but **not citable sources**; keep using Boursorama / justETF.

- **`opened_on` : toujours indisponible en pratique** (vérifié sur réponse réelle le 2026-10-17).
  Le schéma OpenAPI déclare `AssetAttributes.opened_at`, mais l'API **ne sert pas la clé** sur les
  comptes synchronisés : la réponse ne contient que `account_type, balance, created_at, currency,
  full_value_eur, name, owned_value_eur, updated_at`. `annual_yield_percent` est absent de la même
  façon. `created_at` reste la date à laquelle Finary a vu le compte, pas la date d'ouverture.
  → les contrôles PEA ≥ 5 ans et AV ≥ 8 ans restent tributaires d'une saisie manuelle.
  (Un passage antérieur de ce fichier annonçait `opened_at` comme disponible : c'était une lecture
  du schéma, pas de la réponse.)
- No cash-flow / transaction history is exposed → `cash_flows` stays `[]`; deposits must be recorded
  by hand in `profile/manual_inputs.json` for XIRR to work.
- Zero-balance accounts return `{"data": []}` — keep them in the snapshot anyway so their ids stay
  stable in history.

## Envelope mapping (fill in from real Finary account types)
Finary has no envelope concept — `account_type` is coarse (PEA, AV and CTO are all `investment`),
so the envelope is mapped **per account id** from the account name.

| Finary account type / name | canonical `envelope` |
|---|---|
| Livret A | livret_a |
| LDD / LDDS | ldds |
| PEA | pea |
| Assurance-vie (Fortuneo Vie) | assurance_vie |
| Compte courant / checking | current |
| Compte-titres | cto |
| Compte espèces (cash leg of the CTO) | cto |

Account ids are Finary UUIDs, specific to each user. They are mapped in `profile/account_map.json`
(private; see `profile/account_map.example.json`) — `pfa sync` refuses an account that is not listed there.

## Holding kind mapping
- ETF/tracker → `etf`; action → `stock`; OPCVM/SICAV/FCP → `fund`; fonds euros → `fonds_euros`;
  uninvested cash in PEA/AV → omit (the loader synthesizes a `Liquidités` line from balance − holdings).

## Cost basis
- `cost_basis` = total amount invested in the line (quantity × PRU), not the unit price.
- Finary serves the PRU as `buying_price` (per unit) → `cost_basis = quantity * buying_price`.
- Fonds euros carry no buying price → `cost_basis: null` (its P&L is not computable from Finary).

## Account ids
- Use Finary's stable account id. Never change ids between snapshots (history is keyed on them).

## `as_of` — date de valorisation, pas date d'exécution

`as_of = min(last_successful_sync_at des connexions retenues).date()`, **pas** `date.today()`.
Les valeurs ne sont fraîches que de la dernière synchro bancaire : un cron à 06:00 face à une
connexion synchronisée la veille à 10:21 rapporte la valorisation de la veille, et `as_of` doit le
dire. Les comptes ajoutés manuellement n'ont pas de connexion et sont exclus du minimum.
Reste une **DATE** : c'est la clé analytique (PK de `snapshots`, composante de celles de `holdings`
et `account_values`). La traçabilité fine vit dans `data/runs.jsonl` et la table `runs`.

## Reconciliation
Snapshot total must equal `get_portfolio_overview.balance_sheet.owned_gross_assets_effective`
(it includes checking accounts, which the narrower `financial_assets` figure excludes).
On 2026-10-10 the two matched to the cent. Per-account sanity check: Σ holdings + residual = balance.

## Reproducing a mapping
`data/raw/<date>/_map.py` is the script that produced that date's snapshot — copy it forward and
adjust rather than mapping by hand, so the arithmetic stays in code.
