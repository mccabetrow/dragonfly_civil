import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShellNew from './layouts/AppShellNew';
import { ToastProvider } from './components/ui/Toast';
import { RefreshProvider } from './context/RefreshContext';
import CommandPalette from './components/ui/CommandPalette';
// Dashboard pages - using new enterprise-grade layouts
import ExecutiveDashboardPageNew from './pages/ExecutiveDashboardPageNew';
import OpsPage from './pages/OpsPage';
import CollectabilityPageNew from './pages/CollectabilityPageNew';
import CasesPageNew from './pages/CasesPageNew';
import SettingsPageNew from './pages/SettingsPageNew';
import HelpPageNew from './pages/HelpPageNew';
// Legacy pages (kept for reference, not wired)
// import OverviewPage from './pages/OverviewPage';

const App: React.FC = () => {
  return (
    <ToastProvider>
      <RefreshProvider>
        <BrowserRouter>
          <CommandPalette />
          <Routes>
            <Route element={<AppShellNew />}>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              <Route path="/overview" element={<ExecutiveDashboardPageNew />} />
              <Route path="/ops" element={<OpsPage />} />
              <Route path="/collectability" element={<CollectabilityPageNew />} />
              <Route path="/cases" element={<CasesPageNew />} />
              <Route path="/settings" element={<SettingsPageNew />} />
              <Route path="/help" element={<HelpPageNew />} />
              <Route path="*" element={<Navigate to="/overview" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </RefreshProvider>
    </ToastProvider>
  );
};

export default App;
