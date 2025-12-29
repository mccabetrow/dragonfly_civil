import { createClient, type SupabaseClient, type PostgrestError } from '@supabase/supabase-js';
import { supabaseUrl, supabaseAnonKey, isDemoMode } from '../config';

let cachedClient: SupabaseClient | null = null;

// Demo mode - from centralized config
export const IS_DEMO_MODE = isDemoMode;

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
  // Config is already validated and sanitized in @/config/runtime
  return createClient(supabaseUrl, supabaseAnonKey);
}

export function getSupabaseClient(): SupabaseClient {
  if (!cachedClient) {
    cachedClient = buildClient();
  }
  return cachedClient;
}

export const supabaseClient = getSupabaseClient();
