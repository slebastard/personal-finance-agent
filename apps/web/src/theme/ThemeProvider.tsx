import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemePref = 'system' | 'light' | 'dark';
export type Resolved = 'light' | 'dark';

const KEY = 'pfa-theme';
const query = () => window.matchMedia('(prefers-color-scheme: dark)');

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch { return 'system'; }
}

const resolve = (pref: ThemePref): Resolved =>
  pref === 'system' ? (query().matches ? 'dark' : 'light') : pref;

function apply(pref: ThemePref): Resolved {
  const r = resolve(pref);
  const h = document.documentElement;
  h.dataset.theme = r;
  h.dataset.themePref = pref;
  h.style.colorScheme = r;
  return r;
}

interface Ctx { pref: ThemePref; resolved: Resolved; setPref: (p: ThemePref) => void }
const ThemeCtx = createContext<Ctx>({ pref: 'system', resolved: 'light', setPref: () => undefined });
export const useTheme = () => useContext(ThemeCtx);

/**
 * Three states — system, light, dark — because "follow my OS" is a real choice and the OS can change
 * while a tab is open. The first paint is handled by the inline script in index.html; this keeps React,
 * localStorage and the data-theme attribute in step afterwards. Charts read their colours from the CSS
 * variables at the moment they are built, so the page remounts its content when `resolved` changes.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [resolved, setResolved] = useState<Resolved>(() => apply(readPref()));

  useEffect(() => { setResolved(apply(pref)); }, [pref]);
  useEffect(() => {
    if (pref !== 'system') return undefined;
    const mq = query();
    const on = () => setResolved(apply('system'));
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [pref]);

  const setPref = useCallback((p: ThemePref) => {
    try { localStorage.setItem(KEY, p); } catch { /* storage blocked: the choice lasts this session */ }
    setPrefState(p);
  }, []);
  const value = useMemo(() => ({ pref, resolved, setPref }), [pref, resolved, setPref]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}
