"""Render a self-contained HTML dashboard (inline SVG, no network, no deps) from analytics.report()."""
from __future__ import annotations

import datetime as dt
import html
import json
import math
from collections import defaultdict

from . import taxonomy

ENVELOPE_LABELS = {
    "livret_a": "Livret A", "ldds": "LDDS", "lep": "LEP", "livret_other": "Autres livrets", "pea": "PEA",
    "pea_pme": "PEA-PME", "assurance_vie": "Assurance-vie", "per": "PER", "cto": "Compte-titres",
    "current": "Comptes courants", "crypto": "Crypto", "real_estate": "Immobilier", "other": "Autre",
}
ASSET_LABELS = {"equity": "Actions", "bond": "Obligations", "cash": "Liquidités", "fonds_euros": "Fonds euros",
                "real_estate": "Immobilier", "commodity": "Matières premières", "crypto": "Crypto", "other": "Autre"}

SECTOR_LABELS = {
    "Information Technology": "Technologie", "Financials": "Finance", "Health Care": "Santé",
    "Consumer Discretionary": "Conso. cyclique", "Industrials": "Industrie", "Communication Services": "Communication",
    "Consumer Staples": "Conso. de base", "Energy": "Énergie", "Materials": "Matériaux", "Utilities": "Services publics",
    "Real Estate": "Immobilier", "Other": "Autre", "Unclassified": "Non documenté",
}
# taxonomy.country() normalises to canonical English names; the UI is French.
COUNTRY_LABELS = {
    "United States": "États-Unis", "United Kingdom": "Royaume-Uni", "Germany": "Allemagne",
    "Switzerland": "Suisse", "Netherlands": "Pays-Bas", "Spain": "Espagne", "Italy": "Italie",
    "Belgium": "Belgique", "Sweden": "Suède", "Denmark": "Danemark", "Norway": "Norvège",
    "Finland": "Finlande", "Ireland": "Irlande", "Austria": "Autriche", "Japan": "Japon",
    "China": "Chine", "India": "Inde", "South Korea": "Corée du Sud", "Brazil": "Brésil",
    "Mexico": "Mexique", "Australia": "Australie", "New Zealand": "Nouvelle-Zélande",
    "Singapore": "Singapour", "South Africa": "Afrique du Sud", "Saudi Arabia": "Arabie saoudite",
    "United Arab Emirates": "Émirats arabes unis", "Poland": "Pologne", "Portugal": "Portugal",
    "Indonesia": "Indonésie", "Thailand": "Thaïlande", "Malaysia": "Malaisie", "Chile": "Chili",
    "Turkey": "Turquie", "Greece": "Grèce", "Canada": "Canada", "France": "France",
    "Taiwan": "Taïwan", "Israel": "Israël", "Hong Kong": "Hong Kong", "Luxembourg": "Luxembourg",
    "Other": "Autres",
}
REGION_LABELS = {
    "France": "France", "Europe ex-France": "Europe hors France", "North America": "Amérique du Nord",
    "Japan": "Japon", "Asia-Pacific developed": "Asie-Pacifique dév.", "Emerging markets": "Émergents",
    "Other": "Autre", "Unclassified": "Non documenté", "Other (tail)": "Autres pays",
}

