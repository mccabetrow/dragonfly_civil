/**
 * Dragonfly API - Unified Frontend API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * High-level API wrapper for Vercel ↔ Railway connectivity.
 * This is the single source of truth for all frontend-to-backend calls.
 *
 * Go-Live Configuration:
 *   VITE_API_BASE_URL       - Railway backend URL (e.g., https://dragonfly.railway.app/api)
 *   VITE_DRAGONFLY_API_KEY  - API key for X-DRAGONFLY-API-KEY header
 *   VITE_SUPABASE_URL       - Supabase project URL
 *   VITE_SUPABASE_ANON_KEY  - Supabase anon key
 *
 * Usage:
 *   import { api } from '@/lib/api';
 *
 *   // Health check (never throws)
 *   const health = await api.checkBackendHealth();
 *   if (!health.ok) console.error(health.error);
 *
 *   // Upload file (returns result or throws)
 *   const result = await api.uploadBatch(file, 'simplicity');
 */

import { apiClient, AuthError, ApiError, NotFoundError } from './apiClient';
import type { HealthCheckResult } from './apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type DataSourceType = 'simplicity' | 'jbi' | 'foil' | 'manual' | 'api';

export interface BatchUploadResult {
  batchId: string;
  status: 'processing' | 'completed' | 'failed';
  message: string;
  rowCount?: number;
}

export interface BatchUploadError {
  ok: false;
  error: string;
  code: 'network' | 'auth' | 'validation' | 'server' | 'unknown';
  status?: number;
}

export interface BatchUploadSuccess {
  ok: true;
  data: BatchUploadResult;
}

export type BatchUploadResponse = BatchUploadSuccess | BatchUploadError;

// ═══════════════════════════════════════════════════════════════════════════
// API FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Check backend health - verifies Vercel ↔ Railway connectivity.
 *
 * Never throws. Returns a normalized result with ok/error status.
 *
 * @example
 *   const health = await api.checkBackendHealth();
 *   if (!health.ok) {
 *     showError(`Backend disconnected: ${health.error}`);
 *   }
 */
export async function checkBackendHealth(): Promise<HealthCheckResult> {
  return apiClient.checkHealth();
}

/**
 * Upload a CSV batch file to the intake pipeline.
 *
 * This POSTs the file to /api/v1/intake/upload, which:
 * 1. Saves the file and creates a batch record
 * 2. Starts background processing
 * 3. Returns batch_id immediately
 *
 * @param file - CSV file from file input or drag-and-drop
 * @param source - Data source type: 'simplicity' | 'jbi' | 'foil' | 'manual' | 'api'
 * @returns Normalized response with ok/error status
 *
 * @example
 *   const result = await api.uploadBatch(file, 'simplicity');
 *   if (result.ok) {
 *     toast.success(`✅ Batch ${result.data.batchId} queued!`);
 *   } else {
 *     toast.error(`❌ Upload failed: ${result.error}`);
 *   }
 */
export async function uploadBatch(
  file: File,
  source: DataSourceType = 'simplicity'
): Promise<BatchUploadResponse> {
  // Client-side validation
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return {
      ok: false,
      error: '❌ CSV Parse Failed: File must be a .csv file',
      code: 'validation',
    };
  }

  // Max 50MB for normal, 500MB for FOIL
  const maxSize = source === 'foil' ? 500 * 1024 * 1024 : 50 * 1024 * 1024;
  if (file.size > maxSize) {
    const sizeMB = source === 'foil' ? 500 : 50;
    return {
      ok: false,
      error: `❌ File too large: Maximum ${sizeMB}MB allowed`,
      code: 'validation',
    };
  }

  try {
    interface UploadResponse {
      batch_id: string;
      status: string;
      message: string;
      row_count?: number;
    }

    const data = await apiClient.upload<UploadResponse>(
      '/api/v1/intake/upload',
      file,
      { source }
    );

    return {
      ok: true,
      data: {
        batchId: data.batch_id,
        status: data.status as 'processing' | 'completed' | 'failed',
        message: data.message,
        rowCount: data.row_count,
      },
    };
  } catch (err) {
    // Map error types to user-friendly messages
    if (err instanceof AuthError) {
      return {
        ok: false,
        error: '❌ Auth Failed: Invalid API key. Check Vercel environment variables.',
        code: 'auth',
        status: err.status,
      };
    }

    if (err instanceof NotFoundError) {
      return {
        ok: false,
        error: '❌ Endpoint Not Found: Backend may not be deployed. Check Railway.',
        code: 'server',
        status: err.status,
      };
    }

    if (err instanceof ApiError) {
      // Try to extract backend error message
      const body = err.body as { message?: string; detail?: string } | undefined;
      const detail = body?.message || body?.detail || 'Unknown error';
      return {
        ok: false,
        error: `❌ Upload Failed: ${detail}`,
        code: 'server',
        status: err.status,
      };
    }

    // Network/CORS failure
    const message = err instanceof Error ? err.message : 'Connection failed';
    return {
      ok: false,
      error: `❌ Connection Failed: ${message}`,
      code: 'network',
    };
  }
}

/**
 * Get batch list from the intake API.
 *
 * @param page - Page number (1-indexed)
 * @param pageSize - Results per page (default 20)
 * @param status - Optional status filter
 */
