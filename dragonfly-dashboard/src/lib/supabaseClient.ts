import { createClient, type SupabaseClient, type PostgrestError } from '@supabase/supabase-js';

let cachedClient: SupabaseClient | null = null;

// Demo mode check - reads VITE_IS_DEMO env var
const rawDemo = String(import.meta.env.VITE_IS_DEMO ?? '').trim().toLowerCase();
export const IS_DEMO_MODE = ['true', '1', 'yes', 'on'].includes(rawDemo);

// Result type for demo-safe operations
export type DemoSafeResult<T> =
  | { kind: 'ok'; data: T; count?: number | null }
  | { kind: 'error'; error: PostgrestError | Error }
  | { kind: 'demo_locked' };

/**
 * Wraps a Supabase select query builder to handle demo mode and errors gracefully.
 */
export async function demoSafeSelect<T>(
  queryBuilder: PromiseLike<{ data: unknown; error: PostgrestError | null; count?: number | null }>,
): Promise<DemoSafeResult<T>> {
  if (IS_DEMO_MODE) {
    return { kind: 'demo_locked' };
  }
  try {
    const { data, error, count } = await queryBuilder;
    if (error) {
      return { kind: 'error', error };
    }
    return { kind: 'ok', data: data as T, count };
  } catch (err) {
    return { kind: 'error', error: err instanceof Error ? err : new Error('Unknown query error') };
  }
}

/**
 * Wraps a Supabase RPC call to handle demo mode and errors gracefully.
 */
export async function demoSafeRpc<T>(
  functionName: string,
  params?: Record<string, unknown>,
): Promise<DemoSafeResult<T>> {
  if (IS_DEMO_MODE) {
    return { kind: 'demo_locked' };
  }
  try {
    const client = getSupabaseClient();
    const { data, error } = await client.rpc(functionName, params);
    if (error) {
      return { kind: 'error', error };
    }
    return { kind: 'ok', data: data as T };
  } catch (err) {
    return { kind: 'error', error: err instanceof Error ? err : new Error('Unknown RPC error') };
  }
}

function buildClient(): SupabaseClient {
  // Sanitize env vars - remove hidden whitespace/newlines that break auth
  const rawUrl = import.meta.env.VITE_SUPABASE_URL;
  const rawAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

  const url = rawUrl?.trim().replace(/[\r\n\t]/g, '').replace(/\/+$/, '');
  const anonKey = rawAnonKey?.trim().replace(/[\r\n\t]/g, '');

  // Debug logging for Realtime auth troubleshooting
  console.log('[Dragonfly Supabase] URL:', url || '(missing)');
  console.log('[Dragonfly Supabase] Anon Key:', anonKey ? `***${anonKey.slice(-8)}` : '(missing)');

  if (!url || !anonKey) {
    const errorMsg = 'Supabase credentials are missing. Populate VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in Vercel.';
    console.error('[Dragonfly Supabase]', errorMsg);
    throw new Error(errorMsg);
  }

  // Validate anon key is not service role (common mistake)
  if (anonKey.includes('"role":"service_role"') || anonKey.includes('service_role')) {
    console.warn('[Dragonfly Supabase] WARNING: Key appears to be service_role! Use anon key for frontend.');
  }

  return createClient(url, anonKey);
}

export function getSupabaseClient(): SupabaseClient {
  if (!cachedClient) {
    cachedClient = buildClient();
  }
  return cachedClient;
}

export const supabaseClient = getSupabaseClient();
