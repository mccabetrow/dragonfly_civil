import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './layouts/AppShellNew';
import { ToastProvider } from './components/ui/Toast';
import OverviewPage from './pages/OverviewPage';
import CollectabilityPage from './pages/CollectabilityPage';
import CasesPage from './pages/CasesPage';
import SettingsPage from './pages/SettingsPage';
import HelpPage from './pages/HelpPage';

const App: React.FC = () => {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/collectability" element={<CollectabilityPage />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/help" element={<HelpPage />} />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
};

export default App;
