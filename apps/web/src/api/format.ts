/** Formatting only — never arithmetic on portfolio figures. Those come from the server. */
const nf = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const eur = (v: number | null | undefined, dec = 0) =>
  v === null || v === undefined ? '—' : `${(dec ? nf2 : nf).format(v)} €`;

export const pct = (v: number | null | undefined, dec = 1, signed = false) =>
  v === null || v === undefined ? '—'
    : `${signed && v > 0 ? '+' : ''}${(v * 100).toFixed(dec).replace('.', ',')} %`;

export const signCls = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0 ? '' : v > 0 ? 'up' : 'down';

const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];

export const monthLabel = (ym: string) => {
  const [y, m] = ym.split('-').map(Number) as [number, number];
  return `${MONTHS[m - 1]} ${y}`;
};

export const ENVELOPE_LABELS: Record<string, string> = {
  livret_a: 'Livret A', ldds: 'LDDS', lep: 'LEP', livret_other: 'Autres livrets', pea: 'PEA',
  pea_pme: 'PEA-PME', assurance_vie: 'Assurance-vie', per: 'PER', cto: 'Compte-titres',
  current: 'Comptes courants', crypto: 'Crypto', real_estate: 'Immobilier', other: 'Autre',
};
export const ASSET_LABELS: Record<string, string> = {
  equity: 'Actions', bond: 'Obligations', cash: 'Liquidités', fonds_euros: 'Fonds euros',
  real_estate: 'Immobilier', commodity: 'Matières premières', crypto: 'Crypto', other: 'Autre',
};
export const SECTOR_LABELS: Record<string, string> = {
  'Information Technology': 'Technologie', Financials: 'Finance', 'Health Care': 'Santé',
  'Consumer Discretionary': 'Conso. cyclique', Industrials: 'Industrie',
  'Communication Services': 'Communication', 'Consumer Staples': 'Conso. de base',
  Energy: 'Énergie', Materials: 'Matériaux', Utilities: 'Services publics',
  'Real Estate': 'Immobilier', Other: 'Autre', Unclassified: 'Non documenté',
};
export const REGION_LABELS: Record<string, string> = {
  France: 'France', 'Europe ex-France': 'Europe hors France', 'North America': 'Amérique du Nord',
  Japan: 'Japon', 'Asia-Pacific developed': 'Asie-Pacifique dév.',
  'Emerging markets': 'Émergents', Other: 'Autre', Unclassified: 'Non documenté',
  'Other (tail)': 'Autres pays',
};
export const COUNTRY_LABELS: Record<string, string> = {
  'United States': 'États-Unis', 'United Kingdom': 'Royaume-Uni', Germany: 'Allemagne',
  Switzerland: 'Suisse', Netherlands: 'Pays-Bas', Spain: 'Espagne', Italy: 'Italie',
  Belgium: 'Belgique', Sweden: 'Suède', Denmark: 'Danemark', Finland: 'Finlande',
  Ireland: 'Irlande', Austria: 'Autriche', Japan: 'Japon', China: 'Chine', India: 'Inde',
  'South Korea': 'Corée du Sud', Brazil: 'Brésil', Mexico: 'Mexique', Australia: 'Australie',
  'South Africa': 'Afrique du Sud', 'Saudi Arabia': 'Arabie saoudite', Poland: 'Pologne',
  Portugal: 'Portugal', Thailand: 'Thaïlande', Malaysia: 'Malaisie', Greece: 'Grèce',
  Taiwan: 'Taïwan', Canada: 'Canada', France: 'France', Luxembourg: 'Luxembourg',
  Norway: 'Norvège', Other: 'Autres',
};

/** Bankin' emits its category names in English even on a French account. */
export const CATEGORY_LABELS: Record<string, string> = {
  Home: 'Logement', 'Food & Dining': 'Alimentation & restaurants',
  Entertainment: 'Loisirs', 'Auto & Transport': 'Transport', Shopping: 'Achats',
  Health: 'Santé', Taxes: 'Impôts & taxes', 'Bills & Utilities': 'Factures & abonnements',
  'Misc. expenses': 'Dépenses diverses', 'Personal care': 'Soins personnels',
  'Education & Children': 'Éducation & enfants', 'Business services': 'Services professionnels',
  'Withdrawals, checks & transfer': 'Retraits, chèques & virements', Bank: 'Frais bancaires',
  Incomes: 'Revenus', 'Uncategorized': 'Non catégorisé',
};
export const categoryLabel = (c: string) => {
  const [cat, sub] = c.split(' · ');
  const head = CATEGORY_LABELS[cat!] ?? cat!;
  return sub ? `${head} · ${sub}` : head;
};

export const FLOW_LABELS: Record<string, string> = {
  income: 'Revenus externes', spending: 'Consommation', internal: 'Virements internes',
  refund: 'Remboursements', provisional: 'Retenue provisoire', unclassified: 'Non classé',
};

/** A ratio shown as "2,3 ×". Near zero it keeps two decimals: "-0,0 ×" would hide a net-cash position. */
export const ratioX = (v: number | null | undefined) =>
  v === null || v === undefined ? 'n.d.' : `${v.toFixed(Math.abs(v) > 0 && Math.abs(v) < 0.1 ? 2 : 1).replace('.', ',')} ×`;

/** Plain number with a French decimal comma. */
export const num = (v: number | null | undefined, dec = 1) =>
  v === null || v === undefined ? 'n.d.' : v.toFixed(dec).replace('.', ',');

/** Vendor market cap is in MILLIONS of the listing currency. */
export const marketCap = (m: number | null | undefined, cur?: string | null) => {
  if (m === null || m === undefined) return 'n.d.';
  const c = cur ? ` ${cur}` : '';
  return m >= 1000 ? `${nf.format(Math.round(m / 1000))} Md${c}` : `${nf.format(Math.round(m))} M${c}`;
};

export const SECTOR_NAMES_FR: Record<string, string> = {
  'Information Technology': 'Technologie', Financials: 'Finance', 'Health Care': 'Santé',
  'Consumer Discretionary': 'Conso. cyclique', 'Consumer Staples': 'Conso. de base',
  Industrials: 'Industrie', 'Communication Services': 'Communication', Energy: 'Énergie',
  Materials: 'Matériaux', Utilities: 'Services publics', 'Real Estate': 'Immobilier',
};

/** Colour bucket of a 0-10 quality score (five steps of width 2). Presentation only: the server
 *  computes the distribution itself; this only picks a swatch for a single mark. */
export const qBucket = (score: number | null | undefined): number | null =>
  score === null || score === undefined ? null : Math.min(Math.floor(score / 2), 4);

/** Large money amounts in compact French form (Md = milliard, M = million). */
export const compact = (v: number | null | undefined) => {
  if (v === null || v === undefined) return 'n.d.';
  const a = Math.abs(v);
  const f = (x: number, u: string) => `${(x).toFixed(Math.abs(x) >= 100 ? 0 : 1).replace('.', ',')} ${u}`;
  return a >= 1e12 ? f(v / 1e12, 'Bn') : a >= 1e9 ? f(v / 1e9, 'Md') : a >= 1e6 ? f(v / 1e6, 'M') : nf.format(v);
};
