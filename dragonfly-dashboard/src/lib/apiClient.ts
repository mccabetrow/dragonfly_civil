/**
 * API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Unified, TypeScript-safe API client for all Dragonfly dashboard requests.
 * All data fetching flows through this client for consistent auth and error handling.
 *
 * Features:
 * - Automatic timeout with AbortController (default: 15s)
 * - X-Request-ID header for distributed tracing
 * - Supabase JWT auth integration
 * - Custom error types: AuthError, NotFoundError, RateLimitError, ServerError, NetworkError, ApiError
 * - Automatic login redirect on 401
 * - Captures X-Dragonfly-SHA from server responses for debugging
 *
 * Configuration is centralized in src/config/runtime.ts
 */

import { apiBaseUrl, dragonflyApiKey, supabaseUrl, supabaseAnonKey } from '../config';
import { createClient, SupabaseClient } from '@supabase/supabase-js';

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG (from centralized runtime config)
// ═══════════════════════════════════════════════════════════════════════════

const BASE_URL: string = apiBaseUrl;
const API_KEY: string = dragonflyApiKey;

/** Default request timeout in milliseconds */
export const DEFAULT_TIMEOUT_MS = 15_000;

// Export validated config for external use
export const API_BASE_URL: string = BASE_URL;

// ═══════════════════════════════════════════════════════════════════════════
// SUPABASE CLIENT (for JWT auth)
// ═══════════════════════════════════════════════════════════════════════════

/** Supabase client instance for auth token retrieval */
let _supabaseClient: SupabaseClient | null = null;

function getSupabaseClient(): SupabaseClient {
  if (!_supabaseClient) {
    _supabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
      },
    });
  }
  return _supabaseClient;
}

/**
 * Get the current Supabase JWT token for authenticated requests.
 * Returns null if user is not authenticated.
 */
