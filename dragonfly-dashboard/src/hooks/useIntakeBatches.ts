/**
 * useIntakeBatches - Hook for the Ops Command Center intake monitoring
 *
 * Fetches batch data from /api/v1/intake/batches via apiClient.
 * Designed for the Intake Station pane.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type IntakeBatchStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface IntakeBatch {
  id: string;
  filename: string;
  source: string;
  status: IntakeBatchStatus;
  totalRows: number;
  validRows: number;
  errorRows: number;
  successRate: number;
  durationSeconds: number | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  createdBy: string | null;
  workerId: string | null;
  recentErrors: IntakeBatchError[] | null;
}

export interface IntakeBatchError {
  row: number;
  code: string;
  message: string;
}

export interface IntakeBatchesState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'demo_locked';
  error: string | null;
  isAuthError: boolean;
  isNotFound: boolean;
  isError: boolean;
}

export interface UseIntakeBatchesResult {
  state: IntakeBatchesState;
  batches: IntakeBatch[];
  activeBatch: IntakeBatch | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_BATCHES: IntakeBatch[] = [
  {
    id: 'demo-batch-001',
    filename: 'simplicity_export_dec.csv',
    source: 'simplicity',
    status: 'completed',
    totalRows: 156,
    validRows: 152,
    errorRows: 4,
    successRate: 97.4,
    durationSeconds: 12,
    createdAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    startedAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    completedAt: new Date(Date.now() - 1000 * 60 * 29).toISOString(),
    createdBy: 'ops@dragonfly.com',
    workerId: 'worker-1',
    recentErrors: [
      { row: 45, code: 'PARSE_ERROR', message: 'Invalid date format' },
      { row: 89, code: 'VALIDATION_ERROR', message: 'Missing case number' },
    ],
  },
  {
    id: 'demo-batch-002',
    filename: 'jbi_weekly_batch.csv',
    source: 'jbi',
    status: 'processing',
    totalRows: 230,
    validRows: 180,
    errorRows: 0,
    successRate: 78.3,
    durationSeconds: null,
    createdAt: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    startedAt: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    completedAt: null,
    createdBy: 'ops@dragonfly.com',
    workerId: 'worker-2',
    recentErrors: null,
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useIntakeBatches(limit = 20): UseIntakeBatchesResult {
  const [state, setState] = useState<IntakeBatchesState>({
    status: 'idle',
    error: null,
    isAuthError: false,
    isNotFound: false,
    isError: false,
  });
  const [batches, setBatches] = useState<IntakeBatch[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchBatches = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setState({ status: 'demo_locked', error: null, isAuthError: false, isNotFound: false, isError: false });
      setBatches(DEMO_BATCHES);
      setLastUpdated(new Date());
      return;
    }

    setState({ status: 'loading', error: null, isAuthError: false, isNotFound: false, isError: false });

    try {
      interface ApiBatchResponse {
        batches: Array<Record<string, unknown>>;
      }

      const response = await apiClient.get<ApiBatchResponse>(`/api/v1/intake/batches?limit=${limit}`);
      const parsed = (response.batches ?? []).map(parseIntakeBatch);
      
      setBatches(parsed);
      setState({ status: 'ready', error: null, isAuthError: false, isNotFound: false, isError: false });
      setLastUpdated(new Date());
    } catch (err) {
      console.error('[useIntakeBatches]', err);

      if (err instanceof AuthError) {
        setState({
          status: 'error',
          error: 'Invalid API key – check Vercel VITE_DRAGONFLY_API_KEY vs Railway DRAGONFLY_API_KEY.',
          isAuthError: true,
          isNotFound: false,
          isError: false,
        });
      } else if (err instanceof NotFoundError) {
        setState({
          status: 'error',
          error: 'Intake batches endpoint not configured yet.',
          isAuthError: false,
          isNotFound: true,
          isError: false,
        });
      } else {
        const message = err instanceof Error ? err.message : 'Something went wrong. Please try again.';
        setState({
          status: 'error',
          error: message,
          isAuthError: false,
          isNotFound: false,
          isError: true,
        });
      }
      // In error state, show demo data as fallback
      setBatches(DEMO_BATCHES);
    }
  }, [limit]);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  useOnRefresh(fetchBatches);

  // Find the currently active (processing) batch
  const activeBatch = batches.find((b) => b.status === 'processing') ?? null;

  return {
    state,
    batches,
    activeBatch,
    refetch: fetchBatches,
    lastUpdated,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// PARSER
// ═══════════════════════════════════════════════════════════════════════════

function parseIntakeBatch(row: Record<string, unknown>): IntakeBatch {
  // Parse recent_errors from JSONB
  let recentErrors: IntakeBatchError[] | null = null;
  if (row.recent_errors && Array.isArray(row.recent_errors)) {
    recentErrors = (row.recent_errors as Array<Record<string, unknown>>).map((e) => ({
      row: Number(e.row ?? 0),
      code: String(e.code ?? 'UNKNOWN'),
      message: String(e.message ?? ''),
    }));
  }

  return {
    id: String(row.id ?? ''),
    filename: String(row.filename ?? ''),
    source: String(row.source ?? 'unknown'),
    status: (row.status as IntakeBatchStatus) ?? 'pending',
    totalRows: Number(row.total_rows ?? 0),
    validRows: Number(row.valid_rows ?? 0),
    errorRows: Number(row.error_rows ?? 0),
    successRate: Number(row.success_rate ?? 0),
    durationSeconds: row.duration_seconds != null ? Number(row.duration_seconds) : null,
    createdAt: String(row.created_at ?? ''),
    startedAt: row.started_at ? String(row.started_at) : null,
    completedAt: row.completed_at ? String(row.completed_at) : null,
    createdBy: row.created_by ? String(row.created_by) : null,
    workerId: row.worker_id ? String(row.worker_id) : null,
    recentErrors,
  };
}

export default useIntakeBatches;
