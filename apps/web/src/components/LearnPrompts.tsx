import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { Card } from './ui';

const RUNGS: Record<number, string> = {
  1: 'Coûts et indexation', 2: 'Enveloppes françaises', 3: 'Le risque pour de vrai',
  4: 'Lire une entreprise', 5: 'Valorisation et taux de base', 6: 'Processus',
};

/**
 * Reading suggestions drawn from YOUR numbers. The catalogue is deterministic: each card carries
 * the data that triggered it, so you can check why it is there. The button copies the matching
 * `/learn` command; the conversation itself happens with the agent, not here.
 */
export function LearnPrompts({ isin }: { isin?: string }) {
  const { data } = useQuery({ queryKey: ['learn', isin ?? 'portfolio'], queryFn: () => api.learnPrompts(isin) });
  const [copied, setCopied] = useState<string | null>(null);
  if (!data?.length) return null;
  const copy = (id: string, cmd: string) => {
    void navigator.clipboard?.writeText(cmd);
    setCopied(id);
    setTimeout(() => setCopied(null), 1600);
  };
  return (
    <Card title="Pistes pour aller plus loin"
          caption="Choisies d'après tes données — chaque piste montre ce qui l'a déclenchée" wide>
      <div className="prompts">
        {data.map((p) => (
          <article className="prompt" key={p.id}>
            <h3>{p.title}</h3>
            <p className="q">{p.question}</p>
            <p className="ev"><span className="cap">Dans tes données</span> {p.evidence}</p>
            <p className="cap">{p.why}</p>
            {p.reading.length > 0 && (
              <ul className="cap">{p.reading.map((r) => (
                <li key={r.label}>{r.url
                  ? <a href={r.url} target="_blank" rel="noopener noreferrer">{r.label}</a> : r.label}</li>))}
              </ul>)}
            <div className="act">
              <button className="btn" onClick={() => copy(p.id, p.learn.command)}>
                {copied === p.id ? 'Copié ✓' : `Copier ${p.learn.command.split(' ')[0]}`}
              </button>
              <span className="cap">Niveau {p.learn.rung} · {RUNGS[p.learn.rung] ?? ''}</span>
            </div>
          </article>))}
      </div>
    </Card>
  );
}
