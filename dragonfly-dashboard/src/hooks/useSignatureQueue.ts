/**
 * Hook for v_enforcement_actions_pending_signature view
 * Shows enforcement actions awaiting attorney signature
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';

export type ActionType =
  | 'wage_garnishment'
  | 'bank_levy'
  | 'property_lien'
  | 'information_subpoena'
  | 'restraining_notice'
  | 'other';

export interface SignatureQueueRow {
  actionId: string;
  judgmentId: string;
  caseIndexNumber: string;
  debtorName: string;
  principalAmount: number;
  actionType: ActionType;
  status: string;
  notes: string | null;
  createdAt: string;
  ageDays: number;
  metadata: Record<string, unknown> | null;
}

interface RawSignatureRow {
  action_id: string | null;
  judgment_id: string | null;
  case_index_number: string | null;
  debtor_name: string | null;
  principal_amount: number | string | null;
  action_type: string | null;
  status: string | null;
  notes: string | null;
  created_at: string | null;
  age_days: number | string | null;
  metadata: Record<string, unknown> | null;
}

const SIGNATURE_VIEW = 'v_enforcement_actions_pending_signature' as const;
const SIGNATURE_LOCK_MESSAGE =
  'Signature queue is hidden in demo mode. Connect to production tenant to view pending actions.';

export const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  wage_garnishment: 'Wage Garnishment',
  bank_levy: 'Bank Levy',
  property_lien: 'Property Lien',
  information_subpoena: 'Info Subpoena',
  restraining_notice: 'Restraining Notice',
  other: 'Other',
};

export const ACTION_TYPE_COLORS: Record<ActionType, string> = {
  wage_garnishment: 'bg-violet-100 text-violet-700',
  bank_levy: 'bg-emerald-100 text-emerald-700',
  property_lien: 'bg-amber-100 text-amber-700',
  information_subpoena: 'bg-blue-100 text-blue-700',
  restraining_notice: 'bg-red-100 text-red-700',
  other: 'bg-slate-100 text-slate-600',
};

function parseRow(raw: RawSignatureRow): SignatureQueueRow | null {
  if (!raw.action_id || !raw.judgment_id) return null;

  return {
    actionId: raw.action_id,
    judgmentId: raw.judgment_id,
    caseIndexNumber: raw.case_index_number ?? '—',
    debtorName: raw.debtor_name ?? 'Unknown',
    principalAmount: typeof raw.principal_amount === 'number' ? raw.principal_amount : parseFloat(String(raw.principal_amount)) || 0,
    actionType: (raw.action_type as ActionType) ?? 'other',
    status: raw.status ?? 'unknown',
    notes: raw.notes ?? null,
    createdAt: raw.created_at ?? new Date().toISOString(),
    ageDays: Number(raw.age_days) || 0,
    metadata: raw.metadata ?? null,
  };
}

export type UseSignatureQueueResult = MetricsHookResult<SignatureQueueRow[]> & {
  totalCount: number;
  urgentCount: number; // > 3 days old
};

export function useSignatureQueue(): UseSignatureQueueResult {
  const [state, setState] = useState<MetricsState<SignatureQueueRow[]>>(buildInitialMetricsState());

  const fetchData = useCallback(async () => {
    setState(buildLoadingMetricsState());

    if (IS_DEMO_MODE) {
      setState(buildDemoLockedState(SIGNATURE_LOCK_MESSAGE));
      return;
    }

    try {
      const query = supabaseClient
        .from(SIGNATURE_VIEW)
        .select('*')
        .order('created_at', { ascending: true })
        .limit(100);

      const result = await demoSafeSelect<RawSignatureRow[]>(query);

      if (result.kind === 'demo_locked') {
        setState(buildDemoLockedState(SIGNATURE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        setState(buildErrorMetricsState(result.error.message));
        return;
      }

      const rows = result.data
        .map((r: RawSignatureRow) => parseRow(r))
        .filter((r): r is SignatureQueueRow => r !== null);

      setState(buildReadyMetricsState(rows));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load signature queue';
      setState(buildErrorMetricsState(message));
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const rows = state.data ?? [];
  const totalCount = rows.length;
  const urgentCount = rows.filter((r) => r.ageDays > 3).length;

  return {
    ...state,
    state,
    data: rows,
    refetch: fetchData,
    totalCount,
    urgentCount,
  };
}

/**
 * Mark an enforcement action as signed
 * Calls the update_enforcement_action_status RPC via service_role
 * Note: In production, this should go through the backend API at /api/enforcement/mark_signed
 */
export async function markActionSigned(
  actionId: string,
  notes?: string,
): Promise<{ success: boolean; error?: string }> {
  try {
    // Call the update_enforcement_action_status RPC
    // Note: This requires service_role. For anon users, route through backend API.
    const { error } = await supabaseClient.rpc('update_enforcement_action_status', {
      _action_id: actionId,
      _status: 'completed',
      _notes: notes ?? 'Signed and sent by attorney',
    });

    if (error) {
      return { success: false, error: error.message };
    }

    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to mark action as signed';
    return { success: false, error: message };
  }
}