CSS = """
.viz-root{color-scheme:light;--page:#f9f9f7;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--series-1:#2a78d6;--series-1-wash:rgba(42,120,214,.10);
--target:#0b0b0b;--good:#006300;--bad:#d03b3b;--border:rgba(11,11,11,.10);--warn:#fab219;
--cat-1:#2a78d6;--cat-2:#eb6834;--cat-3:#1baf7a;--cat-4:#eda100;--cat-5:#e87ba4;--cat-6:#008300;
--cat-7:#4a3aa7;--cat-8:#e34948;
--cat-1-ink:#0b0b0b;--cat-2-ink:#0b0b0b;--cat-3-ink:#0b0b0b;--cat-4-ink:#0b0b0b;--cat-5-ink:#0b0b0b;--cat-6-ink:#ffffff;--cat-7-ink:#ffffff;--cat-8-ink:#0b0b0b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--page:#0d0d0d;
--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--series-1:#3987e5;
--series-1-wash:rgba(57,135,229,.12);--target:#f0efec;--good:#0ca30c;--bad:#e66767;--border:rgba(255,255,255,.10);
--cat-1:#3987e5;--cat-2:#d95926;--cat-3:#199e70;--cat-4:#c98500;--cat-5:#d55181;--cat-6:#008300;--cat-7:#9085e9;--cat-8:#e66767;
--cat-1-ink:#0b0b0b;--cat-2-ink:#0b0b0b;--cat-3-ink:#0b0b0b;--cat-4-ink:#0b0b0b;--cat-5-ink:#0b0b0b;--cat-6-ink:#ffffff;--cat-7-ink:#0b0b0b;--cat-8-ink:#0b0b0b}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--page:#0d0d0d;--surface-1:#1a1a19;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--series-1:#3987e5;--series-1-wash:rgba(57,135,229,.12);
--target:#f0efec;--good:#0ca30c;--bad:#e66767;--border:rgba(255,255,255,.10);
--cat-1:#3987e5;--cat-2:#d95926;--cat-3:#199e70;--cat-4:#c98500;--cat-5:#d55181;--cat-6:#008300;--cat-7:#9085e9;--cat-8:#e66767;
--cat-1-ink:#0b0b0b;--cat-2-ink:#0b0b0b;--cat-3-ink:#0b0b0b;--cat-4-ink:#0b0b0b;--cat-5-ink:#0b0b0b;--cat-6-ink:#ffffff;--cat-7-ink:#0b0b0b;--cat-8-ink:#0b0b0b}
*{box-sizing:border-box}
body{margin:0;background:var(--page)}
.viz-root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text-primary);background:var(--page);
min-height:100vh;padding:24px 16px 48px}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px;margin-bottom:20px}
h1{font-size:15px;font-weight:600;margin:0;color:var(--text-secondary)}
.hero{font-size:52px;font-weight:600;letter-spacing:-.02em;line-height:1.1;margin-top:4px}
.sub{color:var(--text-secondary);font-size:14px}
.up{color:var(--good)}.down{color:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:12px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px}
.tile .label{font-size:13px;color:var(--text-secondary)}.tile .value{font-size:26px;font-weight:600;margin-top:6px}
.tile .delta{font-size:13px;margin-top:4px;color:var(--text-secondary)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;margin-bottom:12px}
.grid2.start{align-items:start}
h2{font-size:14px;font-weight:600;margin:0 0 4px}.cap{font-size:12px;color:var(--muted);margin:0 0 12px}
svg text{font-family:inherit}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;color:var(--muted);font-weight:500;border-bottom:1px solid var(--grid);padding:6px 8px;white-space:nowrap}
.tbl td{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:top}
.tbl td.n,.tbl th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tbl a{color:var(--text-primary)}
.scroll{overflow-x:auto}
.pill{display:inline-block;font-size:11px;padding:1px 6px;border-radius:999px;border:1px solid var(--border);color:var(--text-secondary)}
ul.checks{margin:0;padding-left:0;list-style:none;font-size:13px}ul.checks li{padding:6px 0;border-bottom:1px solid var(--grid)}
.ico{display:inline-block;width:16px;font-weight:700}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--border);
border-radius:8px;padding:6px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);opacity:0;transition:opacity .1s;z-index:9}
.hit{fill:transparent;cursor:default}.hit:hover+.bar,.barg:hover .bar{opacity:.85}
details summary{cursor:pointer;color:var(--text-secondary);font-size:13px}
footer{margin-top:20px;color:var(--muted);font-size:12px}
a.line{color:var(--text-primary);text-decoration:none;border-bottom:1px solid var(--axis)}
a.line:hover{border-bottom-color:var(--series-1);color:var(--series-1)}
.crumb{font-size:13px;margin-bottom:14px}
.crumb a{color:var(--text-secondary);text-decoration:none}.crumb a:hover{color:var(--series-1)}
.filters{display:flex;flex-wrap:wrap;gap:20px;align-items:center;margin:0 0 12px;padding:10px 14px;
background:var(--surface-1);border:1px solid var(--border);border-radius:12px}
.fgroup{display:flex;align-items:center;gap:8px}
.fgroup>span{font-size:12px;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{appearance:none;border:0;background:transparent;color:var(--text-secondary);font:inherit;font-size:12px;
padding:5px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--border)}
.seg button[aria-pressed="true"]{background:var(--series-1-wash);color:var(--text-primary);font-weight:600}
.seg button:focus-visible{outline:2px solid var(--series-1);outline-offset:-2px}
.kv{width:100%;border-collapse:collapse;font-size:13px}
.kv th{text-align:left;font-weight:400;color:var(--text-secondary);padding:5px 0;white-space:nowrap}
.kv td{text-align:right;padding:5px 0;font-variant-numeric:tabular-nums}
.note{font-size:13px;line-height:1.55;color:var(--text-secondary);background:var(--series-1-wash);
border-radius:8px;padding:12px 14px;margin:0}
.srcs{margin:0;padding-left:18px;font-size:12px;line-height:1.7}
.srcs a{color:var(--series-1);word-break:break-all}
.flag{border-color:var(--warn);color:var(--text-primary)}
.lg{list-style:none;margin:10px 0 0;padding:0;font-size:13px}
.lg li{display:flex;align-items:center;gap:9px;padding:5px 0;border-bottom:1px solid var(--grid)}
.lg li:last-child{border-bottom:0}
.lg .sw{width:10px;height:10px;border-radius:3px;flex:0 0 auto}
.lg .nm{flex:1}
.lg .vl{font-variant-numeric:tabular-nums;color:var(--text-secondary);white-space:nowrap}
.lg .pc{font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap;min-width:52px;text-align:right}
.donut{display:block;margin:0 auto;max-width:100%;height:auto}
.donut g{cursor:default}.donut g:focus-visible{outline:none}
.donut g:hover path,.donut g:focus-visible path{opacity:.85}
.chartwrap:focus-visible{outline:2px solid var(--series-1);outline-offset:3px;border-radius:6px}
"""

JS = """
const tip=document.getElementById('tip');
function showTip(text,x,y){tip.textContent=text;tip.style.opacity=1;
 tip.style.left=Math.min(x+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(y+14)+'px';}
// delegated so bars re-rendered by the unit/grouping toggles keep their tooltips
document.addEventListener('mousemove',e=>{
 const el=e.target.closest&&e.target.closest('[data-tip]');
 if(!el){tip.style.opacity=0;return;}
 showTip(el.dataset.tip,e.clientX,e.clientY);
});
document.addEventListener('mouseleave',()=>tip.style.opacity=0,true);
// keyboard parity: focusing a chart announces nothing new, the table twin carries the values
document.addEventListener('focusin',e=>{
 const el=e.target.closest&&e.target.closest('[data-tip]');
 if(!el){tip.style.opacity=0;return;}
 const r=el.getBoundingClientRect();showTip(el.dataset.tip,r.left+r.width/2,r.top);
});
document.addEventListener('focusout',()=>tip.style.opacity=0);
"""


