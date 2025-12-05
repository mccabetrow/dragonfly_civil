/**
 * API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Centralized API client for authenticated FastAPI requests.
 * All internal API calls should use this client to ensure consistent auth.
 */

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════════

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
export const API_KEY = import.meta.env.VITE_DRAGONFLY_API_KEY || '';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface ApiError {
  status: number;
  message: string;
  error?: string;
  isAuthError: boolean;
}

export interface ApiRequestOptions extends Omit<RequestInit, 'headers'> {
  /** Additional headers to merge with default auth headers */
  headers?: Record<string, string>;
  /** Skip Content-Type header (for FormData uploads) */
  skipContentType?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Build headers for API requests.
 * Includes X-API-KEY for authentication when available.
 * Does NOT throw if the key is missing – allows tests to run without secrets.
 */
export function getAuthHeaders(skipContentType = false): Record<string, string> {
  const headers: Record<string, string> = {};

  // Only include auth header if API key is configured
  if (API_KEY) {
    headers['X-API-KEY'] = API_KEY;
  }

  if (!skipContentType) {
    headers['Content-Type'] = 'application/json';
  }

  return headers;
}

/**
 * Parse error response from API.
 */
async function parseErrorResponse(response: Response): Promise<ApiError> {
  const isAuthError = response.status === 401 || response.status === 403;
  let message = `HTTP ${response.status}`;
  let error: string | undefined;

  try {
    const body = await response.json();
    error = body.error;
    message = body.detail || body.message || message;
  } catch {
    // Ignore JSON parse errors
  }

  return {
    status: response.status,
    message,
    error,
    isAuthError,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// API CLIENT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Make an authenticated API request.
 *
 * @param path - API path (e.g., '/api/v1/intake/upload')
 * @param options - Fetch options
 * @returns Response object
 * @throws ApiError on non-2xx responses
 */
export async function apiRequest(
  path: string,
  options: ApiRequestOptions = {}
): Promise<Response> {
  const { headers: extraHeaders = {}, skipContentType = false, ...fetchOptions } = options;

  // Merge headers: auth headers first, then caller headers, then force auth header
  // This ensures X-API-KEY cannot be overridden by caller
  const authHeaders = getAuthHeaders(skipContentType);
  const headers: Record<string, string> = {
    ...authHeaders,
    ...extraHeaders,
  };
  
  // Force auth header to prevent override (if API key is set)
  if (API_KEY) {
    headers['X-API-KEY'] = API_KEY;
  }

  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    ...fetchOptions,
    headers,
  });

  return response;
}

/**
 * Make an authenticated API request and parse JSON response.
 *
 * @param path - API path (e.g., '/api/v1/intake/batches')
 * @param options - Fetch options
 * @returns Parsed JSON response
 * @throws ApiError on non-2xx responses
 */
export async function apiJson<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const response = await apiRequest(path, options);

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return response.json() as Promise<T>;
}

/**
 * Upload a file via FormData with authentication.
 *
 * @param path - API path (e.g., '/api/v1/intake/upload')
 * @param formData - FormData containing the file and other fields
 * @returns Response object
 */
export async function apiUpload(path: string, formData: FormData): Promise<Response> {
  return apiRequest(path, {
    method: 'POST',
    body: formData,
    skipContentType: true, // Let browser set Content-Type with boundary
  });
}
