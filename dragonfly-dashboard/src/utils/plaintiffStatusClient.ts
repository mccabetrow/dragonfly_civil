import type { SupabaseClient } from '@supabase/supabase-js';

export type PlaintiffStatus = 'new' | 'contacted' | 'qualified' | 'sent_agreement' | 'signed' | 'lost';

export async function setPlaintiffStatus(
  supabase: SupabaseClient,
  plaintiffId: string,
  newStatus: PlaintiffStatus,
  note?: string,
): Promise<void> {
  if (!plaintiffId) {
    throw new Error('Plaintiff id is required to update status.');
  }

  const { error } = await supabase.rpc('set_plaintiff_status', {
    _plaintiff_id: plaintiffId,
    _new_status: newStatus,
    _note: note ?? null,
    _changed_by: 'dashboard',
  });

  if (error) {
    const message = error.message || 'Failed to update plaintiff status.';
    throw new Error(message);
  }
}
