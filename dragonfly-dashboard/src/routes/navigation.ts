import type { ComponentType } from 'react';
import OverviewPage from '../pages/OverviewPage';
import ExecutiveDashboardPageNew from '../pages/ExecutiveDashboardPageNew';
import CollectabilityPage from '../pages/CollectabilityPage';
import PipelineDashboard from '../pages/PipelineDashboard';
import CallQueuePage from '../pages/CallQueuePage';
import EnforcementPage from '../pages/EnforcementPage';
import CasesPage from '../pages/CasesPage';
import { OpsConsolePage } from '../pages/OpsConsolePageNew';
import MomEnforcementConsolePage from '../pages/MomEnforcementConsolePage';
import SettingsPage from '../pages/SettingsPage';
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
 * 1. Ops Console - Mom's home base (call queue + daily progress)
 * 2. Scoreboard - Dad's executive view
 * 3. Pipeline - Funnel health check
 * 4. Cases - Search and detail views
 * 5. Enforcement - Active matters
 * Remaining routes are secondary (settings, help, legacy pages)
 */
export const NAVIGATION_ROUTES: NavigationRoute[] = [
  // Primary workflow routes
  { label: 'Ops Console', path: '/ops-console', component: OpsConsolePage, primary: true },
  { label: 'Mom Console', path: '/mom-console', component: MomEnforcementConsolePage, primary: true },
  { label: 'Scoreboard', path: '/exec-dashboard', component: ExecutiveDashboardPageNew, primary: true },
  { label: 'Pipeline', path: '/pipeline', component: PipelineDashboard, primary: true },
  { label: 'Cases', path: '/cases', component: CasesPage, primary: true },
  { label: 'Enforcement', path: '/enforcement', component: EnforcementPage, primary: true },
  // Secondary / legacy routes
  { label: 'Overview', path: '/overview', component: OverviewPage },
  { label: 'Collectability', path: '/collectability', component: CollectabilityPage },
  { label: 'Call Queue', path: '/call-queue', component: CallQueuePage },
  { label: 'Settings', path: '/settings', component: SettingsPage },
  { label: 'Help', path: '/help', component: HelpPage },
];

/** Subset of routes for primary nav display */
export const PRIMARY_ROUTES = NAVIGATION_ROUTES.filter((r) => r.primary);

/** Subset of routes for secondary/utility nav */
export const SECONDARY_ROUTES = NAVIGATION_ROUTES.filter((r) => !r.primary);