async function getSupabaseJwt(): Promise<string | null> {
  try {
    const client = getSupabaseClient();
    const { data: { session } } = await client.auth.getSession();
    return session?.access_token ?? null;
  } catch (err) {
    console.warn('[API] Failed to get Supabase session:', err);
    return null;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// UUID GENERATION (for X-Request-ID)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Generate a UUID v4 for request tracing.
 * Uses crypto.randomUUID if available, falls back to manual generation.
 */
function generateRequestId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for older browsers
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// CUSTOM ERROR TYPES
// ═══════════════════════════════════════════════════════════════════════════

/** Base class for all API errors */
abstract class BaseApiError extends Error {
  abstract readonly status: number;
  abstract readonly path: string;
  readonly requestId?: string;

  constructor(message: string, requestId?: string) {
    super(message);
    this.requestId = requestId;
  }
}

/**
 * Thrown for 401/403 authentication or authorization failures.
 * Triggers automatic redirect to login page.
 */
export class AuthError extends BaseApiError {
  readonly status: number;
  readonly path: string;

  constructor(message: string, status: number, path: string, requestId?: string) {
    super(message, requestId);
    this.name = 'AuthError';
    this.status = status;
    this.path = path;
    Object.setPrototypeOf(this, AuthError.prototype);
  }
}

/**
 * Thrown for 404 not found responses.
 */
export class NotFoundError extends BaseApiError {
  readonly status: number;
  readonly path: string;

  constructor(message: string, status: number, path: string, requestId?: string) {
    super(message, requestId);
    this.name = 'NotFoundError';
    this.status = status;
    this.path = path;
    Object.setPrototypeOf(this, NotFoundError.prototype);
  }
}

/**
 * Thrown for 429 Too Many Requests (rate limiting).
 */
export class RateLimitError extends BaseApiError {
  readonly status: number = 429;
  readonly path: string;
  readonly retryAfter?: number;

  constructor(message: string, path: string, retryAfter?: number, requestId?: string) {
    super(message, requestId);
    this.name = 'RateLimitError';
    this.path = path;
    this.retryAfter = retryAfter;
    Object.setPrototypeOf(this, RateLimitError.prototype);
  }
}

/**
 * Thrown for 500+ server errors.
 * Includes the X-Dragonfly-SHA header value if available for debugging.
 */
export class ServerError extends BaseApiError {
  readonly status: number;
  readonly path: string;
  readonly serverSha?: string;
  readonly body?: unknown;

  constructor(
    message: string,
    status: number,
    path: string,
    serverSha?: string,
    body?: unknown,
    requestId?: string
  ) {
    super(message, requestId);
    this.name = 'ServerError';
    this.status = status;
    this.path = path;
    this.serverSha = serverSha;
    this.body = body;
    Object.setPrototypeOf(this, ServerError.prototype);
  }
}

/**
 * Thrown for network/connectivity failures (distinct from API errors).
 * Examples: DNS failure, CORS blocked, server unreachable.
 */
export class NetworkError extends BaseApiError {
  readonly status: number = 0;
  readonly path: string;
  readonly cause?: Error;

  constructor(message: string, path: string, cause?: Error, requestId?: string) {
    super(message, requestId);
    this.name = 'NetworkError';
    this.path = path;
    this.cause = cause;
    Object.setPrototypeOf(this, NetworkError.prototype);
  }
}

/**
 * Thrown for all other non-2xx API responses.
 */
export class ApiError extends BaseApiError {
  readonly status: number;
  readonly path: string;
  readonly body?: unknown;

  constructor(message: string, status: number, path: string, body?: unknown, requestId?: string) {
    super(message, requestId);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.body = body;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// INTERNAL HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Build a full API URL from path.
 *
 * Option A: BASE_URL is root domain (e.g., https://...railway.app)
 *           Paths should be /api/... or /health etc.
 *
 * Handles:
 * - Missing leading slash on path
 * - Empty BASE_URL (uses relative path for proxy setups)
 */
export function apiUrl(path: string): string {
  // Ensure path starts with /
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  // Concatenate base + path (no double slashes since we stripped trailing from base)
  return `${BASE_URL}${normalizedPath}`;
}

/** @internal Legacy alias for backward compatibility */
function buildUrl(path: string): string {
  return apiUrl(path);
}

/** Options for API requests */
export interface RequestOptions extends Omit<RequestInit, 'signal'> {
  /** Request timeout in milliseconds (default: 15000) */
  timeout?: number;
  /** Skip automatic Supabase JWT attachment */
  skipAuth?: boolean;
  /** Custom request ID (auto-generated if not provided) */
  requestId?: string;
}

/**
 * Get default headers for all API requests.
 * Includes X-Request-ID for distributed tracing.
 */
function getDefaultHeaders(requestId: string): Record<string, string> {
  return {
    'X-DRAGONFLY-API-KEY': API_KEY,
    'Accept': 'application/json',
    'X-Request-ID': requestId,
  };
}

/**
 * Attempt to parse JSON from response body.
 * Returns undefined if parsing fails.
 */
async function tryParseJson(response: Response): Promise<unknown | undefined> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/**
 * Redirect to login page on authentication failure.
 */
function redirectToLogin(): void {
  const currentPath = window.location.pathname + window.location.search;
  const loginUrl = `/login?redirect=${encodeURIComponent(currentPath)}`;
  console.warn('[API] Redirecting to login:', loginUrl);
  window.location.href = loginUrl;
}

/**
 * Handle non-2xx responses by throwing appropriate error types.
 */
async function handleErrorResponse(
  response: Response,
  path: string,
  requestId: string
): Promise<never> {
  const parsed = await tryParseJson(response);
  const status = response.status;

  // 401/403 - Auth error with redirect
  if (status === 401 || status === 403) {
    console.error('[API AuthError]', {
      path,
      status,
      requestId,
      baseUrl: BASE_URL,
      message: (parsed as { detail?: unknown })?.detail ?? parsed,
    });

    // Schedule redirect after throwing (allows caller to catch if needed)
    setTimeout(() => redirectToLogin(), 100);
    throw new AuthError('Invalid or missing credentials', status, path, requestId);
  }

  // 404 - Not Found
  if (status === 404) {
    throw new NotFoundError('Resource or view not found', status, path, requestId);
  }

  // 429 - Rate Limited
  if (status === 429) {
    const retryAfter = response.headers.get('Retry-After');
    const retrySeconds = retryAfter ? parseInt(retryAfter, 10) : undefined;
    throw new RateLimitError(
      'Rate limit exceeded. Please slow down.',
      path,
      retrySeconds,
      requestId
    );
  }

  // 500+ - Server Error (capture X-Dragonfly-SHA for debugging)
  if (status >= 500) {
    const serverSha = response.headers.get('X-Dragonfly-SHA') ?? undefined;
    console.error('[API ServerError]', {
      path,
      status,
      requestId,
      serverSha,
      body: parsed,
    });
    throw new ServerError(
      `Server error: HTTP ${status}`,
      status,
      path,
      serverSha,
      parsed,
      requestId
    );
  }

  // All other errors
  throw new ApiError('API request failed', status, path, parsed, requestId);
}

/**
 * Core fetch wrapper with timeout, auth, tracing, and error handling.
 */
async function doFetch<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const url = buildUrl(path);
  const { timeout = DEFAULT_TIMEOUT_MS, skipAuth = false, requestId: customRequestId, ...fetchOptions } = options;

  // Generate or use provided request ID
  const requestId = customRequestId ?? generateRequestId();

  // Set up timeout with AbortController
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // Build headers
  const headers: Record<string, string> = {
    ...getDefaultHeaders(requestId),
    ...(fetchOptions.headers as Record<string, string> || {}),
  };

  // Attach Supabase JWT if available and not skipped
  if (!skipAuth) {
    const jwt = await getSupabaseJwt();
    if (jwt) {
      headers['Authorization'] = `Bearer ${jwt}`;
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...fetchOptions,
      headers,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);

    // Check if it was a timeout
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new NetworkError(
        `Request timed out after ${timeout}ms`,
        path,
        undefined,
        requestId
      );
    }

    // Network/connectivity failure
    const cause = err instanceof Error ? err : undefined;
    throw new NetworkError(
      'Network error – check connection or API status.',
      path,
      cause,
      requestId
    );
  }

  clearTimeout(timeoutId);

  if (!response.ok) {
    await handleErrorResponse(response, path, requestId);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

// ═══════════════════════════════════════════════════════════════════════════
// PUBLIC API CLIENT
// ═══════════════════════════════════════════════════════════════════════════

export type HealthErrorCategory =
  | 'none'
  | 'cors'
  | 'auth'
  | 'timeout'
  | 'network'
  | 'server'
  | 'unknown';

export interface HealthCheckResult {
  ok: boolean;
  status: number;
  environment?: string;
  /** Detailed error message when ok=false */
  error?: string;
  /** Endpoint that responded (/api/health or /health) */
  endpoint: string;
  /** High-level error category for UI messaging */
  category: HealthErrorCategory;
  /** Unix timestamp (ms) when the check completed */
  checkedAt: number;
}

/**
 * Unified API client for all Dragonfly dashboard requests.
 *
 * All methods:
 * - Build URLs correctly from path + BASE_URL
 * - Include X-DRAGONFLY-API-KEY and Accept headers
 * - Map status codes to typed errors (AuthError, NotFoundError, ApiError)
 * - Wrap network failures in a clear Error message
 */
const HEALTH_ENDPOINTS = ['/api/health', '/health'];
const HEALTH_TIMEOUT_MS = 7000;

function categorizeStatus(status: number): HealthErrorCategory {
  if (status === 401 || status === 403) {
    return 'auth';
  }
  if (status >= 500) {
    return 'server';
  }
  if (status === 0) {
    return 'network';
  }
  return 'unknown';
}

function categorizeError(error: unknown): HealthErrorCategory {
  if (typeof DOMException !== 'undefined' && error instanceof DOMException && error.name === 'AbortError') {
    return 'timeout';
  }
  if (error instanceof TypeError) {
    // Browser fetch throws TypeError on CORS / network failures
    return 'cors';
  }
  const message = error instanceof Error ? error.message.toLowerCase() : '';
  if (message.includes('cors')) {
    return 'cors';
  }
  if (message.includes('timeout')) {
    return 'timeout';
  }
  if (message.includes('network')) {
    return 'network';
  }
  return 'unknown';
}

export const apiClient = {
  /**
   * GET request returning typed JSON.
   * @param path - API path (e.g., '/api/judgments')
   * @param options - Request options including timeout, auth, and requestId
   */
  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    return doFetch<T>(path, {
      method: 'GET',
      ...options,
    });
  },

  /**
   * POST request with JSON body returning typed JSON.
   * @param path - API path (e.g., '/api/judgments')
   * @param body - Request body (will be JSON stringified)
   * @param options - Request options including timeout, auth, and requestId
   */
  async post<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return doFetch<T>(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: JSON.stringify(body),
      ...options,
    });
  },

  /**
   * PUT request with JSON body returning typed JSON.
   * @param path - API path (e.g., '/api/judgments/123')
   * @param body - Request body (will be JSON stringified)
   * @param options - Request options including timeout, auth, and requestId
   */
  async put<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return doFetch<T>(path, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: JSON.stringify(body),
      ...options,
    });
  },

  /**
   * PATCH request with JSON body returning typed JSON.
   * @param path - API path (e.g., '/api/judgments/123')
   * @param body - Partial update body (will be JSON stringified)
   * @param options - Request options including timeout, auth, and requestId
   */
  async patch<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return doFetch<T>(path, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: JSON.stringify(body),
      ...options,
    });
  },

  /**
   * DELETE request returning typed JSON.
   * @param path - API path (e.g., '/api/judgments/123')
   * @param options - Request options including timeout, auth, and requestId
   */
  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return doFetch<T>(path, {
      method: 'DELETE',
      ...options,
    });
  },

  /**
   * Upload a file via FormData.
   * Appends file under key "file" plus any extra fields.
   * @param path - API path (e.g., '/api/upload')
   * @param file - File to upload
   * @param extraFields - Additional form fields to include
   * @param options - Request options including timeout and requestId
   */
  async upload<T>(
    path: string,
    file: File,
    extraFields?: Record<string, string>,
    options?: RequestOptions
  ): Promise<T> {
    const { timeout = DEFAULT_TIMEOUT_MS, requestId: customRequestId, skipAuth = false } = options ?? {};
    const requestId = customRequestId ?? generateRequestId();

    const formData = new FormData();
    formData.append('file', file);

    if (extraFields) {
      for (const [key, value] of Object.entries(extraFields)) {
        formData.append(key, value);
      }
    }

    const url = buildUrl(path);

    // Set up timeout with AbortController
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    // Build headers
    const headers: Record<string, string> = {
      'X-DRAGONFLY-API-KEY': API_KEY,
      'Accept': 'application/json',
      'X-Request-ID': requestId,
      // No Content-Type – browser sets multipart/form-data with boundary
    };

    // Attach Supabase JWT if available
    if (!skipAuth) {
      const jwt = await getSupabaseJwt();
      if (jwt) {
        headers['Authorization'] = `Bearer ${jwt}`;
      }
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers,
        body: formData,
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timeoutId);

      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new NetworkError(`Upload timed out after ${timeout}ms`, path, undefined, requestId);
      }

      const cause = err instanceof Error ? err : undefined;
      throw new NetworkError('Upload failed – check connection.', path, cause, requestId);
    }

    clearTimeout(timeoutId);

    if (!response.ok) {
      await handleErrorResponse(response, path, requestId);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  },

  /**
   * Health check endpoint.
   * Returns normalized result; never throws.
   *
   * ROBUST LOGIC:
   * - Try /api/health first
   * - Fallback to /health (some setups use root path)
   * - ANY HTTP 200 = healthy (regardless of JSON body)
   */
  async checkHealth(): Promise<HealthCheckResult> {
    let lastResult: HealthCheckResult | null = null;
    const requestId = generateRequestId();

    for (const endpoint of HEALTH_ENDPOINTS) {
      const url = apiUrl(endpoint);
      console.log(`[Dragonfly] Health check: ${url}`);

      const controller = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
      const timeoutId = controller ? setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS) : undefined;

      try {
        const response = await fetch(url, {
          method: 'GET',
          headers: getDefaultHeaders(requestId),
          mode: 'cors',
          credentials: 'omit',
          signal: controller?.signal,
        });

        if (timeoutId) {
          clearTimeout(timeoutId);
        }

        if (response.ok) {
          let environment: string | undefined;
          try {
            const data = await response.json();
            if (data && typeof data === 'object') {
              environment = (data as { environment?: string }).environment;
            }
          } catch (parseErr) {
            console.warn('[Dragonfly] Health response JSON parse failed (tolerated):', parseErr);
          }

          console.log(`[Dragonfly] Health OK from ${endpoint}`);
          return {
            ok: true,
            status: response.status,
            environment,
            error: undefined,
            endpoint,
            category: 'none',
            checkedAt: Date.now(),
          };
        }

        const category = categorizeStatus(response.status);
        const description =
          category === 'auth'
            ? 'API key missing or rejected (401/403).'
            : `Health endpoint responded with HTTP ${response.status}.`;

        console.warn(`[Dragonfly] ${endpoint} returned ${response.status}`);

        const result: HealthCheckResult = {
          ok: false,
          status: response.status,
          environment: undefined,
          error: description,
          endpoint,
          category,
          checkedAt: Date.now(),
        };

        lastResult = result;

        // Auth failures won't be resolved by trying alternate endpoints
        if (category === 'auth') {
          return result;
        }
      } catch (err) {
        if (timeoutId) {
          clearTimeout(timeoutId);
        }

        const category = categorizeError(err);
        const message = err instanceof Error ? err.message : 'Health request failed.';
        console.warn(`[Dragonfly] ${endpoint} failed:`, message);

        lastResult = {
          ok: false,
          status: 0,
          environment: undefined,
          error: message,
          endpoint,
          category,
          checkedAt: Date.now(),
        };
      }
    }

    return (
      lastResult ?? {
        ok: false,
        status: 0,
        environment: undefined,
        error: 'All health endpoints unreachable – check Railway deployment.',
        endpoint: HEALTH_ENDPOINTS[0],
        category: 'unknown',
        checkedAt: Date.now(),
      }
    );
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// LEGACY EXPORTS (for backward compatibility during migration)
// ═══════════════════════════════════════════════════════════════════════════

