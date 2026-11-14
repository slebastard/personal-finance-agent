import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import Portfolio from './routes/Portfolio';
import Flows from './routes/Flows';
import Instrument from './routes/Instrument';
import Company from './routes/Company';
import '@fontsource-variable/outfit/wght.css';
import './theme.css';
import { ThemeProvider } from './theme/ThemeProvider';
import Shell from './layout/Shell';

// Short staleTime + refetch on focus: coming back to the tab after a `pfa sync` shows fresh
// figures. That is the whole point of having a server rather than a pre-rendered file.
const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: true, retry: 1 } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        {/* hash routing: works identically when served and when an archive is opened from file:// */}
        <HashRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route path="/portfolio" element={<Portfolio />} />
              <Route path="/flows" element={<Flows />} />
              <Route path="/instruments/:isin" element={<Instrument />} />
              <Route path="/companies/:isin" element={<Company />} />
              <Route path="*" element={<Navigate to="/portfolio" replace />} />
            </Route>
          </Routes>
        </HashRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