export async function getBatches(
  page = 1,
  pageSize = 20,
  status?: string
): Promise<{ ok: true; data: unknown } | { ok: false; error: string }> {
  try {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    if (status) params.set('status', status);

    const data = await apiClient.get(`/api/v1/intake/batches?${params}`);
    return { ok: true, data };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to fetch batches';
    return { ok: false, error: message };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// BATCH STATUS POLLING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Batch status response from polling endpoint.
 * World-Class Ingestion: includes timing metrics, error budget, and rejection reason.
 */
export interface BatchStatusResult {
  batchId: string;
  filename: string;
  status: 'uploaded' | 'staging' | 'validating' | 'transforming' | 'inserting' | 'upserting' | 'completed' | 'failed';
  rowCountTotal: number;
  rowCountInserted: number;
  rowCountInvalid: number;
  rowCountValid: number;
  rowCountDuplicate: number;
  plaintiffsInserted: number;
  plaintiffsDuplicate: number;
  plaintiffsFailed: number;
  errorSummary: string | null;
  errors: BatchRowError[];
  // World-Class Observability
  parseDurationMs: number | null;
  dbDurationMs: number | null;
  errorThresholdPercent: number;
  rejectionReason: string | null;
}

export interface BatchRowError {
  rowIndex: number;
  errorCode: string;
  errorMessage: string;
  rawData: Record<string, unknown>;
}

export interface BatchStatusSuccess {
  ok: true;
  data: BatchStatusResult;
}

export interface BatchStatusError {
  ok: false;
  error: string;
  code: 'network' | 'auth' | 'not_found' | 'server';
}

export type BatchStatusResponse = BatchStatusSuccess | BatchStatusError;

/**
 * Get batch status by ID.
 *
 * Used for polling during processing. Returns current status and counts.
 *
 * @param batchId - UUID of the batch to check
 * @returns Normalized response with batch status
 *
 * @example
 *   // Poll every 2 seconds until complete or failed
 *   const result = await api.getBatchStatus(batchId);
 *   if (result.ok && result.data.status === 'completed') {
 *     showSuccess(`✅ ${result.data.rowCountInserted} rows inserted`);
 *   }
 */
export async function getBatchStatus(batchId: string): Promise<BatchStatusResponse> {
  try {
    interface StatusResponse {
      id: string;
      filename: string;
      status: string;
      row_count_total: number;
      row_count_inserted: number;
      row_count_invalid: number;
      row_count_valid: number;
      row_count_duplicate?: number;
      plaintiffs_inserted?: number;
      plaintiffs_duplicate?: number;
      plaintiffs_failed?: number;
      error_summary: string | null;
      // World-Class fields
      parse_duration_ms?: number | null;
      db_duration_ms?: number | null;
      error_threshold_percent?: number;
      rejection_reason?: string | null;
      errors?: Array<{
        row_index: number;
        error_code: string;
        error_message: string;
        raw_data: Record<string, unknown>;
      }>;
    }

    const data = await apiClient.get<StatusResponse>(`/api/v1/intake/batches/${batchId}`);

    return {
      ok: true,
      data: {
        batchId: data.id,
        filename: data.filename,
        status: data.status as BatchStatusResult['status'],
        rowCountTotal: data.row_count_total,
        rowCountInserted: data.row_count_inserted,
        rowCountInvalid: data.row_count_invalid,
        rowCountValid: data.row_count_valid,
        rowCountDuplicate: data.row_count_duplicate ?? 0,
        plaintiffsInserted: data.plaintiffs_inserted ?? 0,
        plaintiffsDuplicate: data.plaintiffs_duplicate ?? 0,
        plaintiffsFailed: data.plaintiffs_failed ?? 0,
        errorSummary: data.error_summary,
        // World-Class observability
        parseDurationMs: data.parse_duration_ms ?? null,
        dbDurationMs: data.db_duration_ms ?? null,
        errorThresholdPercent: data.error_threshold_percent ?? 10,
        rejectionReason: data.rejection_reason ?? null,
        errors: (data.errors ?? []).map((e) => ({
          rowIndex: e.row_index,
          errorCode: e.error_code,
          errorMessage: e.error_message,
          rawData: e.raw_data,
        })),
      },
    };
  } catch (err) {
    if (err instanceof AuthError) {
      return { ok: false, error: 'Authentication failed', code: 'auth' };
    }
    if (err instanceof NotFoundError) {
      return { ok: false, error: 'Batch not found', code: 'not_found' };
    }
    if (err instanceof ApiError) {
      return { ok: false, error: err.message, code: 'server' };
    }
    return { ok: false, error: 'Connection failed', code: 'network' };
  }
}

/**
 * Get intake system state (for status indicators).
 */
export async function getIntakeState(): Promise<{
  ok: true;
  data: unknown;
  degraded: boolean;
} | {
  ok: false;
  error: string;
}> {
  try {
    interface StateResponse {
      ok: boolean;
      degraded?: boolean;
      data: unknown;
    }
    const response = await apiClient.get<StateResponse>('/api/v1/intake/state');
    return {
      ok: true,
      data: response.data,
      degraded: response.degraded ?? false,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to fetch intake state';
    return { ok: false, error: message };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// UNIFIED API OBJECT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Unified API client for Dragonfly frontend.
 *
 * All methods return normalized responses with ok/error status.
 * No method throws - all errors are captured in the response.
 */
export const api = {
  checkBackendHealth,
  uploadBatch,
  getBatches,
  getBatchStatus,
  getIntakeState,
} as const;

// Re-export error types for type checking
export { AuthError, ApiError, NotFoundError } from './apiClient';
export type { HealthCheckResult, HealthErrorCategory } from './apiClient';

export default api;
