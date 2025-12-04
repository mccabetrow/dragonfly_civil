/**
 * useIntakeQueue - Hook for fetching intake queue data
 * 
 * Fetches AI-validated leads awaiting ops review from v_intake_queue view.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { useOnRefresh } from '../context/RefreshContext';

export interface IntakeQueueRow {
  judgmentId: string;
  validationId: string;
  caseIndexNumber: string;
  debtorName: string;
  originalCreditor: string | null;
  judgmentDate: string | null;
  principalAmount: number | null;
  county: string | null;
  status: string;
  importedAt: string;
  validatedAt: string | null;
  validationResult: 'valid' | 'invalid' | 'needs_review' | null;
  confidenceScore: number | null;
  nameCheckPassed: boolean | null;
  nameCheckNote: string | null;
  addressCheckPassed: boolean | null;
  addressCheckNote: string | null;
  caseNumberCheckPassed: boolean | null;
  caseNumberCheckNote: string | null;
  queueStatus: 'pending_review' | 'auto_valid' | 'auto_invalid' | 'reviewed';
  reviewPriority: number;
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewDecision: string | null;
  reviewNotes: string | null;
}

interface RawIntakeQueueRow {
  judgment_id: string | null;
  validation_id: string | null;
  case_index_number: string | null;
  debtor_name: string | null;
  original_creditor: string | null;
  judgment_date: string | null;
  principal_amount: number | string | null;
  county: string | null;
  status: string | null;
  imported_at: string | null;
  validated_at: string | null;
  validation_result: string | null;
  confidence_score: number | null;
  name_check_passed: boolean | null;
  name_check_note: string | null;
  address_check_passed: boolean | null;
  address_check_note: string | null;
  case_number_check_passed: boolean | null;
  case_number_check_note: string | null;
  queue_status: string | null;
  review_priority: number | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_decision: string | null;
  review_notes: string | null;
}

const INTAKE_QUEUE_LOCK_MESSAGE =
  'Intake queue is available only in the production environment.';

function normalizeRow(raw: RawIntakeQueueRow): IntakeQueueRow {
  return {
    judgmentId: raw.judgment_id ?? '',
    validationId: raw.validation_id ?? '',
    caseIndexNumber: raw.case_index_number ?? '',
    debtorName: raw.debtor_name ?? 'Unknown',
    originalCreditor: raw.original_creditor ?? null,
    judgmentDate: raw.judgment_date ?? null,
    principalAmount: typeof raw.principal_amount === 'string' 
      ? parseFloat(raw.principal_amount) 
      : raw.principal_amount,
    county: raw.county ?? null,
    status: raw.status ?? 'unknown',
    importedAt: raw.imported_at ?? '',
    validatedAt: raw.validated_at ?? null,
    validationResult: (raw.validation_result as IntakeQueueRow['validationResult']) ?? null,
    confidenceScore: raw.confidence_score ?? null,
    nameCheckPassed: raw.name_check_passed ?? null,
    nameCheckNote: raw.name_check_note ?? null,
    addressCheckPassed: raw.address_check_passed ?? null,
    addressCheckNote: raw.address_check_note ?? null,
    caseNumberCheckPassed: raw.case_number_check_passed ?? null,
    caseNumberCheckNote: raw.case_number_check_note ?? null,
    queueStatus: (raw.queue_status as IntakeQueueRow['queueStatus']) ?? 'pending_review',
    reviewPriority: raw.review_priority ?? 0,
    reviewedBy: raw.reviewed_by ?? null,
    reviewedAt: raw.reviewed_at ?? null,
    reviewDecision: raw.review_decision ?? null,
    reviewNotes: raw.review_notes ?? null,
  };
}

export function useIntakeQueue(limit: number = 50): MetricsHookResult<IntakeQueueRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<IntakeQueueRow[]>>(() =>
    buildInitialMetricsState<IntakeQueueRow[]>(),
  );

  const fetchData = useCallback(async () => {
    // Demo mode check
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<IntakeQueueRow[]>(INTAKE_QUEUE_LOCK_MESSAGE));
      return;
    }

    setSnapshot(buildLoadingMetricsState<IntakeQueueRow[]>());

    try {
      const { data, error } = await supabaseClient
        .from('v_intake_queue')
        .select('*')
        .limit(limit);

      if (error) {
        console.error('[useIntakeQueue] Query error:', error);
        setSnapshot(buildErrorMetricsState<IntakeQueueRow[]>(error.message));
        return;
      }

      const normalized = (data as RawIntakeQueueRow[])
        .filter(row => row.judgment_id)
        .map(normalizeRow);

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error fetching intake queue';
      console.error('[useIntakeQueue] Exception:', err);
      setSnapshot(buildErrorMetricsState<IntakeQueueRow[]>(message));
    }
  }, [limit]);

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Refetch on global refresh
  useOnRefresh(fetchData);

  return { ...snapshot, state: snapshot, refetch: fetchData };
}

/**
 * Hook for submitting intake review decisions
 */
