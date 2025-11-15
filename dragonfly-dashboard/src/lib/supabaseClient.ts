import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let cachedClient: SupabaseClient | null = null;

function buildClient(): SupabaseClient {
  const url = import.meta.env.VITE_SUPABASE_URL;
  const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      'Supabase credentials are missing. Populate VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in your environment.',
    );
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
