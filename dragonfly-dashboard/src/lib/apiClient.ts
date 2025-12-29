/**
 * API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Unified, TypeScript-safe API client for all Dragonfly dashboard requests.
 * All data fetching flows through this client for consistent auth and error handling.
 *
 * Configuration is centralized in src/config/runtime.ts
 */

import { apiBaseUrl, dragonflyApiKey } from '../config';

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG (from centralized runtime config)
// ═══════════════════════════════════════════════════════════════════════════

const BASE_URL: string = apiBaseUrl;
const API_KEY: string = dragonflyApiKey;

// Export validated config for external use
export const API_BASE_URL: string = BASE_URL;

// ═══════════════════════════════════════════════════════════════════════════
// CUSTOM ERROR TYPES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Thrown for 401/403 authentication or authorization failures.
 */
export class AuthError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(message: string, status: number, path: string) {
    super(message);
    this.name = 'AuthError';
    this.status = status;
    this.path = path;
    Object.setPrototypeOf(this, AuthError.prototype);
  }
}

/**
 * Thrown for 404 not found responses.
 */
export class NotFoundError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(message: string, status: number, path: string) {
    super(message);
    this.name = 'NotFoundError';
    this.status = status;
    this.path = path;
    Object.setPrototypeOf(this, NotFoundError.prototype);
  }
}

/**
 * Thrown for all other non-2xx API responses.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly body?: unknown;

  constructor(message: string, status: number, path: string, body?: unknown) {
    super(message);
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

/**
 * Get default headers for all API requests.
 */
function getDefaultHeaders(): Record<string, string> {
  return {
    'X-DRAGONFLY-API-KEY': API_KEY,
    'Accept': 'application/json',
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
 * Handle non-2xx responses by throwing appropriate error types.
 */
async function handleErrorResponse(response: Response, path: string): Promise<never> {
  const parsed = await tryParseJson(response);
  const status = response.status;

  if (status === 401 || status === 403) {
    console.error('[API AuthError]', {
      path,
      status,
      baseUrl: BASE_URL,
      message: (parsed as { detail?: unknown })?.detail ?? parsed,
    });
    throw new AuthError('Invalid or missing API key', status, path);
  }

  if (status === 404) {
    throw new NotFoundError('Resource or view not found', status, path);
  }

  throw new ApiError('API request failed', status, path, parsed);
}

/**
 * Core fetch wrapper with error handling.
 */
async function doFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = buildUrl(path);

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        ...getDefaultHeaders(),
        ...options.headers,
      },
    });
  } catch (err) {
    // Network/connectivity failure
    throw new Error('Connection failed – check API base URL / Railway status.');
  }

  if (!response.ok) {
    await handleErrorResponse(response, path);
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

export interface HealthCheckResult {
  ok: boolean;
  status: number;
  environment?: string;
  /** Detailed error message when ok=false */
  error?: string;
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
export const apiClient = {
  /**
   * GET request returning typed JSON.
   */
  async get<T>(path: string, options?: RequestInit): Promise<T> {
    return doFetch<T>(path, {
      method: 'GET',
      ...options,
    });
  },

  /**
   * POST request with JSON body returning typed JSON.
   */
  async post<T>(path: string, body: unknown, options?: RequestInit): Promise<T> {
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
   * Upload a file via FormData.
   * Appends file under key "file" plus any extra fields.
   */
  async upload<T>(
    path: string,
    file: File,
    extraFields?: Record<string, string>
  ): Promise<T> {
    const formData = new FormData();
    formData.append('file', file);

    if (extraFields) {
      for (const [key, value] of Object.entries(extraFields)) {
        formData.append(key, value);
      }
    }

    const url = buildUrl(path);

    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-DRAGONFLY-API-KEY': API_KEY,
          'Accept': 'application/json',
          // No Content-Type – browser sets multipart/form-data with boundary
        },
        body: formData,
      });
    } catch {
      throw new Error('Connection failed – check API base URL / Railway status.');
    }

    if (!response.ok) {
      await handleErrorResponse(response, path);
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
    const endpoints = ['/api/health', '/health'];

    for (const endpoint of endpoints) {
      try {
        const url = apiUrl(endpoint);
        console.log(`[Dragonfly] Health check: ${url}`);

        const response = await fetch(url, {
          method: 'GET',
          headers: getDefaultHeaders(),
        });

        // ANY 200-level response = healthy
        if (response.ok) {
          // Try to parse JSON for extra info, but don't require it
          let environment: string | undefined;
          try {
            const data = await response.json();
            environment = data?.environment;
          } catch {
            // Response wasn't JSON - that's fine, still healthy
          }

          console.log(`[Dragonfly] Health OK from ${endpoint}`);
          return {
            ok: true,
            status: response.status,
            environment,
            error: undefined,
          };
        }

        // Non-2xx - try next endpoint
        console.warn(`[Dragonfly] ${endpoint} returned ${response.status}, trying next...`);
      } catch (err) {
        // Network error - try next endpoint
        console.warn(`[Dragonfly] ${endpoint} failed:`, err);
      }
    }

    // All endpoints failed
    console.error('[Dragonfly] All health endpoints failed');
    return {
      ok: false,
      status: 0,
      environment: undefined,
      error: 'All health endpoints unreachable – check Railway deployment.',
    };
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
