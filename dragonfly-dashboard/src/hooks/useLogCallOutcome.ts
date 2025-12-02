import { useCallback, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { supabaseClient } from '../lib/supabaseClient';

export interface LogCallOutcomePayload {
  plaintiffId: string;
  outcome: string;
  interestLevel?: string | null;
  notes?: string | null;
  nextFollowUpAt?: string | null;
  assignee?: string | null;
}

export interface LogCallOutcomeResult {
  logCallOutcome: (payload: LogCallOutcomePayload) => Promise<string>;
  isLogging: boolean;
  error: string | null;
  resetError: () => void;
}

export function useLogCallOutcome(): LogCallOutcomeResult {
  const [isLogging, setIsLogging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const logCallOutcome = useCallback(async (payload: LogCallOutcomePayload) => {
    const followUpIso = normalizeDateTime(payload.nextFollowUpAt);
    const sanitizedNotes = sanitize(payload.notes);
    const sanitizedAssignee = sanitize(payload.assignee);
    const sanitizedInterest = sanitize(payload.interestLevel);
    const sanitizedOutcome = sanitize(payload.outcome);

    if (!payload.plaintiffId) {
      throw new Error('A valid plaintiff is required to log a call outcome.');
    }
    if (!sanitizedOutcome) {
      throw new Error('Select an outcome before logging the call.');
    }

    setIsLogging(true);
    setError(null);

    const { data, error } = await supabaseClient.rpc('log_call_outcome', {
      p_plaintiff_id: payload.plaintiffId,
      p_outcome: sanitizedOutcome,
      p_interest_level: sanitizedInterest,
      p_notes: sanitizedNotes,
      p_next_follow_up_at: followUpIso,
      p_assignee: sanitizedAssignee,
    });

    if (error) {
      const friendly = deriveFriendlyMessage(error);
      setError(friendly);
      setIsLogging(false);
      throw new Error(friendly);
    }

    setIsLogging(false);
    setError(null);
    return (data as string) ?? '';
  }, []);

  const resetError = useCallback(() => setError(null), []);

  return { logCallOutcome, isLogging, error, resetError };
}

function sanitize(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeDateTime(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

function deriveFriendlyMessage(error: PostgrestError): string {
  if (error.message) {
    return error.message;
  }
  if (error.details) {
    return error.details;
  }
  return 'Failed to log call outcome.';
}
