/**
 * useDataIntegrity - Hook for interacting with the Data Integrity API
 *
 * Provides:
 * - Dashboard stats (total rows, integrity score, failed count)
 * - List of failed rows (dead letter queue)
 * - Retry functionality for individual failed rows
 * - Batch verification
 */
import { useCallback, useEffect, useState } from 'react';
import { useOnRefresh } from '../context/RefreshContext';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IntegrityDashboard {
  total_rows_ingested: number;
  rows_successfully_stored: number;
  rows_with_discrepancies: number;
  integrity_score_pct: number;
  batches_processed: number;
  batches_with_issues: number;
  pending_resolution: number;
  resolved_count: number;
  last_check_at: string | null;
}

export interface FailedRow {
  id: string;
  batch_id: string;
  batch_name: string | null;
  row_index: number;
  source_hash: string | null;
  discrepancy_type: string;
  error_message: string | null;
  raw_data: Record<string, unknown> | null;
  resolution_status: 'pending' | 'resolved' | 'ignored' | 'retry_scheduled';
  resolution_notes: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  retry_count: number;
  created_at: string;
}

export interface BatchVerification {
  batch_id: string;
  batch_name: string | null;
  csv_row_count: number;
  db_row_count: number;
  match_count: number;
  mismatch_count: number;
  missing_in_db: number;
  verification_passed: boolean;
  discrepancies: VerificationDiscrepancy[];
  verified_at: string;
}

export interface VerificationDiscrepancy {
  row_index: number;
  issue_type: string;
  description: string;
}

