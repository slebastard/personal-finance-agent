import { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeftRight, CalendarClock, LayoutDashboard, Monitor, Moon, Sprout, Sun } from 'lucide-react';
import { api } from '../api/client';
import { useTheme, type ThemePref } from '../theme/ThemeProvider';

const SECTIONS = [
  { to: '/portfolio', label: 'Patrimoine', icon: LayoutDashboard,
    // the dashboard owns the asset pages too: a line or a company is "inside" Patrimoine
    match: (p: string) => /^\/(portfolio|instruments|companies)/.test(p) },
  { to: '/flows', label: 'Flux', icon: ArrowLeftRight, match: (p: string) => p.startsWith('/flows') },
];

const TITLES: [RegExp, string][] = [
  [/^\/flows/, 'Flux de trésorerie'], [/^\/instruments/, 'Détail d’une ligne'],
  [/^\/companies/, 'Détail d’une société'], [/^\/portfolio/, 'Patrimoine'],
];

/**
 * The side rail is a floating box like every other one. Collapsed it shows round icon buttons;
 * hovering NEAR it, hovering it, or tabbing into it opens it over the page (the content never moves).
 * The opening is pure CSS (:hover / :focus-within); the logo button pins it open for touch screens,
 * which have no hover.
 */
function Rail() {
  const { pathname } = useLocation();
  const [pinned, setPinned] = useState(false);
  return (
    <aside className="rail" data-pinned={pinned} aria-label="Navigation principale">
      <button className="rail-brand" onClick={() => setPinned((v) => !v)}
              aria-expanded={pinned} aria-label="Déplier ou replier le menu">
        <span className="rail-logo"><Sprout size={22} /></span>
        <span className="rail-name">Patrimoine<small>assistant personnel</small></span>
      </button>
      <nav style={{ display: 'grid', gap: 6 }}>
        {SECTIONS.map(({ to, label, icon: Icon, match }) => (
          <Link key={to} to={to} className="rail-item" title={label}
                aria-current={match(pathname) ? 'page' : undefined}>
            <Icon /><span className="rail-label">{label}</span>
          </Link>))}
      </nav>
      <div className="rail-spacer" />
    </aside>
  );
}

const THEME_OPTIONS: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'Thème du système', icon: Monitor },
  { value: 'light', label: 'Thème clair', icon: Sun },
  { value: 'dark', label: 'Thème sombre', icon: Moon },
];

function ThemeToggle() {
  const { pref, setPref } = useTheme();
  return (
    <div className="theme-toggle" role="group" aria-label="Thème d'affichage">
      {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
        <button key={value} aria-pressed={pref === value} aria-label={label} title={label}
                onClick={() => setPref(value)}><Icon /></button>))}
    </div>
  );
}

const dateFr = (iso: string) =>
  new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
    .format(new Date(`${iso}T12:00:00`));

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('');

function Topbar() {
  const { pathname } = useLocation();
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: () => api.meta() });
  const title = TITLES.find(([re]) => re.test(pathname))?.[1] ?? 'Patrimoine';
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="topbar-right">
        {meta?.latestAsOf && (
          <span className="chip-info" title="Date de valorisation du dernier snapshot Finary">
            <CalendarClock aria-hidden /> Données au {dateFr(meta.latestAsOf)}
          </span>)}
        {meta?.userName && (
          <span className="user"><span className="avatar" aria-hidden>{initials(meta.userName)}</span>
            <span className="uname">{meta.userName}</span></span>)}
        <ThemeToggle />
      </div>
    </header>
  );
}

export default function Shell() {
  const { resolved } = useTheme();
  return (
    <div className="shell">
      <div className="rail-slot"><Rail /></div>
      <div className="main">
        <Topbar />
        {/* keyed by theme: charts read the CSS variables when they are BUILT, so a theme change remounts them */}
        <div className="page" key={resolved}><Outlet /></div>
        <footer className="foot">
          Chiffres calculés côté serveur depuis <code>data/finance.db</code>.
          Informations à visée personnelle, pas un conseil en investissement réglementé.
        </footer>
      </div>
    </div>
  );
}