# ---- per-instrument page: bars re-rendered client-side by the toggles ----
INSTRUMENT_JS = """
const SVGNS='http://www.w3.org/2000/svg';
const fmtPct=v=>(v*100).toFixed(1).replace('.',',')+' %';
const fmtEur=v=>{const a=Math.abs(v);
 const s=a>=1000?a.toLocaleString('fr-FR',{maximumFractionDigits:0}):a.toFixed(0);
 return (v<0?'−':'')+s.replace(/\\u202f|,/g,' ')+' €';};
const MUTED=new Set(['Autre','Autres','Non documenté','Other','Unclassified']);

/* One series, one colour (slot 1); the "Autres/Non documenté" tail is deliberately recessive.
   Mirrors the server-rendered hbar() so both pages read as one system. */
function drawBars(host,rows,base,mode,tick){
 const W=host.clientWidth||520,rowH=28,barH=16,labW=138,valW=74,plotW=Math.max(W-labW-valW,80);
 const vmax=Math.max(...rows.map(r=>r.w),...(tick?rows.map(r=>tick[r.label]||0):[0]),0.01);
 const H=rows.length*rowH+8;
 const svg=document.createElementNS(SVGNS,'svg');
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
 svg.setAttribute('height',H);svg.setAttribute('role','img');
 const ax=document.createElementNS(SVGNS,'line');
 ax.setAttribute('x1',labW);ax.setAttribute('x2',labW);ax.setAttribute('y1',0);ax.setAttribute('y2',H-4);
 ax.setAttribute('stroke','var(--axis)');svg.appendChild(ax);
 rows.forEach((r,i)=>{
  const y=i*rowH+6,w=Math.max(r.w/vmax*plotW,2),rr=Math.min(4,w/2);
  const g=document.createElementNS(SVGNS,'g');
  const t=tick?tick[r.label]:undefined;
  g.setAttribute('data-tip',`${r.label} · ${fmtPct(r.w)} · ${fmtEur(r.w*base)}`
    +(t!==undefined?` · poche actions ${fmtPct(t)}`:''));
  g.setAttribute('tabindex','0');g.setAttribute('class','chartwrap');
  const hit=document.createElementNS(SVGNS,'rect');
  hit.setAttribute('x',0);hit.setAttribute('y',y-5);hit.setAttribute('width',W);
  hit.setAttribute('height',rowH);hit.setAttribute('fill','transparent');g.appendChild(hit);
  const lab=document.createElementNS(SVGNS,'text');
  lab.setAttribute('x',labW-8);lab.setAttribute('y',y+barH/2+4);lab.setAttribute('text-anchor','end');
  lab.setAttribute('font-size','12');lab.setAttribute('fill','var(--text-secondary)');
  lab.textContent=r.label;g.appendChild(lab);              // untrusted text -> textContent
  const bar=document.createElementNS(SVGNS,'path');
  bar.setAttribute('d',`M${labW},${y} H${labW+w-rr} Q${labW+w},${y} ${labW+w},${y+rr} `
    +`V${y+barH-rr} Q${labW+w},${y+barH} ${labW+w-rr},${y+barH} H${labW} Z`);
  bar.setAttribute('fill',MUTED.has(r.label)?'var(--axis)':'var(--series-1)');g.appendChild(bar);
  const val=document.createElementNS(SVGNS,'text');
  val.setAttribute('x',labW+Math.max(w,(t||0)/vmax*plotW+1)+6);val.setAttribute('y',y+barH/2+4);
  val.setAttribute('font-size','12');val.setAttribute('fill','var(--text-primary)');
  val.textContent=mode==='eur'?fmtEur(r.w*base):fmtPct(r.w);g.appendChild(val);
  if(t!==undefined){const tk=document.createElementNS(SVGNS,'line'),tx=labW+t/vmax*plotW;
   tk.setAttribute('x1',tx);tk.setAttribute('x2',tx);tk.setAttribute('y1',y-3);tk.setAttribute('y2',y+barH+3);
   tk.setAttribute('stroke','var(--target)');tk.setAttribute('stroke-width','2');g.appendChild(tk);}
  svg.appendChild(g);
 });
 host.replaceChildren(svg);
}

/* view state lives in the URL hash so a given view is bookmarkable and shareable */
const H=new Set(location.hash.replace('#','').split(',').filter(Boolean));
let UNIT=H.has('eur')?'eur':'pct',GEO=H.has('region')?'region':'country';
function syncHash(){const p=[];if(UNIT==='eur')p.push('eur');if(GEO==='region')p.push('region');
 history.replaceState(null,'',p.length?'#'+p.join(','):location.pathname);}
function syncButtons(){
 document.querySelectorAll('[data-toggle] button').forEach(b=>{
  const cur=b.parentElement.dataset.toggle==='unit'?UNIT:GEO;
  b.setAttribute('aria-pressed',String(b.dataset.value===cur));});
}
function paint(){
 document.querySelectorAll('[data-chart]').forEach(host=>{
  const c=CHARTS[host.dataset.chart];if(!c)return;
  const set=c.variants?c.variants[GEO]:c;
  // the tick is a share of my equity sleeve: only comparable while the labels are shares too
  drawBars(host,set.rows,c.base,UNIT,UNIT==='pct'?set.tick:null);
  const cap=document.querySelector(`[data-unitcap="${host.dataset.chart}"]`);
  if(cap)cap.textContent=UNIT==='eur'?`en euros de mon portefeuille · base ${fmtEur(c.base)}`
                                     :c.caption;
 });
}
function wire(name,set){
 document.querySelectorAll(`[data-toggle="${name}"] button`).forEach(b=>{
  b.addEventListener('click',()=>{set(b.dataset.value);syncButtons();syncHash();paint();});
 });
}
wire('unit',v=>UNIT=v);wire('geo',v=>GEO=v);
syncButtons();paint();
addEventListener('resize',paint);
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def eur(v, dec=0) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{dec}f}".replace(",", " ").replace(".", ",")
    return f"{'−' if v < 0 else ''}{s} €"


def compact_eur(v) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v/1e6:.1f} M€".replace(".", ",")
    if a >= 1e3:
        return f"{v/1e3:.0f} k€"
    return f"{v:.0f} €"


def qty(v) -> str:
    if v is None:
        return "—"
    s = f"{v:,.4f}".replace(",", " ").replace(".", ",")
    return s.rstrip("0").rstrip(",") if "," in s else s


def pct(v, dec=1, signed=False) -> str:
    if v is None:
        return "—"
    s = f"{v*100:+.{dec}f}" if signed else f"{v*100:.{dec}f}"
    return s.replace(".", ",").replace("-", "−") + " %"


def hbar(rows, label_fn=lambda b: b, targets: dict | None = None, width=360) -> str:
    """Horizontal bars, one series. Value label at the tip; optional target tick."""
    if not rows:
        return '<p class="cap">Aucune donnée.</p>'
    rows = list(rows)
    present = {r["bucket"] for r in rows}
    for b, t in (targets or {}).items():   # show targeted buckets even when actual is 0
        if b not in present:
            rows.insert(len([r for r in rows if r["bucket"] not in ("Unclassified", "Other", "Other (tail)")]),
                        {"bucket": b, "value": 0.0, "pct": 0.0})
    row_h, bar_h, lab_w, val_w = 28, 16, 132, 52
    plot_w = width - lab_w - val_w
    vmax = max([r["pct"] for r in rows] + list((targets or {}).values()) + [0.01])
    h = len(rows) * row_h + 8
    out = [f'<svg viewBox="0 0 {width} {h}" width="{width}" height="{h}" role="img" style="max-width:100%;height:auto">']
    out.append(f'<line x1="{lab_w}" y1="0" x2="{lab_w}" y2="{h-4}" stroke="var(--axis)" stroke-width="1"/>')
    for i, r in enumerate(rows):
        y = i * row_h + 6
        w = max(r["pct"] / vmax * plot_w, 2)
        lab = label_fn(r["bucket"])
        t = (targets or {}).get(r["bucket"])
        tip = f"{lab} · {pct(r['pct'])} · {eur(r['value'])}" + (f" · cible {pct(t)}" if t is not None else "")
        rr = min(4, w / 2)
        # square at baseline, 4px rounded data-end
        d = (f"M{lab_w},{y} H{lab_w + w - rr} Q{lab_w + w},{y} {lab_w + w},{y + rr} "
             f"V{y + bar_h - rr} Q{lab_w + w},{y + bar_h} {lab_w + w - rr},{y + bar_h} H{lab_w} Z")
        muted = r["bucket"] in ("Unclassified", "Other", "Other (tail)")
        fill = "var(--axis)" if muted else "var(--series-1)"
        out.append(f'<g class="barg" data-tip="{esc(tip)}"><rect class="hit" x="0" y="{y-5}" width="{width}" height="{row_h}"/>'
                   f'<text x="{lab_w-8}" y="{y+bar_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-secondary)">{esc(lab)}</text>'
                   f'<path class="bar" d="{d}" fill="{fill}"/>'
                   f'<text x="{lab_w + max(w, (t or 0) / vmax * plot_w + 1) + 6}" y="{y+bar_h/2+4}" font-size="12" fill="var(--text-primary)">{pct(r["pct"])}</text>')
        if t is not None:
            tx = lab_w + t / vmax * plot_w
            out.append(f'<line x1="{tx}" y1="{y-3}" x2="{tx}" y2="{y+bar_h+3}" stroke="var(--target)" stroke-width="2"/>')
        out.append("</g>")
    # targets for buckets not present in actuals
    out.append("</svg>")
    return "".join(out)


# Categorical slot per envelope — fixed to the ENTITY, so adding or emptying an envelope never
# repaints the others. The ring is drawn in slot order, which makes the ring's neighbour pairs
# exactly the palette's documented adjacent pairlist (validated light+dark); in particular the
# weak orange/yellow pair is never adjacent. Anything outside this map folds into a muted "Autres".
ENVELOPE_SLOT = {"pea": 1, "assurance_vie": 2, "livret_a": 3, "current": 4,
                 "ldds": 5, "per": 6, "cto": 7, "pea_pme": 8}
MAX_SEGMENTS = 6   # donuts stay readable to ~6 slices; the tail folds into "Autres"


def _arc(cx, cy, ro, ri, a0, a1) -> str:
    large = 1 if (a1 - a0) % 360 > 180 else 0
    p = []
    for r, a, sweep in ((ro, a0, None), (ro, a1, None), (ri, a1, None), (ri, a0, None)):
        rad = math.radians(a)
        p.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
    return (f"M{p[0][0]:.2f},{p[0][1]:.2f} A{ro},{ro} 0 {large} 1 {p[1][0]:.2f},{p[1][1]:.2f} "
            f"L{p[2][0]:.2f},{p[2][1]:.2f} A{ri},{ri} 0 {large} 0 {p[3][0]:.2f},{p[3][1]:.2f} Z")


def donut(rows, total, size=250) -> str:
    """Part-to-whole ring over the envelopes, Finary-style: total in the hole, one slice per vector.

    Slices are separated by a 2px surface gap (never a stroked border) and the big ones carry their
    own percentage, so colour is never the only way to tell two slices apart.
    """
    if not rows:
        return '<p class="cap">Aucune enveloppe valorisée.</p>'
    cx = cy = size / 2
    ro, ri = size / 2 - 6, size / 2 - 44
    gap = math.degrees(2.0 / ((ro + ri) / 2))      # a 2px arc at mid-radius
    out = [f'<svg class="donut" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
           f'role="img" aria-label="Répartition par enveloppe">']
    a = -90.0
    for r in rows:
        span = r["pct"] * 360
        a0, a1 = a, a + span
        a += span
        if span >= 359.9:                           # single envelope: a plain ring, no seam
            d = (_arc(cx, cy, ro, ri, -90, 90) + " " + _arc(cx, cy, ro, ri, 90, 270))
        else:
            pad = min(gap / 2, max(span / 2 - 0.3, 0))
            d = _arc(cx, cy, ro, ri, a0 + pad, a1 - pad)
        tip = f"{r['label']} · {pct(r['pct'])} · {eur(r['value'])}"
        out.append(f'<g tabindex="0" data-tip="{esc(tip)}"><path d="{d}" fill="{r["fill"]}"/>')
        if span >= 26:                              # only label a slice the text actually fits in
            rad = math.radians((a0 + a1) / 2)
            lx, ly = cx + (ro + ri) / 2 * math.cos(rad), cy + (ro + ri) / 2 * math.sin(rad)
            out.append(f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle" font-size="12" '
                       f'font-weight="600" fill="{r["ink"]}">{pct(r["pct"], 0)}</text>')
        out.append("</g>")
    out.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="22" font-weight="600" '
               f'fill="var(--text-primary)">{compact_eur(total)}</text>'
               f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" font-size="12" '
               f'fill="var(--muted)">total</text></svg>')
    legend = "".join(
        f'<li><span class="sw" style="background:{r["fill"]}"></span>'
        f'<span class="nm">{esc(r["label"])}</span>'
        f'<span class="vl">{eur(r["value"])}</span>'
        f'<span class="pc">{pct(r["pct"])}</span></li>' for r in rows)
    table = "".join(f"<tr><td>{esc(r['label'])}</td><td class='n'>{eur(r['value'])}</td>"
                    f"<td class='n'>{pct(r['pct'])}</td></tr>" for r in rows)
    return ("".join(out) + f'<ul class="lg">{legend}</ul>'
            + "<details><summary>Tableau</summary><table class='tbl'><thead><tr><th>Enveloppe</th>"
              "<th class='n'>Montant</th><th class='n'>Part</th></tr></thead><tbody>"
            + table + "</tbody></table></details>")


def envelope_rows(envelopes) -> list[dict]:
    """Envelope rows ready to draw: drop the empty ones, fix a colour per envelope, fold the tail."""
    live = [e for e in envelopes if e["value"] > 0]
    live.sort(key=lambda e: (ENVELOPE_SLOT.get(e["bucket"], 99), -e["value"]))
    known = [e for e in live if e["bucket"] in ENVELOPE_SLOT]
    tail = [e for e in live if e["bucket"] not in ENVELOPE_SLOT]
    if len(known) > MAX_SEGMENTS:                   # keep the biggest, fold the rest
        known.sort(key=lambda e: -e["value"])
        tail += known[MAX_SEGMENTS:]
        known = known[:MAX_SEGMENTS]
        known.sort(key=lambda e: ENVELOPE_SLOT[e["bucket"]])
    rows = [{"label": ENVELOPE_LABELS.get(e["bucket"], e["bucket"]), "value": e["value"],
             "pct": e["pct"], "fill": f"var(--cat-{ENVELOPE_SLOT[e['bucket']]})",
             "ink": f"var(--cat-{ENVELOPE_SLOT[e['bucket']]}-ink)"} for e in known]
    if tail:
        rows.append({"label": "Autres", "value": sum(e["value"] for e in tail),
                     "pct": sum(e["pct"] for e in tail), "fill": "var(--axis)",
                     "ink": "var(--text-primary)"})
    return rows


def line_chart(hist, width=1100, height=240) -> str:
    pts = [(dt.date.fromisoformat(h["as_of"]), h["total"]) for h in hist]
    if len(pts) < 2:
        return ('<p class="cap">Un seul instantané pour l’instant — la courbe apparaîtra après le prochain '
                '<code>/snapshot</code>.</p>')
    pad_l, pad_r, pad_t, pad_b = 56, 64, 12, 26
    x0, x1 = pts[0][0], pts[-1][0]
    span = max((x1 - x0).days, 1)
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    rng = hi - lo or hi * 0.05 or 1
    lo, hi = lo - rng * 0.15, hi + rng * 0.15
    # clean ticks
    import math
    step = 10 ** math.floor(math.log10((hi - lo) / 3))
    for m in (1, 2, 2.5, 5, 10):
        if (hi - lo) / (step * m) <= 4:
            step *= m
            break
    t0 = math.ceil(lo / step) * step
    ticks = []
    while t0 <= hi:
        ticks.append(t0)
        t0 += step
    X = lambda d: pad_l + (d - x0).days / span * (width - pad_l - pad_r)  # noqa: E731
    Y = lambda v: pad_t + (hi - v) / (hi - lo) * (height - pad_t - pad_b)  # noqa: E731
    o = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for t in ticks:
        o.append(f'<line x1="{pad_l}" x2="{width-pad_r}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="var(--grid)"/>'
                 f'<text x="{pad_l-6}" y="{Y(t)+4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{compact_eur(t)}</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(d):.1f},{Y(v):.1f}" for i, (d, v) in enumerate(pts))
    area = path + f" L{X(x1):.1f},{height-pad_b} L{X(x0):.1f},{height-pad_b} Z"
    o.append(f'<path d="{area}" fill="var(--series-1-wash)"/>')
    o.append(f'<path d="{path}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    for d, v in pts:
        o.append(f'<g data-tip="{d.isoformat()} · {eur(v)}"><circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="12" fill="transparent"/>'
                 f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/></g>')
    d, v = pts[-1]
    o.append(f'<text x="{X(d)+8:.1f}" y="{Y(v)+4:.1f}" font-size="12" fill="var(--text-primary)">{compact_eur(v)}</text>')
    for d in (x0, x1):
        o.append(f'<text x="{X(d):.1f}" y="{height-8}" text-anchor="middle" font-size="11" fill="var(--muted)">{d.strftime("%d/%m/%y")}</text>')
    o.append("</svg>")
    return "".join(o)


def _signed_cls(v):
    return "" if v in (None, 0) else ("up" if v > 0 else "down")


def positions_table(pos, documented=(), link_prefix="") -> str:
    rows = []
    for p in pos:
        isin = p.get("isin")
        links = ""
        if isin:
            links = (f' <a class="pill" href="https://www.google.com/search?q=site%3Aboursorama.com+{esc(isin)}" target="_blank" rel="noopener">Boursorama</a>'
                     + (f' <a class="pill" href="https://www.justetf.com/fr/etf-profile.html?isin={esc(isin)}" target="_blank" rel="noopener">justETF</a>'
                        if p["kind"] == "etf" else ""))
        # the name links to the per-instrument page when a fiche exists for it
        name = (f'<a class="line" href="{esc(link_prefix)}instruments/{esc(isin)}.html">{esc(p["name"])}</a>'
                if isin in documented else esc(p["name"]))
        rows.append(
            f"<tr><td>{name}<br><span class='cap'>{esc(isin or p['kind'])}</span>{links}</td>"
            f"<td>{esc(ENVELOPE_LABELS.get(p['envelope'], p['envelope']))}</td>"
            f"<td class='n'>{eur(p['value'])}</td><td class='n'>{pct(p['weight'])}</td>"
            f"<td class='n {_signed_cls(p['pnl'])}'>{'—' if p['pnl'] is None else eur(p['pnl'])}</td>"
            f"<td class='n {_signed_cls(p['pnl_pct'])}'>{pct(p['pnl_pct'], signed=True)}</td>"
            f"<td class='n'>{pct(p['ter'], 2)}</td>"
            f"<td>{'' if p['has_instrument_data'] or p['kind'] in ('cash','fonds_euros') else '<span class=pill>à documenter</span>'}</td></tr>")
    return ("<div class='scroll'><table class='tbl'><thead><tr><th>Ligne</th><th>Enveloppe</th><th class='n'>Valeur</th>"
            "<th class='n'>Poids</th><th class='n'>+/− latente</th><th class='n'>%</th><th class='n'>Frais (TER)</th><th></th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def checks_list(r) -> str:
    items = []
    for c in r["envelope_checks"]:
        if c["check"] == "ceiling":
            full = c["headroom"] <= 0
            items.append(f"<li><span class='ico'>{'■' if full else '○'}</span><b>{esc(c['account'])}</b> — "
                         f"{eur(c['value'])} / plafond {eur(c['limit'])} · "
                         + ("plafond atteint" if full else f"marge {eur(c['headroom'])}")
                         + f" · taux {pct(c['rate'], 2)}</li>")
        elif c["check"] == "pea_ceiling":
            items.append(f"<li><span class='ico'>○</span><b>{esc(c['account'])}</b> — versements "
                         + (f"{eur(c['value'])} / {eur(c['limit'])} (marge {eur(c['headroom'])})" if c["value"] is not None
                            else "inconnus — renseigner <code>pea_contributions_total</code>") + "</li>")
        elif c["check"] in ("pea_5y", "av_8y"):
            ok = c["ok"]
            label = "PEA ≥ 5 ans" if c["check"] == "pea_5y" else "Assurance-vie ≥ 8 ans"
            items.append(f"<li><span class='ico' style='color:var({'--good' if ok else '--muted'})'>{'✓' if ok else '…'}</span>"
                         f"<b>{esc(c['account'])}</b> — {label} : {'oui' if ok else 'non'} ({c['value']:.1f} ans)</li>")
    return "<ul class='checks'>" + ("".join(items) or "<li>Aucune vérification applicable.</li>") + "</ul>"


def perf_bars(perf: dict, width=360) -> str:
    """Zero-baseline bars for 1y / 3y / 5y returns. Gains and losses are a polarity, so they
    carry the good/bad status tokens — always beside a signed value label, never colour alone."""
    labels = [("1y", "1 an"), ("3y_annualized", "3 ans (annualisé)"), ("5y_annualized", "5 ans (annualisé)")]
    rows = [(lab, perf[k]) for k, lab in labels if perf.get(k) is not None]
    if not rows:
        return '<p class="cap">Aucune performance publiée dans la fiche.</p>'
    row_h, bar_h, lab_w, val_w = 30, 16, 132, 56
    plot_w = width - lab_w - val_w
    vmax = max(abs(v) for _, v in rows) or 0.01
    zero = lab_w + (plot_w / 2 if any(v < 0 for _, v in rows) else 0)
    half = plot_w / 2 if any(v < 0 for _, v in rows) else plot_w
    h = len(rows) * row_h + 8
    o = [f'<svg viewBox="0 0 {width} {h}" width="{width}" height="{h}" role="img" style="max-width:100%;height:auto">',
         f'<line x1="{zero:.1f}" y1="0" x2="{zero:.1f}" y2="{h-4}" stroke="var(--axis)"/>']
    for i, (lab, v) in enumerate(rows):
        y = i * row_h + 7
        w = max(abs(v) / vmax * half, 2)
        x = zero if v >= 0 else zero - w
        rr = min(4, w / 2)
        if v >= 0:
            d = (f"M{x},{y} H{x + w - rr} Q{x + w},{y} {x + w},{y + rr} V{y + bar_h - rr} "
                 f"Q{x + w},{y + bar_h} {x + w - rr},{y + bar_h} H{x} Z")
            tx = x + w + 6
            anchor = "start"
        else:
            d = (f"M{x + rr},{y} H{x + w} V{y + bar_h} H{x + rr} Q{x},{y + bar_h} {x},{y + bar_h - rr} "
                 f"V{y + rr} Q{x},{y} {x + rr},{y} Z")
            tx = x - 6
            anchor = "end"
        fill = "var(--good)" if v >= 0 else "var(--bad)"
        o.append(f'<g data-tip="{esc(lab)} · {pct(v, 1, signed=True)}">'
                 f'<rect x="0" y="{y-6}" width="{width}" height="{row_h}" fill="transparent"/>'
                 f'<text x="{lab_w-8}" y="{y+bar_h/2+4}" text-anchor="end" font-size="12" '
                 f'fill="var(--text-secondary)">{esc(lab)}</text>'
                 f'<path d="{d}" fill="{fill}"/>'
                 f'<text x="{tx:.1f}" y="{y+bar_h/2+4}" text-anchor="{anchor}" font-size="12" '
                 f'fill="var(--text-primary)">{pct(v, 1, signed=True)}</text></g>')
    o.append("</svg>")
    return "".join(o)


def _bucket_table(rows, base) -> str:
    """The table twin every chart needs: values reachable without hovering."""
    body = "".join(f"<tr><td>{esc(x['label'])}</td><td class='n'>{pct(x['w'])}</td>"
                   f"<td class='n'>{eur(x['w'] * base)}</td></tr>" for x in rows)
    return ("<details><summary>Tableau</summary><table class='tbl'><thead><tr><th>Poste</th>"
            "<th class='n'>Part</th><th class='n'>Montant</th></tr></thead><tbody>"
            + body + "</tbody></table></details>")


def _chart_card(cid, title, caption, rows, base) -> str:
    return (f"<div class='card'><h2>{title}</h2>"
            f"<p class='cap' data-unitcap='{cid}'>{caption}</p>"
            f"<div data-chart='{cid}' style='min-height:40px'></div>{_bucket_table(rows, base)}</div>")


def instrument_page(isin: str, r: dict, back="../index.html") -> str:
    """Analysis page for one holding, built from data/instruments/<ISIN>.json + its position."""
    meta = r["instruments"][isin]
    lines = [p for p in r["positions"] if p.get("isin") == isin]
    value = sum(p["value"] for p in lines)
    cost = sum(p["cost_basis"] for p in lines if p["cost_basis"] is not None) or None
    pnl = (value - cost) if cost else None
    weight = value / r["total_value"] if r["total_value"] else 0
    bd = meta["breakdowns"]
    ac = bd.get("asset_class", {})
    eq_share = ac.get("equity", 0.0)
    eq_value = value * eq_share
    ex = r["exposure"]

    def rows_of(d, label_fn=lambda b: b):
        return sorted(({"label": label_fn(k), "w": v} for k, v in d.items()),
                      key=lambda x: (x["label"] in ("Autres", "Autre", "Non documenté"), -x["w"]))

    charts, cards = {}, []
    if len(ac) == 1:
        # one asset class is a fact, not a chart — a single bar would be an empty gesture
        only = next(iter(ac))
        cards.append(f"<div class='card'><h2>Classe d’actifs</h2><p class='cap'>intégralité du fonds</p>"
                     f"<div class='hero' style='font-size:34px'>{esc(ASSET_LABELS.get(only, only))}</div>"
                     f"<p class='cap' style='margin-top:6px'>soit {eur(value)}</p></div>")
    elif ac:
        rows = rows_of(ac, lambda b: ASSET_LABELS.get(b, b))
        charts["ac"] = {"rows": rows, "base": value, "caption": "part du fonds"}
        cards.append(_chart_card("ac", "Classes d’actifs", "part du fonds", rows, value))

    country = bd.get("country")
    if country:
        by_country = defaultdict(float)
        by_region = defaultdict(float)
        for k, w in country.items():
            c = taxonomy.country(k)
            by_country[c] += w
            by_region[taxonomy.region_of_country(c)] += w
        c_rows = rows_of(dict(by_country), lambda b: COUNTRY_LABELS.get(b, b))
        r_rows = rows_of(dict(by_region), lambda b: REGION_LABELS.get(b, b))
        tick = {REGION_LABELS.get(x["bucket"], x["bucket"]): x["pct"] for x in ex["region"]}
        charts["geo"] = {"base": eq_value, "caption": "part de la poche actions du fonds",
                         "variants": {"country": {"rows": c_rows},
                                      "region": {"rows": r_rows, "tick": tick}}}
        cards.append(
            "<div class='card'><h2>Géographie</h2>"
            "<p class='cap' data-unitcap='geo'>part de la poche actions du fonds</p>"
            "<div data-chart='geo' style='min-height:40px'></div>"
            "<p class='cap' style='margin-top:8px'>En vue « Régions », le trait vertical marque la "
            "moyenne de toute ma poche actions.</p>"
            + _bucket_table(c_rows, eq_value) + "</div>")

    sector = bd.get("sector")
    if sector:
        s_rows = rows_of({taxonomy.sector(k): v for k, v in sector.items()},
                         lambda b: SECTOR_LABELS.get(b, b))
        tick = {SECTOR_LABELS.get(x["bucket"], x["bucket"]): x["pct"] for x in ex["sector"]}
        charts["sec"] = {"rows": s_rows, "base": eq_value, "tick": tick,
                         "caption": "part de la poche actions du fonds · trait = moyenne de ma poche actions"}
        cards.append(_chart_card("sec", "Secteurs (GICS)",
                                 "part de la poche actions du fonds · trait = moyenne de ma poche actions",
                                 s_rows, eq_value))

    if not country and not sector:
        why = ("Fonds obligataire : la géographie et les secteurs ne sont calculés que sur la poche "
               "actions, que ce fonds n’a pas. Voir les notes en bas de page."
               if ac.get("bond") else
               "Aucune décomposition chiffrée publiée par l’émetteur — rien n’a été deviné. "
               "Cette ligne compte donc en « Non documenté » dans la vue d’ensemble.")
        cards.append(f"<div class='card'><h2>Décomposition</h2><p class='cap'>{esc(why)}</p></div>")

    ter = meta.get("ter")
    fee = value * ter if ter else None
    pea = meta.get("pea_eligible")
    pea_txt = "—" if pea is None else ("Oui" if pea else "Non")
    held_pea = any(p["envelope"] == "pea" for p in lines)
    pea_flag = (" <span class='pill flag'>détenu hors PEA</span>"
                if pea and not held_pea else "")

    tiles = "".join([
        f"<div class='card tile'><div class='label'>Valeur</div><div class='value'>{eur(value)}</div>"
        f"<div class='delta'>{pct(weight)} de mon patrimoine</div></div>",
        f"<div class='card tile'><div class='label'>Plus-value latente</div>"
        f"<div class='value {_signed_cls(pnl)}'>{eur(pnl) if pnl is not None else '—'}</div>"
        f"<div class='delta'>{pct(pnl / cost, signed=True) if pnl is not None and cost else '—'}"
        f" · investi {eur(cost) if cost else '—'}</div></div>",
        f"<div class='card tile'><div class='label'>Frais courants (TER)</div>"
        f"<div class='value'>{pct(ter, 2) if ter else '—'}</div>"
        f"<div class='delta'>{eur(fee) + ' par an à cet encours' if fee else '—'}</div></div>",
        f"<div class='card tile'><div class='label'>Éligible PEA</div><div class='value'>{pea_txt}</div>"
        f"<div class='delta'>SRI {meta.get('sri') or '—'}/7{pea_flag}</div></div>",
    ])

    pos_rows = "".join(
        f"<tr><td>{esc(p['account_name'])}<br><span class='cap'>"
        f"{esc(ENVELOPE_LABELS.get(p['envelope'], p['envelope']))}</span></td>"
        f"<td class='n'>{qty(p['quantity'])}</td>"
        f"<td class='n'>{eur(p['unit_price'], 2) if p['unit_price'] else '—'}</td>"
        f"<td class='n'>{eur(p['cost_basis']) if p['cost_basis'] else '—'}</td>"
        f"<td class='n'>{eur(p['value'])}</td>"
        f"<td class='n {_signed_cls(p['pnl'])}'>{eur(p['pnl']) if p['pnl'] is not None else '—'}</td></tr>"
        for p in lines)

    perf_rows = "".join(
        f"<tr><td>{lab}</td><td class='n {_signed_cls(meta['performance'][k])}'>"
        f"{pct(meta['performance'][k], 1, signed=True)}</td></tr>"
        for k, lab in (("1y", "1 an"), ("3y_annualized", "3 ans (annualisé)"),
                       ("5y_annualized", "5 ans (annualisé)"))
        if meta["performance"].get(k) is not None) or "<tr><td colspan=2>—</td></tr>"

    facts = [("ISIN", isin), ("Type", meta["kind"]), ("Émetteur", meta.get("issuer")),
             ("Indice suivi", meta.get("index")), ("Réplication", meta.get("replication")),
             ("Fiche mise à jour le", meta.get("fetched_at"))]
    facts_html = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in facts if v)
    srcs = "".join(f'<li><a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["url"])}</a>'
                   f' <span class="cap">({esc(s.get("fetched_at", ""))})</span></li>'
                   for s in meta.get("sources", []))

    geo_toggle = ("""<div class="fgroup"><span>Géographie</span><div class="seg" data-toggle="geo">
  <button data-value="country" aria-pressed="true">Pays</button>
  <button data-value="region" aria-pressed="false">Régions</button></div></div>"""
                  if "geo" in charts else "")
    # with no chart to re-scale, the unit switch would be a dead control
    filters = (f'<section class="filters" role="group" aria-label="Affichage des décompositions">'
               f'<div class="fgroup"><span>Unité</span><div class="seg" data-toggle="unit">'
               f'<button data-value="pct" aria-pressed="true">% du fonds</button>'
               f'<button data-value="eur" aria-pressed="false">€ chez moi</button></div></div>'
               f'{geo_toggle}</section>') if charts else ""
    data_js = json.dumps(charts, ensure_ascii=False).replace("</", "<\\/")
    body = f"""
