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
}

// ═══════════════════════════════════════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════════════════════════════════════

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const API_KEY = import.meta.env.VITE_DRAGONFLY_API_KEY || '';

function getHeaders(): HeadersInit {
  return {
    'X-API-KEY': API_KEY,
  };
}

function getJsonHeaders(): HeadersInit {
  return {
    'X-API-KEY': API_KEY,
    'Content-Type': 'application/json',
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const isAuthError = response.status === 401 || response.status === 403;
    let message = `HTTP ${response.status}`;

    try {
      const body = await response.json();
      message = body.detail || body.message || message;
    } catch {
      // Ignore JSON parse errors
    }

    const error: IngestApiError = {
      status: response.status,
      message,
      isAuthError,
    };
    throw error;
  }

  return response.json() as Promise<T>;
}

// ═══════════════════════════════════════════════════════════════════════════
// API FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

export async function uploadSimplicityCSV(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/api/v1/ingest/simplicity/upload`, {
    method: 'POST',
    headers: getHeaders(),
    body: formData,
  });

  return handleResponse<UploadResult>(response);
}

export async function fetchBatches(limit = 50): Promise<IngestBatch[]> {
  const response = await fetch(`${API_BASE}/api/v1/ingest/batches?limit=${limit}`, {
    headers: getHeaders(),
  });

  const data = await handleResponse<{ batches: IngestBatch[]; count: number }>(response);
  return data.batches;
}

export async function fetchBatchDetail(batchId: string): Promise<IngestBatch> {
  const response = await fetch(`${API_BASE}/api/v1/ingest/batch/${batchId}`, {
    headers: getHeaders(),
  });

  return handleResponse<IngestBatch>(response);
}

export async function fetchBatchErrors(
  batchId: string,
  limit = 100
): Promise<BatchErrorRow[]> {
  const response = await fetch(
    `${API_BASE}/api/v1/ingest/batch/${batchId}/errors?limit=${limit}`,
    {
      headers: getHeaders(),
    }
  );

  const data = await handleResponse<{ batch_id: string; errors: BatchErrorRow[]; count: number }>(
    response
  );
  return data.errors;
}

export async function processBatch(
  batchId: string
): Promise<{ status: string; rows_inserted: number; rows_updated: number }> {
  const response = await fetch(`${API_BASE}/api/v1/ingest/batch/${batchId}/process`, {
    method: 'POST',
    headers: getJsonHeaders(),
  });

  return handleResponse(response);
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
      setError(err as IngestApiError);
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
      setError(err as IngestApiError);
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { batch, errors, loading, error, refetch };
}