export function useSubmitIntakeReview() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitReview = useCallback(async (
    validationId: string,
    decision: 'approved' | 'rejected' | 'flagged',
    notes?: string
  ): Promise<boolean> => {
    if (IS_DEMO_MODE) {
      console.log('[useSubmitIntakeReview] Demo mode - simulating submit');
      return true;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const { data, error: rpcError } = await supabaseClient.rpc('submit_intake_review', {
        _validation_id: validationId,
        _decision: decision,
        _notes: notes || null,
      });

      if (rpcError) {
        console.error('[useSubmitIntakeReview] RPC error:', rpcError);
        setError(rpcError.message);
        return false;
      }

      return data === true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error submitting review';
      console.error('[useSubmitIntakeReview] Exception:', err);
      setError(message);
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  return {
    submitReview,
    isSubmitting,
    error,
  };
}

/**
 * Hook for fetching intake stats
 */
export interface IntakeStats {
  newCandidates: number;
  awaitingReview: number;
  approvedToday: number;
  rejectedToday: number;
  validationResults: {
    valid: number;
    invalid: number;
    needsReview: number;
  };
  pendingHumanReview: number;
  generatedAt: string;
}

export function useIntakeStats(): MetricsHookResult<IntakeStats | null> {
  const [snapshot, setSnapshot] = useState<MetricsState<IntakeStats | null>>(() =>
    buildInitialMetricsState<IntakeStats | null>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<IntakeStats | null>(INTAKE_QUEUE_LOCK_MESSAGE));
      return;
    }

    setSnapshot(buildLoadingMetricsState<IntakeStats | null>());

    try {
      const { data, error } = await supabaseClient.rpc('get_intake_stats');

      if (error) {
        console.error('[useIntakeStats] RPC error:', error);
        setSnapshot(buildErrorMetricsState<IntakeStats | null>(error.message));
        return;
      }

      const stats: IntakeStats = {
        newCandidates: data?.new_candidates ?? 0,
        awaitingReview: data?.awaiting_review ?? 0,
        approvedToday: data?.approved_today ?? 0,
        rejectedToday: data?.rejected_today ?? 0,
        validationResults: {
          valid: data?.validation_results?.valid ?? 0,
          invalid: data?.validation_results?.invalid ?? 0,
          needsReview: data?.validation_results?.needs_review ?? 0,
        },
        pendingHumanReview: data?.pending_human_review ?? 0,
        generatedAt: data?.generated_at ?? new Date().toISOString(),
      };

      setSnapshot(buildReadyMetricsState(stats));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error fetching intake stats';
      console.error('[useIntakeStats] Exception:', err);
      setSnapshot(buildErrorMetricsState<IntakeStats | null>(message));
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useOnRefresh(fetchData);

  return { ...snapshot, state: snapshot, refetch: fetchData };
}
