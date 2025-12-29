/**
 * Runtime Configuration
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * SINGLE SOURCE OF TRUTH for all environment variables in the Vite frontend.
 *
 * ⚠️  WHAT YOU SET IS WHAT YOU GET — No _PROD suffixes, no magic overrides.
 *
 * Features:
 * - Trims all whitespace/newlines to prevent auth failures
 * - Validates required vars and throws clear errors (Fail Fast)
 * - Debug logging in dev mode only (never logs secrets in prod)
 *
 * Required Vercel Environment Variables:
 *   VITE_API_BASE_URL          - Railway backend URL (e.g., https://...railway.app)
 *   VITE_DRAGONFLY_API_KEY     - API key for X-DRAGONFLY-API-KEY header
 *   VITE_SUPABASE_URL          - Supabase project URL
 *   VITE_SUPABASE_ANON_KEY     - Supabase anon/public key (NOT service_role!)
 *
 * Optional:
 *   VITE_DEMO_MODE             - "true" to enable demo mode (locks mutations)
 */

// ═══════════════════════════════════════════════════════════════════════════
// ENVIRONMENT DETECTION
// ═══════════════════════════════════════════════════════════════════════════

/** True when running in production build (Vercel, etc.) */
export const isProd = import.meta.env.PROD;

/** True when running in development mode */
export const isDev = import.meta.env.DEV;

// ═══════════════════════════════════════════════════════════════════════════
// SANITIZATION HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Sanitize an environment variable value.
 * - Trims leading/trailing whitespace
 * - Removes newlines, carriage returns, tabs
 * - Returns undefined for empty/missing values
 */
function sanitize(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const cleaned = value.trim().replace(/[\r\n\t]/g, '');
  return cleaned || undefined;
}

/**
 * Sanitize a URL value.
 * - Same as sanitize() plus removes trailing slashes
 */
function sanitizeUrl(value: string | undefined): string | undefined {
  const cleaned = sanitize(value);
  if (!cleaned) return undefined;
  return cleaned.replace(/\/+$/, '');
}

/**
 * Get an env var directly. No _PROD overrides — what you set is what you get.
 */
function getEnv(key: string, isUrl = false): string | undefined {
  const value = (import.meta.env as Record<string, string | undefined>)[key];
  return isUrl ? sanitizeUrl(value) : sanitize(value);
}

/**
 * Get a required env var. Throws a clear error if missing.
 */
function requireEnv(key: string, isUrl = false): string {
  const value = getEnv(key, isUrl);
  if (!value) {
    const errorMsg = `[config/runtime] Missing required env var: ${key}. ` +
      `Set ${key} in Vercel Environment Variables.`;
    console.error(errorMsg);
    throw new Error(errorMsg);
  }
  return value;
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTED CONFIG VALUES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Railway backend API base URL.
 * Used for all /api/... requests.
 * Example: https://dragonflycivil-production-d57a.up.railway.app
 */
export const apiBaseUrl: string = requireEnv('VITE_API_BASE_URL', true);

/**
 * Dragonfly API key for X-DRAGONFLY-API-KEY header.
 * Required for all authenticated API requests.
 */
export const dragonflyApiKey: string = requireEnv('VITE_DRAGONFLY_API_KEY');

/**
 * Supabase project URL.
 * Example: https://iaketsyhmqbwaabgykux.supabase.co
 *
 * IMPORTANT: Must be the REST API URL (*.supabase.co), NOT the pooler host.
 */
export const supabaseUrl: string = (() => {
  const url = requireEnv('VITE_SUPABASE_URL', true);

  // Validate it's the correct Supabase URL format (not pooler)
  if (url.includes('pooler.supabase.com')) {
    const errorMsg =
      '[config/runtime] ERROR: VITE_SUPABASE_URL is a pooler URL. ' +
      'Use the REST API URL: https://<ref>.supabase.co (not pooler.supabase.com)';
    console.error(errorMsg);
    throw new Error(errorMsg);
  }

  // Validate it ends with supabase.co
  if (!url.includes('.supabase.co')) {
    console.warn(
      '[config/runtime] WARNING: VITE_SUPABASE_URL may be incorrect. ' +
      'Expected format: https://<ref>.supabase.co'
    );
  }

  return url;
})();

/**
 * Supabase anon/public key (safe for frontend).
 * NOT the service_role key!
 */
export const supabaseAnonKey: string = (() => {
  const key = requireEnv('VITE_SUPABASE_ANON_KEY');

  // Validate it's not accidentally the service role key
  if (key.includes('service_role')) {
    console.warn(
      '[config/runtime] WARNING: VITE_SUPABASE_ANON_KEY appears to be a service_role key! ' +
      'Use the anon/public key for frontend.'
    );
  }

  return key;
})();

/**
 * Demo mode flag.
 * When true, mutations are locked and demo data is shown.
 * Uses VITE_DEMO_MODE (VITE_IS_DEMO is deprecated).
 */
export const isDemoMode: boolean = (() => {
  // Prefer VITE_DEMO_MODE, fallback to VITE_IS_DEMO for backward compat
  const raw = getEnv('VITE_DEMO_MODE') ?? getEnv('VITE_IS_DEMO') ?? '';
  return ['true', '1', 'yes', 'on'].includes(raw.toLowerCase());
})();

// ═══════════════════════════════════════════════════════════════════════════
// DEBUG LOGGING (dev mode only)
// ═══════════════════════════════════════════════════════════════════════════

if (isDev) {
  console.log('[Dragonfly Config] Runtime configuration loaded:');
  console.log('  Mode:', isProd ? 'PRODUCTION' : 'DEVELOPMENT');
  console.log('  API Base URL:', apiBaseUrl);
  console.log('  API Key:', dragonflyApiKey ? `***${dragonflyApiKey.slice(-8)}` : '(missing)');
  console.log('  Supabase URL:', supabaseUrl);
  console.log('  Supabase Anon Key:', supabaseAnonKey ? `***${supabaseAnonKey.slice(-8)}` : '(missing)');
  console.log('  Demo Mode:', isDemoMode);
}

// Production logging - minimal, no secrets
if (isProd) {
  console.log('[Dragonfly] Config initialized. API:', apiBaseUrl);
}

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG OBJECT (for passing around or debugging)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Full runtime config object.
 * Useful for passing config to components or for debugging.
 */
export const runtimeConfig = {
  isProd,
  isDev,
  isDemoMode,
  apiBaseUrl,
  dragonflyApiKey,
  supabaseUrl,
  supabaseAnonKey,
} as const;

export type RuntimeConfig = typeof runtimeConfig;

export default runtimeConfig;