<div class="viz-root"><div class="wrap">
<p class="crumb"><a href="{esc(back)}">← Portefeuille</a></p>
<header><div><h1>{esc(meta['name'])}</h1>
<div class="hero">{eur(value)}</div>
<div class="sub">{esc(isin)} · {esc(', '.join(sorted({ENVELOPE_LABELS.get(p['envelope'], p['envelope']) for p in lines})))}</div></div>
<div class="sub">Au {esc(r['as_of'])}</div></header>
<section class="tiles">{tiles}</section>
{filters}
<section class="grid2 start">{''.join(cards)}
<div class="card"><h2>Performance de l’instrument</h2>
<p class="cap">Publiée par la source, nette de frais de gestion — ce n’est pas ma performance sur la ligne</p>
{perf_bars(meta['performance'])}
<details><summary>Tableau</summary><table class="tbl"><thead><tr><th>Horizon</th>
<th class="n">Performance</th></tr></thead><tbody>{perf_rows}</tbody></table></details></div>
</section>
<section class="grid2 start">
<div class="card"><h2>Ma position</h2><p class="cap">Prix de revient et quantités issus de Finary</p>
<div class="scroll"><table class="tbl"><thead><tr><th>Compte</th><th class="n">Qté</th>
<th class="n">Cours</th><th class="n">Investi</th><th class="n">Valeur</th><th class="n">+/−</th></tr></thead>
<tbody>{pos_rows}</tbody></table></div></div>
<div class="card"><h2>Caractéristiques</h2><p class="cap">Fiche <code>{esc(isin)}.json</code></p>
<table class="kv">{facts_html}</table></div>
</section>
<section class="card"><h2>Notes & sources</h2>
<p class="note">{esc(meta['notes'] or 'Aucune note.')}</p>
<p class="cap" style="margin-top:12px">Sources consultées</p><ul class="srcs">{srcs or '<li>—</li>'}</ul></section>
<footer>Fiche : <code>data/instruments/{esc(isin)}.json</code> · régénérée par
<code>python3 -m pfa dashboard</code>. Informations à visée personnelle, pas un conseil en investissement réglementé.</footer>
</div></div><div id="tip" role="tooltip"></div>"""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(meta['name'])} · {esc(isin)}</title><style>{CSS}</style></head><body>{body}
<script>{JS}</script><script>const CHARTS={data_js};{INSTRUMENT_JS}</script></body></html>"""


