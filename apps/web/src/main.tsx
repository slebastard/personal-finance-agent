import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom';
import Portfolio from './routes/Portfolio';
import Flows from './routes/Flows';
import Instrument from './routes/Instrument';
import Company from './routes/Company';
import './theme.css';

// Short staleTime + refetch on focus: coming back to the tab after a `pfa sync` shows fresh
// figures. That is the whole point of having a server rather than a pre-rendered file.
const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: true, retry: 1 } },
});

const tab = ({ isActive }: { isActive: boolean }) => (isActive ? 'on' : undefined);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      {/* hash routing: works identically when served and when an archive is opened from file:// */}
      <HashRouter>
        <div className="wrap">
          <nav className="tabs">
            <NavLink to="/portfolio" className={tab}>Portefeuille</NavLink>
            <NavLink to="/flows" className={tab}>Flux</NavLink>
          </nav>
          <Routes>
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/flows" element={<Flows />} />
            <Route path="/instruments/:isin" element={<Instrument />} />
            <Route path="/companies/:isin" element={<Company />} />
            <Route path="*" element={<Navigate to="/portfolio" replace />} />
          </Routes>
          <footer>
            Chiffres calculés côté serveur depuis <code>data/finance.db</code>.
            Informations à visée personnelle, pas un conseil en investissement réglementé.
          </footer>
        </div>
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>,
);
