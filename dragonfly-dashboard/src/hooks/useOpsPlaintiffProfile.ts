import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient, type DemoSafeResult } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { buildDashboardError } from '../utils/dashboardErrors';

const OPS_PROFILE_LOCK_MESSAGE =
  'Plaintiff-level history stays hidden in the demo tenant. Connect to production Supabase to view contact logs.';
const CALL_ATTEMPT_LIMIT = 50;
const STATUS_HISTORY_LIMIT = 50;
const ENFORCEMENT_HISTORY_LIMIT = 50;
const JUDGMENT_LIMIT = 40;
const CONTACT_LIMIT = 25;

export interface OpsPlaintiffSummary {
  id: string;
  name: string;
  firmName: string | null;
  phone: string | null;
  email: string | null;
  tier: string | null;
  statusLabel: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface OpsCallAttempt {
  id: string;
  outcome: string;
  interest: string | null;
  notes: string | null;
  followUpAt: string | null;
  attemptedAt: string | null;
}

export type OpsTimelineEventType = 'call' | 'status' | 'enforcement';

export interface OpsTimelineEvent {
  id: string;
  type: OpsTimelineEventType;
  title: string;
  description: string | null;
  occurredAt: string | null;
}

export interface OpsPlaintiffJudgment {
  judgmentId: string;
  caseNumber: string | null;
  enforcementStage: string | null;
  enforcementStageLabel: string;
  enforcementStageUpdatedAt: string | null;
  collectabilityTier: string | null;
}

export interface OpsPlaintiffProfile {
  summary: OpsPlaintiffSummary;
  contacts: OpsContact[];
  callAttempts: OpsCallAttempt[];
  timeline: OpsTimelineEvent[];
  judgments: OpsPlaintiffJudgment[];
}

export interface OpsContact {
  id: string;
  name: string;
  role: string | null;
  email: string | null;
  phone: string | null;
}

interface RawPlaintiffRow {
  id: string;
  name: string | null;
  firm_name: string | null;
  phone: string | null;
  email: string | null;
  tier: string | null;
  status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface RawCallAttemptRow {
  id: string | null;
  outcome: string | null;
  interest_level: string | null;
  notes: string | null;
  next_follow_up_at: string | null;
  attempted_at: string | null;
}

interface RawStatusHistoryRow {
  id: string | null;
  status: string | null;
  note: string | null;
  changed_at: string | null;
  changed_by: string | null;
}

interface RawEnforcementHistoryRow {
  id: string | null;
  judgment_id: number | string | null;
  stage: string | null;
  note: string | null;
  changed_at: string | null;
  changed_by: string | null;
  judgments?: {
    case_number?: string | null;
    plaintiff_id?: string | null;
  } | null;
}

interface RawJudgmentRow {
  judgment_id: string | null;
  case_number: string | null;
  enforcement_stage: string | null;
  enforcement_stage_updated_at: string | null;
  collectability_tier: string | null;
}

interface RawContactRow {
  id: string | null;
  name: string | null;
  role: string | null;
  email: string | null;
  phone: string | null;
}

export function useOpsPlaintiffProfile(plaintiffId: string | null): MetricsHookResult<OpsPlaintiffProfile | null> {
  const [snapshot, setSnapshot] = useState<MetricsState<OpsPlaintiffProfile | null>>(() =>
    buildInitialMetricsState<OpsPlaintiffProfile | null>(),
  );

  const fetchProfile = useCallback(async () => {
    if (!plaintiffId) {
      setSnapshot(buildReadyMetricsState<OpsPlaintiffProfile | null>(null));
      return;
    }

    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<OpsPlaintiffProfile | null>(OPS_PROFILE_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const [plaintiffRes, callsRes, statusRes, enforcementRes, judgmentsRes, contactsRes] = await Promise.all([
        demoSafeSelect<RawPlaintiffRow[] | null>(
          supabaseClient
            .from('plaintiffs')
            .select('id, name, firm_name, phone, email, tier, status, created_at, updated_at')
            .eq('id', plaintiffId)
            .limit(1),
        ),
        demoSafeSelect<RawCallAttemptRow[] | null>(
          supabaseClient
            .from('plaintiff_call_attempts')
            .select('id, outcome, interest_level, notes, next_follow_up_at, attempted_at')
            .eq('plaintiff_id', plaintiffId)
            .order('attempted_at', { ascending: false, nullsFirst: false })
            .limit(CALL_ATTEMPT_LIMIT),
        ),
        demoSafeSelect<RawStatusHistoryRow[] | null>(
          supabaseClient
            .from('plaintiff_status_history')
            .select('id, status, note, changed_at, changed_by')
            .eq('plaintiff_id', plaintiffId)
            .order('changed_at', { ascending: false, nullsFirst: false })
            .limit(STATUS_HISTORY_LIMIT),
        ),
        demoSafeSelect<RawEnforcementHistoryRow[] | null>(
          supabaseClient
            .from('enforcement_history')
            .select('id, judgment_id, stage, note, changed_at, changed_by, judgments!inner(case_number, plaintiff_id)')
            .eq('judgments.plaintiff_id', plaintiffId)
            .order('changed_at', { ascending: false, nullsFirst: false })
            .limit(ENFORCEMENT_HISTORY_LIMIT),
        ),
        demoSafeSelect<RawJudgmentRow[] | null>(
          supabaseClient
            .from('v_judgment_pipeline')
            .select(
              'judgment_id, case_number, enforcement_stage, enforcement_stage_updated_at, collectability_tier',
            )
            .eq('plaintiff_id', plaintiffId)
            .order('enforcement_stage_updated_at', { ascending: false, nullsFirst: false })
            .limit(JUDGMENT_LIMIT),
        ),
        demoSafeSelect<RawContactRow[] | null>(
          supabaseClient
            .from('plaintiff_contacts')
            .select('id, name, role, email, phone')
            .eq('plaintiff_id', plaintiffId)
            .order('created_at', { ascending: true, nullsFirst: false })
            .limit(CONTACT_LIMIT),
        ),
      ]);

      const detailRows = unwrapRows(plaintiffRes);
      const detailRow = detailRows[0];
      if (!detailRow) {
        setSnapshot(
          buildErrorMetricsState<OpsPlaintiffProfile | null>(new Error('Plaintiff not found.'), {
            message: 'We could not find that plaintiff.',
          }),
        );
        return;
      }

      const summary: OpsPlaintiffSummary = {
        id: detailRow.id,
        name: normalizeText(detailRow.name) ?? '—',
        firmName: normalizeNullable(detailRow.firm_name),
        phone: normalizeNullable(detailRow.phone),
        email: normalizeNullable(detailRow.email),
        tier: normalizeTier(detailRow.tier),
        statusLabel: formatStatus(detailRow.status),
        createdAt: detailRow.created_at,
        updatedAt: detailRow.updated_at,
      };

      const contacts = mapContacts(unwrapRows(contactsRes));
      const callAttempts = mapCallAttempts(unwrapRows(callsRes));
      const statusEvents = mapStatusEvents(unwrapRows(statusRes));
      const enforcementEvents = mapEnforcementEvents(unwrapRows(enforcementRes));
      const timeline = buildTimeline(callAttempts, statusEvents, enforcementEvents);
      const judgments = mapJudgments(unwrapRows(judgmentsRes));

      const profile: OpsPlaintiffProfile = {
        summary,
        contacts,
        callAttempts,
        timeline,
        judgments,
      };

      setSnapshot(buildReadyMetricsState(profile));
    } catch (err) {
      const { error: normalizedError, message } = buildDashboardError(err, {
        fallback: 'Unable to load plaintiff profile.',
        viewName: 'Ops console plaintiff profile',
      });
      setSnapshot(buildErrorMetricsState<OpsPlaintiffProfile | null>(normalizedError, { message }));
    }
  }, [plaintiffId]);

  useEffect(() => {
    void fetchProfile();
  }, [fetchProfile]);

  const refetch = useCallback(async () => {
    await fetchProfile();
  }, [fetchProfile]);

  return {
    ...snapshot,
    state: snapshot,
    refetch,
  } satisfies MetricsHookResult<OpsPlaintiffProfile | null>;
}

function mapContacts(rows: RawContactRow[]): OpsContact[] {
  return rows.map((row, index) => ({
    id: (row.id ?? `contact-${index}`).toString(),
    name: normalizeText(row.name) ?? '—',
    role: normalizeNullable(row.role),
    email: normalizeNullable(row.email),
    phone: normalizeNullable(row.phone),
  }));
}

function mapCallAttempts(rows: RawCallAttemptRow[]): OpsCallAttempt[] {
  return rows.map((row, index) => ({
    id: (row.id ?? `call-${index}`).toString(),
    outcome: formatStatus(row.outcome),
    interest: normalizeNullable(row.interest_level),
    notes: normalizeNullable(row.notes),
    followUpAt: row.next_follow_up_at ?? null,
    attemptedAt: row.attempted_at ?? null,
  }));
}

function mapStatusEvents(rows: RawStatusHistoryRow[]): OpsTimelineEvent[] {
  return rows.map((row, index) => ({
    id: (row.id ?? `status-${index}`).toString(),
    type: 'status',
    title: `Status → ${formatStatus(row.status)}`,
    description: row.note ?? null,
    occurredAt: row.changed_at ?? null,
  }));
}

function mapEnforcementEvents(rows: RawEnforcementHistoryRow[]): OpsTimelineEvent[] {
  return rows.map((row, index) => ({
    id: (row.id ?? `enforcement-${index}`).toString(),
    type: 'enforcement',
    title: `Enforcement → ${formatStatus(row.stage)}`,
    description: row.judgments?.case_number ? `Case ${row.judgments.case_number}` : row.note ?? null,
    occurredAt: row.changed_at ?? null,
  }));
}

function buildTimeline(
  calls: OpsCallAttempt[],
  statusEvents: OpsTimelineEvent[],
  enforcementEvents: OpsTimelineEvent[],
): OpsTimelineEvent[] {
  const callEvents: OpsTimelineEvent[] = calls.map((attempt) => ({
    id: `call-timeline-${attempt.id}`,
    type: 'call',
    title: `Call → ${attempt.outcome}`,
    description: attempt.notes,
    occurredAt: attempt.attemptedAt,
  }));

  return [...callEvents, ...statusEvents, ...enforcementEvents]
    .filter((event) => event.occurredAt)
    .sort((a, b) => {
      const aTime = Date.parse(a.occurredAt ?? '');
      const bTime = Date.parse(b.occurredAt ?? '');
      if (Number.isNaN(aTime) || Number.isNaN(bTime)) {
        return 0;
      }
      return bTime - aTime;
    })
    .slice(0, 60);
}

function mapJudgments(rows: RawJudgmentRow[]): OpsPlaintiffJudgment[] {
  return rows.map((row, index) => ({
    judgmentId: (row.judgment_id ?? `judgment-${index}`).toString(),
    caseNumber: normalizeNullable(row.case_number),
    enforcementStage: normalizeNullable(row.enforcement_stage),
    enforcementStageLabel: formatStatus(row.enforcement_stage),
    enforcementStageUpdatedAt: row.enforcement_stage_updated_at ?? null,
    collectabilityTier: normalizeTier(row.collectability_tier),
  }));
}

function normalizeText(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeNullable(value: string | null): string | null {
  const normalized = normalizeText(value);
  return normalized ?? null;
}

function normalizeTier(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed.toUpperCase() : null;
}

function formatStatus(value: string | null): string {
  if (!value) {
    return 'Unknown';
  }
  const normalized = value.trim();
  if (!normalized) {
    return 'Unknown';
  }
  return normalized
    .split(/[_-]/g)
    .map((segment) => (segment ? segment[0]?.toUpperCase() + segment.slice(1) : segment))
    .join(' ');
}

function unwrapRows<TRow>(result: DemoSafeResult<TRow[] | null>): TRow[] {
  if (result.kind === 'demo_locked') {
    throw new Error('Demo locked');
  }
  if (result.kind === 'error') {
    throw result.error;
  }
  return Array.isArray(result.data) ? (result.data as TRow[]) : [];
}
