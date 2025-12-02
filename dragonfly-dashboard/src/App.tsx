import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShellNew from './layouts/AppShellNew';
import { ToastProvider } from './components/ui/Toast';
import { RefreshProvider } from './context/RefreshContext';
// Dashboard pages - using new enterprise-grade layouts
import ExecutiveDashboardPageNew from './pages/ExecutiveDashboardPageNew';
import CollectabilityPageNew from './pages/CollectabilityPageNew';
import CasesPageNew from './pages/CasesPageNew';
import SettingsPage from './pages/SettingsPage';
import HelpPage from './pages/HelpPage';
// Legacy pages (kept for reference, not wired)
// import OverviewPage from './pages/OverviewPage';

const App: React.FC = () => {
  return (
    <ToastProvider>
      <RefreshProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShellNew />}>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              <Route path="/overview" element={<ExecutiveDashboardPageNew />} />
              <Route path="/collectability" element={<CollectabilityPageNew />} />
              <Route path="/cases" element={<CasesPageNew />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="*" element={<Navigate to="/overview" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </RefreshProvider>
    </ToastProvider>
  );
};

export default App;
