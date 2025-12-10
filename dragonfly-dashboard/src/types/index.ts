/**
 * Dragonfly Civil - Shared TypeScript Types
 * 
 * Centralized type definitions for the entire application.
 * All types used across pages, components, and hooks should be defined here.
 */

// ═══════════════════════════════════════════════════════════════════════════
// CORE DOMAIN TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Collectability tiers representing case priority
 */
export type Tier = 'A' | 'B' | 'C';

/**
 * Case status in the enforcement pipeline
 */
export type CaseStatus =
  | 'new'
  | 'active'
  | 'pending'
  | 'in_progress'
  | 'escalated'
  | 'collected'
  | 'closed'
  | 'archived';

/**
 * FOIL request status
 */
export type FoilStatus =
  | 'pending'
  | 'submitted'
  | 'received'
  | 'reviewed'
  | 'expired'
  | 'denied';

// ═══════════════════════════════════════════════════════════════════════════
// DATABASE MODELS (matching Supabase tables)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Judgment record from `public.judgments` table
 */
export interface Judgment {
  id: string;
  case_number: string;
  defendant_name: string;
  plaintiff_id?: string;
  judgment_amount: number;
  interest_rate?: number;
  judgment_date?: string;
  filing_date?: string;
  county?: string;
  court?: string;
  status?: CaseStatus;
  notes?: string;
  created_at: string;
  updated_at: string;
}

/**
 * Plaintiff record from `public.plaintiffs` table
 */
export interface Plaintiff {
  id: string;
  name: string;
  contact_email?: string;
  contact_phone?: string;
  attorney_name?: string;
  firm_name?: string;
  address?: string;
  city?: string;
  state?: string;
  zip?: string;
  status?: string;
  tier?: Tier;
  created_at: string;
  updated_at: string;
}

/**
 * FOIL response record from `public.foil_responses` table
 */
export interface FoilResponse {
  id: string;
  case_id: string;
  case_number?: string;
  defendant_name?: string;
  request_date?: string;
  response_date?: string;
  status: FoilStatus;
  agency?: string;
  notes?: string;
  created_at: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// VIEW MODELS (matching Supabase views)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Row from `v_collectability_snapshot` view
 */
export interface CollectabilityRow {
  case_id: string;
  case_number: string;
  defendant_name: string;
  plaintiff_name?: string;
  judgment_amount: number;
  interest_accrued?: number;
  total_owed?: number;
  collectability_score?: number;
  tier: Tier;
  age_days?: number;
  last_activity_date?: string;
  status?: string;
  county?: string;
  priority_rank?: number;
}

/**
 * Aggregated tier summary
 */
export interface TierSummary {
  tier: Tier;
  caseCount: number;
  totalValue: number;
  percentOfTotal?: number;
}

/**
 * Row from `v_plaintiffs_overview` view
 */
export interface PlaintiffOverview {
  id: string;
  name: string;
  total_cases: number;
  total_judgment_value: number;
  tier_a_count: number;
  tier_b_count: number;
  tier_c_count: number;
  status?: string;
  last_activity_date?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// UI STATE TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Status for async data fetching operations
 */
export type DataStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'error'
  | 'demo_locked';

/**
 * Generic async state wrapper
 */
export interface AsyncState<T> {
  status: DataStatus;
  data: T | null;
  error: Error | null;
  lastUpdated?: Date;
}

/**
 * Filter state for case tables
 */
export interface CaseFilters {
  search?: string;
  tier?: Tier | 'all';
  status?: CaseStatus | 'all';
  county?: string | 'all';
  minAmount?: number;
  maxAmount?: number;
  sortBy?: string;
  sortDirection?: 'asc' | 'desc';
}

/**
 * Pagination state
 */
export interface PaginationState {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// ACTION & TASK TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Type of action to take on a case
 */
export type ActionType =
  | 'call'
  | 'email'
  | 'file'
  | 'review'
  | 'follow_up'
  | 'escalate'
  | 'foil';

/**
 * Urgency level for actions
 */
export type ActionUrgency = 'low' | 'normal' | 'high' | 'overdue';

/**
 * Action item for the action queue
 */
export interface ActionItem {
  id: string;
  type: ActionType;
  title: string;
  caseNumber?: string;
  defendant?: string;
  amount?: number;
  tier?: Tier;
  dueDate?: Date | string;
  urgency?: ActionUrgency;
  completed?: boolean;
  notes?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// DASHBOARD METRICS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Dashboard metrics snapshot
 */
export interface DashboardMetrics {
  totalCases: number;
  totalValue: number;
  activeCases: number;
  pendingActions: number;
  collectedThisMonth: number;
  collectedTotal: number;
  tierBreakdown: TierSummary[];
  foilPending: number;
  escalatedCases: number;
}

/**
 * Individual metric with optional trend data
 */
export interface Metric {
  value: number | string;
  previousValue?: number;
  label: string;
  description?: string;
  format?: 'number' | 'currency' | 'percent';
}

// ═══════════════════════════════════════════════════════════════════════════
// API & SUPABASE TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Generic Supabase response wrapper
 */
export interface SupabaseResponse<T> {
  data: T | null;
  error: Error | null;
  count?: number;
}

/**
 * Common query options
 */
export interface QueryOptions {
  limit?: number;
  offset?: number;
  orderBy?: string;
  ascending?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// FORM & INPUT TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Form field validation state
 */
export interface FieldState {
  value: string;
  error?: string;
  touched: boolean;
}

/**
 * Case creation/update form data
 */
export interface CaseFormData {
  caseNumber: string;
  defendantName: string;
  plaintiffId?: string;
  judgmentAmount: number;
  judgmentDate?: string;
  county?: string;
  notes?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT PROP HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Common props for components that can be loading
 */
export interface LoadableProps {
  loading?: boolean;
}

/**
 * Common props for components with error states
 */
export interface ErrorableProps {
  error?: Error | string | null;
  onRetry?: () => void;
}

/**
 * Common props for clickable components
 */
export interface ClickableProps {
  onClick?: () => void;
  disabled?: boolean;
}

/**
 * Combine for common async component props
 */
export interface AsyncComponentProps extends LoadableProps, ErrorableProps {}

// ═══════════════════════════════════════════════════════════════════════════
// ENFORCEMENT ENGINE TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Enforcement Engine Worker metrics from analytics.v_enforcement_activity.
 * Used by the Enforcement Engine dashboard page for real-time monitoring.
 */
export interface EnforcementEngineMetrics {
  /** Enforcement plans created in the last 24 hours */
  plans_created_24h: number;
  /** Enforcement plans created in the last 7 days */
  plans_created_7d: number;
  /** Total enforcement plans ever created */
  total_plans: number;

  /** Draft packets generated in the last 24 hours */
  packets_generated_24h: number;
  /** Draft packets generated in the last 7 days */
  packets_generated_7d: number;
  /** Total draft packets ever generated */
  total_packets: number;

  /** Workers currently processing jobs */
  active_workers: number;
  /** Jobs waiting in the queue */
  pending_jobs: number;
  /** Jobs completed in the last 24 hours */
  completed_24h: number;
  /** Jobs that failed in the last 24 hours */
  failed_24h: number;

  /** Timestamp when metrics were generated */
  generated_at: string;
}

/**
 * Hook result type for useEnforcementEngineData
 */
export interface EnforcementEngineResult {
  data: EnforcementEngineMetrics | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}