/** @deprecated Use apiClient.get/post/upload instead */
export async function apiRequest(
  path: string,
  options: RequestInit & { skipContentType?: boolean } = {}
): Promise<Response> {
  const url = buildUrl(path);
  const { skipContentType, ...fetchOptions } = options;

  const headers: Record<string, string> = {
    'X-DRAGONFLY-API-KEY': API_KEY,
    'Accept': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (!skipContentType && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  return fetch(url, {
    ...fetchOptions,
    headers,
  });
}

/** @deprecated Use apiClient.get instead */
export async function apiJson<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  return apiClient.get<T>(path, options);
}

/** @deprecated Use apiClient.upload instead */
export async function apiUpload(path: string, formData: FormData): Promise<Response> {
  const url = buildUrl(path);
  return fetch(url, {
    method: 'POST',
    headers: {
      'X-DRAGONFLY-API-KEY': API_KEY,
      'Accept': 'application/json',
    },
    body: formData,
  });
}

/** @deprecated Use getDefaultHeaders pattern internally */
export function getAuthHeaders(skipContentType = false): Record<string, string> {
  const headers: Record<string, string> = {
    'X-DRAGONFLY-API-KEY': API_KEY,
  };
  if (!skipContentType) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

// ═══════════════════════════════════════════════════════════════════════════
// DRAGONFLY API CLASS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * DragonflyAPI - Class-based wrapper for the Dragonfly API client.
 *
 * Features:
 * - BASE_URL from VITE_API_BASE_URL (fails fast if missing)
 * - Default 15s timeout with AbortController
 * - Automatic Supabase JWT auth attachment
 * - X-Request-ID header for distributed tracing
 * - Custom error classes: AuthError, NotFoundError, RateLimitError, ServerError, NetworkError
 * - Automatic login redirect on 401
 * - Captures X-Dragonfly-SHA from server errors for debugging
 *
 * Usage:
 * ```typescript
 * import { DragonflyAPI, ServerError } from '@/lib/apiClient';
 *
 * const api = new DragonflyAPI();
 *
 * try {
 *   const data = await api.get<MyType>('/api/data');
 * } catch (err) {
 *   if (err instanceof ServerError) {
 *     console.error(`Server error (SHA: ${err.serverSha}):`, err.message);
 *   }
 * }
 * ```
 */
export class DragonflyAPI {
  private readonly defaultTimeout: number;

  constructor(options?: { timeout?: number }) {
    this.defaultTimeout = options?.timeout ?? DEFAULT_TIMEOUT_MS;
  }

  /**
   * GET request returning typed JSON.
   */
  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    return apiClient.get<T>(path, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * POST request with JSON body returning typed JSON.
   */
  async post<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return apiClient.post<T>(path, body, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * PUT request with JSON body returning typed JSON.
   */
  async put<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return apiClient.put<T>(path, body, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * PATCH request with partial update body returning typed JSON.
   */
  async patch<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    return apiClient.patch<T>(path, body, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * DELETE request returning typed JSON.
   */
  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return apiClient.delete<T>(path, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * Upload a file via FormData.
   */
  async upload<T>(
    path: string,
    file: File,
    extraFields?: Record<string, string>,
    options?: RequestOptions
  ): Promise<T> {
    return apiClient.upload<T>(path, file, extraFields, {
      timeout: this.defaultTimeout,
      ...options,
    });
  }

  /**
   * Health check endpoint.
   * Returns normalized result; never throws.
   */
  async checkHealth(): Promise<HealthCheckResult> {
    return apiClient.checkHealth();
  }

  /** Base URL for the API */
  get baseUrl(): string {
    return API_BASE_URL;
  }
}

// Default singleton instance
export const dragonflyApi = new DragonflyAPI();
