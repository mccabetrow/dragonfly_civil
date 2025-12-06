/**
 * useIngestBatches - Hook for interacting with the Dragonfly Engine ingest API
 *
 * Provides functions to:
 * - Upload CSV files
 * - List recent batches
 * - Get batch details
 * - Get batch errors
 */
import { useCallback, useEffect, useState } from 'react';
import { useOnRefresh } from '../context/RefreshContext';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IngestBatch {
  id: string;
  source: string;
  filename: string;
  row_count_raw: number;
  row_count_valid: number;
  row_count_invalid: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  error_summary: string | null;
  created_at: string | null;
  processed_at: string | null;
  created_by: string | null;
  success_rate_pct?: number;
}

export interface BatchErrorRow {
  row_index: number;
  validation_errors: string[] | null;
  plaintiff_name: string | null;
  defendant_name: string | null;
  case_number: string | null;
  judgment_amount: number | null;
  judgment_date: string | null;
  court: string | null;
}

export interface UploadResult {
  batch_id: string;
  filename: string;
  row_count_raw: number;
  row_count_valid: number;
  row_count_invalid: number;
  status: string;
  message: string;
}

export interface IngestApiError {
  status: number;
  message: string;
  isAuthError: boolean;
  isNotFound?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPER: Convert apiClient errors to IngestApiError
// ═══════════════════════════════════════════════════════════════════════════

function toIngestError(err: unknown): IngestApiError {
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

export async function uploadSimplicityCSV(file: File): Promise<UploadResult> {
  return apiClient.upload<UploadResult>('/api/v1/ingest/simplicity/upload', file);
}

export async function fetchBatches(limit = 50): Promise<IngestBatch[]> {
  const data = await apiClient.get<{ batches: IngestBatch[]; count: number }>(
    `/api/v1/ingest/batches?limit=${limit}`
  );
  return data.batches;
}

export async function fetchBatchDetail(batchId: string): Promise<IngestBatch> {
  return apiClient.get<IngestBatch>(`/api/v1/ingest/batch/${batchId}`);
}

export async function fetchBatchErrors(
  batchId: string,
  limit = 100
): Promise<BatchErrorRow[]> {
  const data = await apiClient.get<{ batch_id: string; errors: BatchErrorRow[]; count: number }>(
    `/api/v1/ingest/batch/${batchId}/errors?limit=${limit}`
  );
  return data.errors;
}

export async function processBatch(
  batchId: string
): Promise<{ status: string; rows_inserted: number; rows_updated: number }> {
  return apiClient.post(`/api/v1/ingest/batch/${batchId}/process`, {});
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useIngestBatches
// ═══════════════════════════════════════════════════════════════════════════

export interface UseIngestBatchesResult {
  batches: IngestBatch[];
  loading: boolean;
  error: IngestApiError | null;
  refetch: () => Promise<void>;
}

export function useIngestBatches(): UseIngestBatchesResult {
  const [batches, setBatches] = useState<IngestBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<IngestApiError | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await fetchBatches();
      setBatches(data);
    } catch (err) {
      setError(toIngestError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    refetch();
  }, [refetch]);

  // Subscribe to refresh bus
  useOnRefresh(refetch);

  return { batches, loading, error, refetch };
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK: useBatchDetail
// ═══════════════════════════════════════════════════════════════════════════

export interface UseBatchDetailResult {
  batch: IngestBatch | null;
  errors: BatchErrorRow[];
  loading: boolean;
  error: IngestApiError | null;
  refetch: () => Promise<void>;
}

export function useBatchDetail(batchId: string | null): UseBatchDetailResult {
  const [batch, setBatch] = useState<IngestBatch | null>(null);
  const [errors, setErrors] = useState<BatchErrorRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<IngestApiError | null>(null);

  const refetch = useCallback(async () => {
    if (!batchId) {
      setBatch(null);
      setErrors([]);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const [batchData, errorsData] = await Promise.all([
        fetchBatchDetail(batchId),
        fetchBatchErrors(batchId),
      ]);
      setBatch(batchData);
      setErrors(errorsData);
    } catch (err) {
      setError(toIngestError(err));
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { batch, errors, loading, error, refetch };
}
