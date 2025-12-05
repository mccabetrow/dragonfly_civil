/**
 * Tests for Intake Upload Hook and Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the useUploadIntake hook and IntakeStation component.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { useUploadIntake } from '../src/hooks/useUploadIntake';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

// Mock the API client module
vi.mock('../src/lib/apiClient', () => ({
  apiUpload: vi.fn(),
  API_KEY: 'test-api-key',
  API_BASE_URL: '',
}));

import { apiUpload } from '../src/lib/apiClient';

const mockApiUpload = vi.mocked(apiUpload);

// Helper to create a mock File
function createMockFile(name: string, size: number = 1024): File {
  const content = new Array(size).fill('a').join('');
  return new File([content], name, { type: 'text/csv' });
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('useUploadIntake', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  it('starts in idle state', () => {
    const { result } = renderHook(() => useUploadIntake());

    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.progress).toBe(0);
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.result).toBeNull();
  });

  it('rejects non-CSV files', async () => {
    const { result } = renderHook(() => useUploadIntake());
    const txtFile = new File(['test'], 'test.txt', { type: 'text/plain' });

    await act(async () => {
      await result.current.uploadFile(txtFile);
    });

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('Please upload a CSV file');
  });

  it('calls apiUpload with correct path and FormData', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        batch_id: 'batch-123',
        filename: 'test.csv',
        total_rows: 10,
        valid_rows: 8,
        error_rows: 2,
        status: 'completed',
        message: 'Upload successful',
      }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    // Start upload
    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    // Advance timers to allow progress updates
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await uploadPromise;

    // Check apiUpload was called correctly
    expect(mockApiUpload).toHaveBeenCalledTimes(1);
    const [path, formData] = mockApiUpload.mock.calls[0];

    expect(path).toBe('/api/v1/intake/upload');
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get('file')).toBeTruthy();
    expect(formData.get('source')).toBe('simplicity');
  });

  it('uses authenticated API client (apiUpload includes X-API-KEY header)', async () => {
    // This test documents that useUploadIntake uses the apiUpload helper
    // which is configured to include the X-API-KEY header automatically.
    // The auth is verified by checking that apiUpload (not raw fetch) is called.
    mockApiUpload.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        batch_id: 'batch-auth',
        filename: 'auth-test.csv',
        total_rows: 1,
        valid_rows: 1,
        error_rows: 0,
        status: 'completed',
        message: 'Auth test',
      }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('auth-test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    // Verify apiUpload was used (not raw fetch)
    // apiUpload automatically adds X-API-KEY header from lib/apiClient
    expect(mockApiUpload).toHaveBeenCalled();
    expect(result.current.state.status).toBe('success');
  });

  it('sets success state on 200/201 response', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        batch_id: 'batch-456',
        filename: 'data.csv',
        total_rows: 100,
        valid_rows: 95,
        error_rows: 5,
        status: 'completed',
        message: 'Batch processed',
      }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('data.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    const uploadResult = await uploadPromise;

    expect(result.current.state.status).toBe('success');
    expect(result.current.state.progress).toBe(100);
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.result).toEqual({
      batchId: 'batch-456',
      filename: 'data.csv',
      totalRows: 100,
      validRows: 95,
      errorRows: 5,
      status: 'completed',
      message: 'Batch processed',
    });
  });

  it('sets error state on 404 response', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Not Found' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('Upload failed: HTTP 404 – Not Found');
  });

  it('sets error state on 500 response with intake_upload_failed code', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: 'intake_upload_failed', message: 'Database connection failed' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe(
      'Something went wrong saving this file. Please try again or contact McCabe.'
    );
    expect(result.current.state.errorCode).toBe('intake_upload_failed');
  });

  it('sets error state on 422 response with validation_error code', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ error: 'validation_error', message: 'Missing required fields' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe(
      'Some rows are invalid. Check the error panel for details.'
    );
    expect(result.current.state.errorCode).toBe('validation_error');
  });

  it('sets fallback error message for unknown error codes', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: 'some_unknown_error', message: 'Something unexpected' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('Upload failed: HTTP 500 – Something unexpected');
    expect(result.current.state.errorCode).toBe('some_unknown_error');
  });

  it('handles error response without JSON body', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('Not JSON');
      },
    } as unknown as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('Upload failed: HTTP 502');
    expect(result.current.state.errorCode).toBeNull();
  });

  it('sets generic HTTP 500 fallback when no error code provided', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ message: 'Internal Server Error' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('Upload failed: HTTP 500 – Internal Server Error');
    expect(result.current.state.errorCode).toBeNull();
  });

  it('reset clears state back to idle', async () => {
    mockApiUpload.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ error: 'Bad Request' }),
    } as Response);

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    // Create an error state
    const uploadPromise = act(async () => {
      return result.current.uploadFile(csvFile);
    });

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    await uploadPromise;

    expect(result.current.state.status).toBe('error');

    // Reset
    act(() => {
      result.current.reset();
    });

    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.progress).toBe(0);
  });

  it('shows uploading state while request is in progress', async () => {
    // Never resolve the apiUpload to keep in uploading state
    mockApiUpload.mockImplementationOnce(() => new Promise(() => {}));

    const { result } = renderHook(() => useUploadIntake());
    const csvFile = createMockFile('test.csv');

    // Start upload but don't await
    act(() => {
      result.current.uploadFile(csvFile);
    });

    // Should be uploading immediately
    expect(result.current.state.status).toBe('uploading');

    // Progress should increase over time
    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    expect(result.current.state.progress).toBeGreaterThan(10);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// INTEGRATION NOTES
// ═══════════════════════════════════════════════════════════════════════════
// For full IntakeStation component tests, you would need to:
// 1. Mock the useUploadIntake hook
// 2. Render the IntakeStation component
// 3. Simulate drag-and-drop or file input changes
// 4. Assert UI updates (spinner, error messages, success state)
//
// These tests focus on the hook behavior which is the critical upload logic.