export interface IntegrityApiError {
  status: number;
  message: string;
  isAuthError: boolean;
  isNotFound?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPER: Convert apiClient errors to IntegrityApiError
// ═══════════════════════════════════════════════════════════════════════════

function toIntegrityError(err: unknown): IntegrityApiError {
  if (err instanceof AuthError) {
    return { status: 401, message: err.message, isAuthError: true, isNotFound: false };
  }
  if (err instanceof NotFoundError) {
    return { status: 404, message: err.message, isAuthError: false, isNotFound: true };
  }
  if (err instanceof Error) {
    return { status: 500, message: err.message, isAuthError: false, isNotFound: false };
  }
  return { status: 500, message: 'Unknown error', isAuthError: false, isNotFound: false };
}

// ═══════════════════════════════════════════════════════════════════════════
// API FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

export async function fetchIntegrityDashboard(): Promise<IntegrityDashboard> {
  return apiClient.get<IntegrityDashboard>('/api/v1/integrity/dashboard');
}

export async function fetchFailedRows(
  limit = 50,
  offset = 0,
  status?: string
): Promise<{ rows: FailedRow[]; total: number }> {
  let url = `/api/v1/integrity/discrepancies?limit=${limit}&offset=${offset}`;
  if (status) {
    url += `&status=${encodeURIComponent(status)}`;
  }
  return apiClient.get<{ rows: FailedRow[]; total: number }>(url);
}

export async function retryFailedRow(id: string): Promise<{ success: boolean; message: string }> {
  return apiClient.post<{ success: boolean; message: string }>(
    `/api/v1/integrity/discrepancies/${id}/retry`,
    {}
  );
}

export async function ignoreFailedRow(id: string, notes?: string): Promise<{ success: boolean }> {
  return apiClient.post<{ success: boolean }>(
    `/api/v1/integrity/discrepancies/${id}/dismiss`,
    { resolution_notes: notes }
  );
}

export async function verifyBatch(batchId: string): Promise<BatchVerification> {
  return apiClient.get<BatchVerification>(`/api/v1/integrity/batches/${batchId}/verify`);
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useIntegrityDashboard
// ═══════════════════════════════════════════════════════════════════════════

export function useIntegrityDashboard() {
  const [data, setData] = useState<IntegrityDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<IntegrityApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchIntegrityDashboard();
      setData(result);
    } catch (err) {
      setError(toIntegrityError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useOnRefresh(load);

  return { data, loading, error, refetch: load };
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useFailedRows
// ═══════════════════════════════════════════════════════════════════════════

interface UseFailedRowsOptions {
  limit?: number;
  status?: string;
}

export function useFailedRows(options: UseFailedRowsOptions = {}) {
  const { limit = 50, status } = options;
  const [rows, setRows] = useState<FailedRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<IntegrityApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFailedRows(limit, offset, status);
      setRows(result.rows);
      setTotal(result.total);
    } catch (err) {
      setError(toIntegrityError(err));
    } finally {
      setLoading(false);
    }
  }, [limit, offset, status]);

  useEffect(() => {
    load();
  }, [load]);

  useOnRefresh(load);

  const nextPage = useCallback(() => {
    if (offset + limit < total) {
      setOffset((prev) => prev + limit);
    }
  }, [offset, limit, total]);

  const prevPage = useCallback(() => {
    if (offset > 0) {
      setOffset((prev) => Math.max(0, prev - limit));
    }
  }, [offset, limit]);

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  return {
    rows,
    total,
    loading,
    error,
    refetch: load,
    pagination: {
      currentPage,
      totalPages,
      hasNext: offset + limit < total,
      hasPrev: offset > 0,
      nextPage,
      prevPage,
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// TYPES: Batch Integrity
// ═══════════════════════════════════════════════════════════════════════════

export interface BatchIntegrity {
  batch_id: string;
  source: string | null;
  filename: string;
  csv_row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  batch_status: string;
  integrity_status: 'pending' | 'verified' | 'discrepancy' | 'skipped' | null;
  verified_at: string | null;
  verification_notes: string | null;
  db_row_count: number;
  audit_entries: number;
  pending_discrepancies: number;
  integrity_score: number;
  status_color: 'GREEN' | 'RED' | 'YELLOW' | 'GRAY';
  created_at: string;
  processed_at: string | null;
}

export interface BatchIntegrityCheck {
  batch_id: string;
  csv_row_count: number;
  db_row_count: number;
  audit_log_count: number;
  discrepancy_count: number;
  integrity_score: number;
  status: string;
  is_verified: boolean;
  verification_message: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// API FUNCTIONS: Batch Integrity
// ═══════════════════════════════════════════════════════════════════════════

export async function fetchBatchIntegrityList(
  limit = 50,
  status?: string
): Promise<{ batches: BatchIntegrity[]; total: number }> {
  let url = `/api/v1/integrity/batches/integrity?limit=${limit}`;
  if (status) {
    url += `&status=${encodeURIComponent(status)}`;
  }
  return apiClient.get<{ batches: BatchIntegrity[]; total: number }>(url);
}

export async function checkBatchIntegrity(batchId: string): Promise<BatchIntegrityCheck> {
  return apiClient.post<BatchIntegrityCheck>(
    `/api/v1/integrity/batches/${batchId}/check-integrity`,
    {}
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useBatchIntegrityList
// ═══════════════════════════════════════════════════════════════════════════

interface UseBatchIntegrityOptions {
  limit?: number;
  status?: string;
}

export function useBatchIntegrityList(options: UseBatchIntegrityOptions = {}) {
  const { limit = 50, status } = options;
  const [batches, setBatches] = useState<BatchIntegrity[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<IntegrityApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBatchIntegrityList(limit, status);
      setBatches(result.batches);
      setTotal(result.total);
    } catch (err) {
      setError(toIntegrityError(err));
    } finally {
      setLoading(false);
    }
  }, [limit, status]);

  useEffect(() => {
    load();
  }, [load]);

  useOnRefresh(load);

  return { batches, total, loading, error, refetch: load };
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useBatchVerification
// ═══════════════════════════════════════════════════════════════════════════

export function useBatchVerification(batchId: string | null) {
  const [data, setData] = useState<BatchVerification | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<IntegrityApiError | null>(null);

  const verify = useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await verifyBatch(batchId);
      setData(result);
    } catch (err) {
      setError(toIntegrityError(err));
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  return { data, loading, error, verify };
}

