/**
 * useUploadIntake - Hook for uploading CSV files to the Intake Fortress
 *
 * Handles file upload with progress tracking and error handling.
 * Designed for the Intake Station drag-and-drop zone.
 * 
 * Supports multiple data sources:
 * - simplicity: Standard Simplicity export format
 * - jbi: JBI export format
 * - foil: FOIL court data dumps (messy/varied column names)
 * - manual: Manual CSV uploads
 */
import { useCallback, useState } from 'react';
import { apiUpload } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type DataSource = 'simplicity' | 'jbi' | 'foil' | 'manual' | 'api';

export type UploadStatus = 'idle' | 'uploading' | 'processing' | 'success' | 'error';

export interface UploadResult {
  batchId: string;
  filename: string;
  totalRows: number;
  validRows: number;
  errorRows: number;
  status: string;
  message: string;
}

export interface UploadState {
  status: UploadStatus;
  progress: number; // 0-100
  error: string | null;
  errorCode: string | null; // Backend error code for conditional UI
  result: UploadResult | null;
}

export interface UseUploadIntakeOptions {
  /** Data source for the upload (determines parsing logic) */
  source?: DataSource;
}

export interface UseUploadIntakeResult {
  state: UploadState;
  uploadFile: (file: File, options?: UseUploadIntakeOptions) => Promise<UploadResult | null>;
  reset: () => void;
  /** Current selected data source */
  source: DataSource;
  /** Set the data source */
  setSource: (source: DataSource) => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// ERROR CODE MAPPING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Maps backend error codes to user-friendly messages.
 */
const ERROR_MESSAGES: Record<string, string> = {
  intake_upload_failed:
    'Something went wrong saving this file. Please try again or contact McCabe.',
  validation_error: 'Some rows are invalid. Check the error panel for details.',
};

/**
 * Get a friendly error message from a backend response.
 */
function getFriendlyErrorMessage(
  errorCode: string | undefined,
  message: string | undefined,
  status: number
): string {
  // Check for known error codes first
  if (errorCode && ERROR_MESSAGES[errorCode]) {
    return ERROR_MESSAGES[errorCode];
  }

  // Fallback to generic message with details
  const detail = message || errorCode || '';
  return detail
    ? `Upload failed: HTTP ${status} – ${detail}`
    : `Upload failed: HTTP ${status}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useUploadIntake(): UseUploadIntakeResult {
  const [state, setState] = useState<UploadState>({
    status: 'idle',
    progress: 0,
    error: null,
    errorCode: null,
    result: null,
  });

  const [source, setSource] = useState<DataSource>('simplicity');

  const reset = useCallback(() => {
    setState({
      status: 'idle',
      progress: 0,
      error: null,
      errorCode: null,
      result: null,
    });
  }, []);

  const uploadFile = useCallback(async (
    file: File,
    options?: UseUploadIntakeOptions
  ): Promise<UploadResult | null> => {
    // Use provided source or current state
    const uploadSource = options?.source ?? source;
    
    // Validate file type
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setState({
        status: 'error',
        progress: 0,
        error: 'Please upload a CSV file',
        errorCode: 'client_validation',
        result: null,
      });
      return null;
    }

    // Validate file size (max 50MB for normal, 500MB for FOIL)
    const MAX_SIZE = uploadSource === 'foil' ? 500 * 1024 * 1024 : 50 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      setState({
        status: 'error',
        progress: 0,
        error: 'File size exceeds 50MB limit',
        errorCode: 'client_validation',
        result: null,
      });
      return null;
    }

    setState({
      status: 'uploading',
      progress: 10,
      error: null,
      errorCode: null,
      result: null,
    });

    // Track error code for state update
    let capturedErrorCode: string | null = null;

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('source', uploadSource);

      // Simulate progress during upload
      const progressInterval = setInterval(() => {
        setState((prev) => ({
          ...prev,
          progress: Math.min(prev.progress + 10, 80),
        }));
      }, 200);

      // Use authenticated API client
      const response = await apiUpload('/api/v1/intake/upload', formData);

      clearInterval(progressInterval);

      if (!response.ok) {
        let errorCode: string | undefined;
        let errorMessage: string | undefined;
        try {
          const errorBody = await response.json();
          errorCode = errorBody.error;
          errorMessage = errorBody.message || errorBody.detail;
        } catch {
          // Ignore JSON parse errors
        }
        capturedErrorCode = errorCode || null;
        const friendlyMessage = getFriendlyErrorMessage(errorCode, errorMessage, response.status);
        throw new Error(friendlyMessage);
      }

      setState((prev) => ({
        ...prev,
        status: 'processing',
        progress: 90,
      }));

      const data = await response.json();

      const result: UploadResult = {
        batchId: data.batch_id ?? data.batchId ?? '',
        filename: data.filename ?? file.name,
        totalRows: data.total_rows ?? data.totalRows ?? 0,
        validRows: data.valid_rows ?? data.validRows ?? 0,
        errorRows: data.error_rows ?? data.errorRows ?? 0,
        status: data.status ?? 'completed',
        message: data.message ?? 'Upload successful',
      };

      setState({
        status: 'success',
        progress: 100,
        error: null,
        errorCode: null,
        result,
      });

      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Upload failed';
      setState({
        status: 'error',
        progress: 0,
        error: message,
        errorCode: capturedErrorCode,
        result: null,
      });
      return null;
    }
  }, [source]);

  return {
    state,
    uploadFile,
    reset,
    source,
    setSource,
  };
}

export default useUploadIntake;
