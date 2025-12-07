import type { ComponentType } from 'react';
import OverviewPage from '../pages/OverviewPage';
import PortfolioDashboardPage from '../pages/PortfolioDashboardPage';
import ExecutiveDashboardPageNew from '../pages/ExecutiveDashboardPageNew';
import CollectabilityPage from '../pages/CollectabilityPage';
import PipelineDashboard from '../pages/PipelineDashboard';
import CallQueuePage from '../pages/CallQueuePage';
import EnforcementPage from '../pages/EnforcementPage';
import CasesPage from '../pages/CasesPage';
import { OpsConsolePage } from '../pages/OpsConsolePageNew';
import MomEnforcementConsolePage from '../pages/MomEnforcementConsolePage';
import SettingsPageNew from '../pages/SettingsPageNew';
import HelpPage from '../pages/HelpPage';

export interface NavigationRoute {
  label: string;
  path: string;
  component: ComponentType;
  /** Primary routes shown prominently; secondary routes shown in a divider section */
  primary?: boolean;
}

/**
 * Navigation routes ordered for daily ops workflow:
 * 1. Dashboard - CEO/investor portfolio overview (primary landing)
 * 2. Judgments - Cases list and details
 * 3. Enforcement - Active matters
 * 4. Settings - Configuration
 */
export const NAVIGATION_ROUTES: NavigationRoute[] = [
  // Primary navigation (CEO-focused)
  { label: 'Dashboard', path: '/dashboard', component: PortfolioDashboardPage, primary: true },
  { label: 'Judgments', path: '/cases', component: CasesPage, primary: true },
  { label: 'Enforcement', path: '/enforcement', component: EnforcementPage, primary: true },
  { label: 'Settings', path: '/settings', component: SettingsPageNew, primary: true },
  // Ops workflow routes (secondary)
  { label: 'Ops Console', path: '/ops-console', component: OpsConsolePage },
  { label: 'Mom Console', path: '/mom-console', component: MomEnforcementConsolePage },
  { label: 'Scoreboard', path: '/exec-dashboard', component: ExecutiveDashboardPageNew },
  { label: 'Pipeline', path: '/pipeline', component: PipelineDashboard },
  // Legacy / utility routes
  { label: 'Overview', path: '/overview', component: OverviewPage },
  { label: 'Collectability', path: '/collectability', component: CollectabilityPage },
  { label: 'Call Queue', path: '/call-queue', component: CallQueuePage },
  { label: 'Help', path: '/help', component: HelpPage },
];

/** Subset of routes for primary nav display */
export const PRIMARY_ROUTES = NAVIGATION_ROUTES.filter((r) => r.primary);

/** Subset of routes for secondary/utility nav */
export const SECONDARY_ROUTES = NAVIGATION_ROUTES.filter((r) => !r.primary);
