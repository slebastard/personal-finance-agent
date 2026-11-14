# personal_finance_agent

A Claude Code project that acts as a personal investment analyst on top of **Finary** (read-only API)
and **Bankin'** (transaction exports), with deterministic Python for every number and a local
client/server web app.

```
          ┌─ WRITE — deterministic Python ──────────────────────────────────┐
Finary ──▶│ pfa sync                → data/raw → data/snapshots → SQLite    │
Bankin'──▶│ pfa import-transactions  → flow classification       → SQLite   │
web    ──▶│ /lookup                  → data/instruments (cited)             │
          └───────────────────────────┬─────────────────────────────────────┘
                                      │ data/finance.db  (rebuildable)
          ┌─ READ — TypeScript ───────▼─────────────────────────────────────┐
          │ apps/server   Nest   repository → service → controller          │
          │ apps/web      React + Vite + ECharts   ·  tabs: Portfolio · Flux│
          └─────────────────────────────────────────────────────────────────┘
            Claude: /review /advise /review-transactions ──▶ journal/*.md
```

Python writes and stays the **oracle**; TypeScript only reads. A parity test compares every figure
the API serves to the output of `pfa report --json` / `pfa flows --json`, to the cent.

## Démarrage sur une machine neuve

Ce dépôt contient le **code** et les **skills** de Claude Code, jamais les données de l'utilisateur
(voir « Confidentialité »). Prérequis : Python ≥ 3.10 (bibliothèque standard seulement, aucun
`pip install`), **Node ≥ 22.13** et **pnpm** (`corepack enable` fournit pnpm), [Claude Code](https://claude.com/claude-code).

```
git clone git@github.com:slebastard/personal-finance-agent.git
cd personal-finance-agent
# (facultatif) dépose ici ton archive de données : pfa-export-AAAAMMJJ-HHMMSS.zip
python3 -m pfa setup
```

`pfa setup` crée l'arborescence, te demande **si tu disposes d'une archive de données** (`.zip`
produite par `pfa export-data`) et, si oui, l'importe et reconstruit la base SQLite ; sinon il crée
tes fichiers de profil à partir des modèles `profile/*.example.*` et une base vide. Il propose enfin
`pnpm install && pnpm build` et active le garde-fou de confidentialité (hook pre-commit).
Options : `--import ARCHIVE`, `--yes` (non interactif), `--no-build`.

Puis `pnpm serve` → http://127.0.0.1:3001.

### Première utilisation (sans archive)

1. `python3 -m pfa auth` — connexion OAuth unique à Finary (authorization_code + PKCE, scope
   `offline_access`). Une page à valider dans le navigateur ; le refresh token va dans le **trousseau
   macOS** (service `pfa-finary`), jamais dans un fichier. `PFA_CREDENTIALS_FILE` bascule sur un fichier
   `0600` si tu as besoin de portabilité (Linux, serveur distant).
2. Renseigne `profile/account_map.json` : UUID de compte Finary → enveloppe. Finary ne distingue pas
   les enveloppes, donc `pfa sync` **échoue** sur un compte absent plutôt que de deviner.
3. Remplis `profile/investor_profile.md` (ou laisse `/advise` t'interroger) et confirme `profile/targets.json`.
4. Ajoute ce que Finary ignore à `profile/manual_inputs.json` (versements PEA, frais du contrat
   d'assurance-vie, historique de versements pour des rendements justes), puis `python3 -m pfa rebuild`.
5. `python3 -m pfa sync` → `/lookup` → `/review`.

### Sauvegarder et déplacer tes données

```
python3 -m pfa export-data                 # → exports/pfa-export-AAAAMMJJ-HHMMSS.zip
python3 -m pfa export-data --no-raw        # sans les réponses brutes d'API (archive plus légère)
python3 -m pfa import-data ARCHIVE.zip --dry-run   # valider et voir ce qui serait écrit
python3 -m pfa import-data ARCHIVE.zip     # restaurer, puis reconstruire la base
python3 -m pfa import-data ARCHIVE.zip --overwrite # remplacer l'existant (anciennes versions sauvegardées)
```

L'archive contient les **sources de vérité** : profil, historique des snapshots (Finary n'a pas d'API
d'historique : ce qui n'est pas archivé est perdu), fiches de fonds, enrichissement des sociétés,
transactions telles que classées (`transactions.jsonl`) et exports Bankin' d'origine, ledger de
provenance, réponses brutes, journal. La base SQLite n'en fait pas partie : `pfa rebuild` la recrée.
**Jamais exportés** : la clé Eulerpool et le jeton Finary (trousseau macOS — sur la nouvelle machine,
refais `python3 -m pfa auth` et `auth-eulerpool`), l'enregistrement OAuth propre à la machine, les
fichiers générés.

> ⚠ L'archive **n'est pas chiffrée** et contient toute ta situation financière : range-la dans un endroit
> sûr (disque chiffré, coffre-fort), jamais dans le dépôt (`*.zip` est ignoré par git).

À l'import, l'archive est traitée comme une entrée **non fiable** : aucun contenu n'est exécuté, chaque
chemin est vérifié contre une liste blanche (pas de chemin absolu, pas de `..`, pas de lien symbolique,
rien hors des dossiers connus), chaque fichier doit figurer au manifest avec une somme SHA-256 exacte,
et un fichier non listé est refusé. En cas de doute, rien n'est écrit.

### En cron (optionnel)

```cron
30 11 * * *  cd ~/Documents/misc/personal_finance_agent && /usr/bin/python3 -m pfa sync >> data/logs/cron.log 2>&1
```

Après 11 h : les connexions Fortuneo se synchronisent vers 10 h, et `as_of` suit la synchro la plus
ancienne, pas l'horloge. Le trousseau doit être déverrouillé (donc session ouverte) — à vérifier au
premier run planifié. `python3 -m pfa runs` montre l'historique et les échecs.

## Lancer l'application web

```
pnpm serve      # http://127.0.0.1:3001 — API + client sur une seule origine
```

C'est **la** commande au quotidien. Le serveur n'écoute que sur `127.0.0.1` et n'a aucune
authentification : il sert des données financières personnelles, il n'a rien à faire sur une
interface publique.

```
pnpm dev        # dev : Vite sur 5173 (proxy /api) + Nest en watch
pnpm test       # arrondis + PARITÉ TypeScript vs `pfa report|flows --json`
pnpm typecheck  # tous les paquets
```

Après un `pfa sync` ou un `pfa import-transactions`, **rafraîchir la page suffit** : le serveur relit
la base à chaque requête (et rouvre le fichier si `pfa rebuild` l'a remplacé). Rien à régénérer.

Routes : `GET /api/v1/{health,meta,report,exposure,positions,instruments/:isin}`,
`GET /api/v1/flows{,/transactions,/savings-capacity}`.

### Interface

Un rail latéral à icônes (Patrimoine, Flux) qui se déplie au survol, au focus clavier ou au clic sur le logo ;
une barre du haut (date du dernier snapshot, nom d'utilisateur, thème) ; des boîtes séparées par un écart
fixe sur un fond à points. Le thème suit le système par défaut, avec bascule **système / clair / sombre**
mémorisée. Courbes et barres sont en émeraude ; les gains et pertes ont leurs propres couleurs, toujours
accompagnées d'une flèche et du signe. Le nom affiché vient de `display_name` dans `profile/manual_inputs.json`.

### Onglet Portefeuille

Total, Δ depuis le snapshot précédent, changement de périmètre, plus-value latente, frais, et
l'exposition transparisée (classes d'actifs, régions, secteurs, pays) avec le trait de cible.
« Par enveloppe » est un donut : une part par vecteur (PEA, AV, livrets, comptes courants), total au
centre. La couleur est fixée **par enveloppe** (`ENVELOPE_SLOT`), jamais par rang, et l'anneau est
dessiné dans l'ordre des slots — ce qui garantit que les paires de teintes voisines restent celles
validées pour la vision des couleurs et le contraste sur fond, en clair et en sombre (voir l'en-tête
de `apps/web/src/theme.css`). Au-delà de 6 enveloppes, la queue est repliée dans « Autres ».

Chaque graphique a son **jumeau tabulaire** : une infobulle enrichit une valeur, elle n'en est
jamais le seul accès.

Cliquer une ligne du tableau « Lignes » ouvre sa page (`#/instruments/<ISIN>`) : ta position (quantité,
cours, prix de revient, plus-value, frais en €/an), la composition du fonds par pays, régions et secteurs
(bascule **% du fonds ↔ € chez moi**, trait = moyenne de ta poche actions), la performance publiée
(1 / 3 / 5 ans), l'évolution de ta valeur snapshot par snapshot, et la fiche avec ses sources citées.
Les chiffres viennent de `pfa instrument <ISIN> --json`, comparés au serveur par le test de parité.

> **Pas encore là :** les principales positions du fonds et les rendements par année civile (il faut étendre
> `/lookup`), et une courbe de cours (aucune source gratuite propre). La courbe de ta valeur n'a que les
> snapshots déjà archivés : Finary n'a pas d'API d'historique. Les rendements (XIRR) et les plafonds
> d'enveloppe ne sont pas encore servis non plus (`envelopeChecks` renvoie `[]`).

### Onglet Flux

Sélection de période (présets, mois révolu, plage libre), puis revenus / consommation / épargne
nette, tendance mensuelle, dépenses par catégorie avec bascule sous-catégories, et les virements
internes isolés. Un encart « À arbitrer » montre ce qui n'est pas classé plutôt que de le ranger par
défaut, avec trois indicateurs de qualité : part non classée, écart de réconciliation (Σ flux vs
Δ solde entre deux snapshots) et mois à revenu suspect.

## Daily use

| You say | What happens |
|---|---|
| `pfa sync` | **Script déterministe** : REST `/v1/*` + overview MCP → brut archivé → mapping → réconciliation → chargement. Prêt pour cron. |
| `/snapshot` | Enveloppe mince : lance `pfa sync` et commente le résultat |
| `/lookup` | Fills missing ISIN data (composition, TER, PEA eligibility) from Boursorama / justETF |
| `/review` | Performance + exposure + fees + envelope review → `journal/<date>-review.md` |
| `/review-transactions` | Après un export Bankin' : pointe les transactions probablement mal catégorisées, propose des règles |
| `/learn` | Éducation financière progressive sur ton portefeuille réel ; journal de prédictions ; jamais de reco de titre |
| `/advise 3000 € this month` | Envelope-aware allocation of new money, simulated before/after → journal |
| free questions | "Quelle est mon exposition aux US ?", "Dois-je remplir mon PEA avant mon AV ?" |

## Sociétés derrière mes fonds (Eulerpool)

```
python3 -m pfa auth-eulerpool --from-env   # une fois : clé -> trousseau macOS (jamais dans un fichier)
python3 -m pfa enrich --dry-run            # estimer le coût en appels et en quota
python3 -m pfa enrich                      # constituants (top 25) + santé de chaque société
python3 -m pfa enrich --status             # âge du cache, couverture, quota restant
```

Chaque fonds de `profile/etf_proxies.json` est décomposé en ses 25 premières sociétés. Pour un ETF
**synthétique**, la liste « officielle » est un panier de collatéral, pas l'indice : on s'appuie donc sur un
ETF **physique du même indice** (approximation, étiquetée et mesurée par un écart secteurs/pays).

Dans l'application : la page d'une ligne (`#/instruments/<ISIN>`) gagne le treemap des sociétés (couleur =
note de qualité), la santé pondérée du fonds, la répartition des notes et un nuage croissance × marge ;
`#/companies/<ISIN>` est la fiche d'une société (historique, marges, croissance, qualité, ESG, modèles du
fournisseur à part) ; l'onglet Portefeuille ajoute « Sociétés derrière mes fonds » (top expositions
consolidées par fonds d'origine, recouvrements, qualité moyenne, couverture). Les « pistes pour aller plus
loin » sont tirées d'un catalogue déterministe (`reference/learning_prompts.json`) et renvoient à `/learn`.

Les données du fournisseur sont **secondaires** : valeurs de valorisation écartées (renvoyées à 0),
sentinelles filtrées, scores et valeurs justes = modèles non publiés, affichés pour l'éducation seulement.
Quota gratuit : 100 000 unités par mois ; la liste de lignes d'un ETF en coûte de 1 600 à 4 200.

## Flux de trésorerie (Bankin')

```
python3 -m pfa import-transactions <export.csv> [--dry-run]
python3 -m pfa flows [--month 2026-02 | --start D --end D] [--json]
python3 -m pfa flows --review               # candidats de recatégorisation
```

Bankin' n'a **pas d'API** pour un particulier (`bankin.com/developers` → 404, `api.bankin.com`
n'existe pas ; seul Bridge, leur offre B2B sous contrat, en expose une). L'export CSV périodique
(offre Plus) est donc la voie supportée, pas un contournement.

Bankin' catégorise ce **qu'est** une transaction, pas la **nature** du flux — il a classé une clôture
de compte en salaire et les versements PEA en « loyer ». La classification en *income / spending /
internal / refund* se fait donc sur le **libellé**, via `profile/flow_rules.json`, la sous-catégorie
ne servant que de signal faible. Au-delà de `amount_review_threshold` (2 000 €), une transaction sans
règle explicite est forcée en `unclassified` et **affichée**, au lieu d'être comptée en consommation.

L'id d'une transaction est un hash de `(date, libellé, montant, compte, occurrence)` et **exclut la
catégorie** : recatégoriser dans Bankin' puis ré-importer **met à jour** la ligne au lieu de la
dupliquer.

## Provenance

`data/runs.jsonl` (append-only) est la source de vérité : chaque run y écrit son `run_id`, son
statut, ses totaux et son écart de réconciliation, et chaque ligne financière en base porte ce
`run_id`. `pfa rebuild` rejoue le ledger ; la table `runs` n'en est que l'index.

## Canonical snapshot

`data/snapshots/YYYY-MM-DD.json`
```json
{
  "as_of": "2026-10-10",
  "source": "finary-mcp",
  "currency": "EUR",
  "accounts": [
    {"id": "<finary account id>", "name": "PEA Fortuneo", "institution": "Fortuneo",
     "envelope": "pea", "opened_on": "2019-03-15", "balance": 47500,
     "holdings": [
       {"isin": "FR0011871128", "name": "…", "kind": "etf", "quantity": 680, "unit_price": 48.0,
        "value": 32640, "cost_basis": 24600}
     ]},
    {"id": "<id>", "name": "Livret A", "institution": "Fortuneo", "envelope": "livret_a", "balance": 23150}
  ],
  "cash_flows": [{"account_id": "<id>", "date": "2026-06-10", "amount": 3600, "note": "versement"}]
}
```
- `envelope` ∈ livret_a, ldds, lep, livret_other, pea, pea_pme, assurance_vie, per, cto, current, crypto, real_estate, other
- `kind` ∈ etf, stock, fund, fonds_euros, bond, cash, scpi, crypto, other
- `cost_basis` is the total invested in the line. Uninvested cash = balance − Σ holdings (auto line).
- `as_of` is derived from the **oldest bank sync**, not from the clock.

## Instrument file

`data/instruments/<ISIN>.json`
```json
{
  "isin": "FR0011871128", "name": "…", "kind": "etf",
  "ter": 0.0015, "pea_eligible": true, "replication": "synthetic", "index": "S&P 500",
  "breakdowns": {
    "asset_class": {"equity": 1.0},
    "country": {"Etats-Unis": 97.5, "Autres": 2.5},
    "sector": {"Technologie de l'information": 33, "Finance": 13}
  },
  "performance": {"1y": 0.12, "3y_annualized": 0.11, "5y_annualized": 0.13},
  "sources": [{"url": "https://www.justetf.com/fr/etf-profile.html?isin=FR0011871128", "fetched_at": "2026-10-10"}],
  "fetched_at": "2026-10-10",
  "notes": "Synthetic replication; breakdown = index exposure."
}
```
Weights may be % or fractions; missing remainder becomes "Other". FR/EN names are normalized to GICS
sectors and regions in `pfa/taxonomy.py`.

## Tests

```
python3 -m unittest discover tests     # pipeline end-to-end sur des fixtures (PFA_ROOT jetable)
pnpm test                              # arrondis + parité TS vs Python
```

Le test de parité démarre le vrai serveur sur la vraie base et compare chaque chiffre servi à
`pfa report --json` / `pfa flows --json` : une divergence d'un centime fait échouer la suite. C'est
ce qui autorise à faire confiance au front sans relire le SQL.

## Confidentialité

- **Le dépôt ne contient que du code, des skills et des modèles de profil** (`profile/*.example.*`).
  `.gitignore` exclut `data/`, `journal/`, `dashboards/`, `exports/`, les archives `*.zip`, les bases,
  les fichiers de profil réels et `.env`.
- **Un garde-fou en trois couches** (`scripts/check_no_personal_data.py`, hook pre-commit et CI) refuse
  un commit contenant un chemin privé, une adresse e-mail, un IBAN valide, un jeton d'API, une clé
  privée, un UUID de compte, ou un terme de **ta liste locale** `.privacy-denylist` (non versionnée :
  ton nom, ton employeur, tes identifiants de compte).
- Les secrets (jeton Finary, clé Eulerpool) vivent dans le trousseau de l'OS, jamais dans un fichier.
- Les données d'un fournisseur tiers (Eulerpool) ne sont pas redistribuées : elles restent locales.
- Les notes de conception qui citent des chiffres réels restent hors du dépôt (`PLAN-*.md`, `SPEC-*.md`).
