import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

/**
 * A term with its definition on hover or keyboard focus. The text comes from reference/glossary.json
 * (served by the API), so a definition has exactly one home. Each entry says what a high value
 * suggests AND what it does not prove, plus where the definition comes from.
 */
export function Def({ k, children }: { k: string; children: ReactNode }) {
  const { data } = useQuery({ queryKey: ['glossary'], queryFn: () => api.glossary(), staleTime: 3_600_000 });
  const g = data?.[k];
  if (!g) return <>{children}</>;
  return (
    <span className="def" tabIndex={0}>
      {children}
      <span className="pop" role="tooltip">
        <b>{g.label}</b>
        <span className="row"><i>Formule</i> {g.formula}</span>
        {g.high !== '—' && <span className="row"><i>Valeur haute</i> {g.high}</span>}
        {g.low !== '—' && <span className="row"><i>Valeur basse</i> {g.low}</span>}
        <span className="row"><i>À savoir</i> {g.caveat}</span>
        <span className="src">Source : {g.source}</span>
      </span>
    </span>
  );
}
