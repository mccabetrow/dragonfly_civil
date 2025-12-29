import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './layouts/AppShell';
import { ToastProvider } from './components/ui/Toast';
import { RefreshProvider } from './context/RefreshContext';
import CommandPalette from './components/ui/CommandPalette';
import SystemDiagnostics from './components/debug/SystemDiagnostics';
import DebugStatus from './components/debug/DebugStatus';
// Dashboard pages - using new enterprise-grade layouts
import PortfolioDashboardPage from './pages/PortfolioDashboardPage';
import ExecutiveDashboardPageNew from './pages/ExecutiveDashboardPageNew';
import OpsPage from './pages/OpsPage';
import OpsIntakePage from './pages/OpsIntakePage';
import IntakeStationPage from './pages/IntakeStationPageNew';
import CollectabilityPageNew from './pages/CollectabilityPageNew';
import CasesPageNew from './pages/CasesPageNew';
import SettingsPageNew from './pages/SettingsPageNew';
import DataIngestionPage from './pages/DataIngestionPage';
import DataIntegrityPage from './pages/DataIntegrityPage';
import HelpPageNew from './pages/HelpPageNew';
import EnforcementActionCenter from './pages/enforcement/EnforcementActionCenter';
import EnforcementEnginePage from './pages/enforcement/EnforcementEnginePage';
import OpsQueuePage from './pages/OpsQueuePage';
import CeoOverviewPage from './pages/CeoOverviewPage';
import OpsCommandCenter from './pages/ops/OpsCommandCenter';
import PortfolioPage from './pages/finance/Portfolio';
import PortfolioExplorerPage from './pages/PortfolioExplorerPage';
import ConfigDebug from './pages/debug/ConfigDebug';

const App: React.FC = () => {
  return (
    <ToastProvider>
      <RefreshProvider>
        <BrowserRouter>
          <CommandPalette />
          <SystemDiagnostics />
          <DebugStatus />
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<PortfolioDashboardPage />} />
              <Route path="/ceo/overview" element={<CeoOverviewPage />} />
              <Route path="/finance/portfolio" element={<PortfolioPage />} />
              <Route path="/portfolio/explorer" element={<PortfolioExplorerPage />} />
              <Route path="/overview" element={<ExecutiveDashboardPageNew />} />
              <Route path="/ops" element={<OpsPage />} />
              <Route path="/ops/intake" element={<OpsIntakePage />} />
              <Route path="/ops/queue" element={<OpsQueuePage />} />
              <Route path="/ops/console" element={<OpsCommandCenter />} />
              <Route path="/intake" element={<IntakeStationPage />} />
              <Route path="/radar" element={<EnforcementActionCenter />} />
              <Route path="/enforcement/engine" element={<EnforcementEnginePage />} />
              <Route path="/collectability" element={<CollectabilityPageNew />} />
              <Route path="/cases" element={<CasesPageNew />} />
              <Route path="/settings" element={<SettingsPageNew />} />
              <Route path="/settings/ingestion" element={<DataIngestionPage />} />
              <Route path="/settings/integrity" element={<DataIntegrityPage />} />
              <Route path="/help" element={<HelpPageNew />} />
              <Route path="/debug/config" element={<ConfigDebug />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </RefreshProvider>
    </ToastProvider>
  );
};

export default App;