def render(r: dict, link_prefix="") -> str:
    ex = r["exposure"]
    gaps = ex["data_gaps"]
    pos = r["positions"]
    invested = sum(p["value"] for p in pos if p["kind"] not in ("cash",))
    pnl_known = [p for p in pos if p["pnl"] is not None]
    pnl = sum(p["pnl"] for p in pnl_known)
    cost = sum(p["cost_basis"] for p in pnl_known) or None
    delta = r["change_vs_previous"]
    targets = {}
    for dim, rows in r["drift_vs_targets"].items():
        targets[dim] = {x["bucket"]: x["target"] for x in rows}
    fees = r["fees"]
    ret = r["returns"]

    def tile(label, value, delta_html=""):
        return f"<div class='card tile'><div class='label'>{label}</div><div class='value'>{value}</div><div class='delta'>{delta_html}</div></div>"

    tiles = "".join([
        tile("Investi (hors liquidités)", eur(invested), f"{pct(invested / r['total_value'] if r['total_value'] else None)} du total"),
        tile("Plus-value latente", f"<span class='{_signed_cls(pnl)}'>{eur(pnl)}</span>",
             f"{pct(pnl / cost if cost else None, signed=True)} sur prix de revient connu"),
        tile("Rendement annualisé (MWR)", pct(ret.get("total"), signed=True) if ret.get("total") is not None else "—",
             f"depuis {ret['from']}" if ret.get("from") and ret.get("total") is not None else "≥ 2 instantanés nécessaires"),
        tile("Frais des fonds / an", eur(fees["fund_fees_eur_per_year"]),
             f"TER moyen {pct(fees['weighted_ter_on_covered'], 2)} · couverture {pct(fees['ter_coverage_pct'], 0)}"),
    ])
    gap_names = sorted({g["name"] for g in gaps["no_geography"]} | {g["name"] for g in gaps["no_sector"]})
    gap_html = ("<p class='cap'>Toutes les lignes actions sont documentées.</p>" if not gap_names else
                "<p class='cap'>Lignes sans décomposition (comptées en « Non documenté ») — lancez <code>/lookup</code> :</p>"
                "<ul class='checks'>" + "".join(f"<li>{esc(n)}</li>" for n in gap_names) + "</ul>")
    hist_rows = "".join(f"<tr><td>{h['as_of']}</td><td class='n'>{eur(h['total'])}</td></tr>" for h in reversed(r["history"]))

    body = f"""
<div class="viz-root"><div class="wrap">
<header><div><h1>Patrimoine financier · au {esc(r['as_of'])}</h1>
<div class="hero">{eur(r['total_value'])}</div>
<div class="sub">{'' if delta is None else f"<span class='{_signed_cls(delta)}'>{'▲' if delta > 0 else '▼'} {eur(delta)}</span> depuis le {esc(r['previous_as_of'])}"}</div></div>
<div class="sub">Source : Finary (lecture seule) · décompositions : Boursorama / justETF</div></header>
<section class="tiles">{tiles}</section>
<section class="card" style="margin-bottom:12px"><h2>Évolution du total</h2><p class="cap">Valeur totale à chaque instantané</p>
{line_chart(r['history'])}
<details><summary>Tableau</summary><table class="tbl"><tr><th>Date</th><th class="n">Total</th></tr>{hist_rows}</table></details></section>
<section class="grid2">
<div class="card"><h2>Par enveloppe</h2><p class="cap">Part du total · survolez une part</p>{donut(envelope_rows(r['envelopes']), r['total_value'])}</div>
<div class="card"><h2>Classes d’actifs</h2><p class="cap">Transparisation des fonds · trait = cible</p>{hbar(ex['asset_class'], lambda b: ASSET_LABELS.get(b, b), targets.get('asset_class'))}</div>
<div class="card"><h2>Géographie (poche actions)</h2><p class="cap">Couverture {pct(gaps['coverage_geo_pct'], 0)} · trait = cible</p>{hbar(ex['region'], lambda b: REGION_LABELS.get(b, b), targets.get('region'))}</div>
<div class="card"><h2>Secteurs (poche actions)</h2><p class="cap">GICS · couverture {pct(gaps['coverage_sector_pct'], 0)}</p>{hbar(ex['sector'], lambda b: SECTOR_LABELS.get(b, b), targets.get('sector'))}</div>
<div class="card"><h2>Principaux pays</h2><p class="cap">Poche actions, transparisée</p>{hbar(ex['country'], lambda b: REGION_LABELS.get(b) or COUNTRY_LABELS.get(b, b))}</div>
<div class="card"><h2>Enveloppes & plafonds</h2><p class="cap">Règles vérifiées le {esc(r['rules_verified_on'])}</p>{checks_list(r)}
<h2 style="margin-top:16px">Qualité des données</h2>{gap_html}</div>
</section>
<section class="card"><h2>Lignes</h2><p class="cap">{len(pos)} lignes · concentration : top 1 {pct(r['concentration']['top1_pct'])}, top 5 {pct(r['concentration']['top5_pct'])} · cliquez une ligne documentée pour sa fiche</p>{positions_table(pos, set(r.get('instruments', {})), link_prefix)}</section>
<footer>Généré le {dt.datetime.now().strftime('%d/%m/%Y %H:%M')} par <code>python3 -m pfa dashboard</code>. Informations à visée personnelle, pas un conseil en investissement réglementé.</footer>
</div></div><div id="tip" role="tooltip"></div>"""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Patrimoine · {esc(r['as_of'])}</title><style>{CSS}</style></head><body>{body}<script>{JS}</script>
</body></html>"""
