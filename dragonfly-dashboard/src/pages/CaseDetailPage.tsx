import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { DashboardError } from '../components/DashboardError.tsx';
import { InlineSpinner } from '../components/InlineSpinner.tsx';
import { ActivityFeed } from '../components/ActivityFeed.tsx';
import { supabaseClient } from '../lib/supabaseClient';

type FetchState = 'loading' | 'ready' | 'not-found' | 'error';

interface CaseSummary {
  caseId: string;
  caseNumber: string | null;
  plaintiff: string | null;
  defendant: string | null;
  judgmentAmount: number | null;
  collectabilityScore: number | null;
  collectabilityTier: string | null;
  statusLabel: string | null;
  lastEnrichedAt: string | null;
  lastScoredAt: string | null;
  lastUpdatedAt: string | null;
}

interface EnrichmentEntry {
  id: number;
  status: string;
  statusCategory: StatusTone;
  summary: string | null;
  createdAt: string | null;
  source: string | null;
}

interface EnforcementTaskEntry {
  id: string;
  label: string | null;
  status: string;
  statusCategory: StatusTone;
  dueAt: string | null;
  createdAt: string | null;
  assignee: string | null;
}

interface CaseDetailData {
  summary: CaseSummary;
  enrichmentHistory: EnrichmentEntry[];
  enforcementTasks: EnforcementTaskEntry[];
}

type StatusTone = 'pending' | 'completed' | 'failed' | 'other';

export default function CaseDetailPage() {
  const [state, data, error, refresh] = useCaseDetail();

  if (state === 'loading') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 py-16">
        <InlineSpinner label="Loading case" />
        <p className="text-sm text-slate-500">Fetching the latest details for this case.</p>
      </div>
    );
  }

  if (state === 'error') {
    return <DashboardError message={error ?? 'Failed to load case detail.'} onRetry={refresh} title="Case detail error" />;
  }

  if (state === 'not-found' || !data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 rounded-3xl border border-slate-200 bg-white py-14">
        <p className="text-lg font-semibold text-slate-800">Case not found</p>
        <p className="text-sm text-slate-500">We could not locate that case in the system.</p>
        <Link
          to="/cases"
          className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
        >
          Back to cases
        </Link>
      </div>
    );
  }

  const { summary } = data;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Case detail</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">{summary.caseNumber ?? summary.caseId}</h1>
          <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-2 text-sm text-slate-600 sm:grid-cols-2">
            <DetailRow label="Plaintiff" value={summary.plaintiff ?? '—'} />
            <DetailRow label="Defendant" value={summary.defendant ?? '—'} />
            <DetailRow label="Status" value={summary.statusLabel ?? '—'} />
            <DetailRow label="Collectability score" value={formatScore(summary.collectabilityScore, summary.collectabilityTier)} />
            <DetailRow label="Judgment amount" value={formatCurrency(summary.judgmentAmount)} />
            <DetailRow label="Last enriched" value={formatDate(summary.lastEnrichedAt)} />
            <DetailRow label="Last scored" value={formatDate(summary.lastScoredAt)} />
            <DetailRow label="Last updated" value={formatDate(summary.lastUpdatedAt)} />
          </dl>
        </div>
        <button
          type="button"
          onClick={refresh}
          className="self-start rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
        >
          Refresh
        </button>
      </header>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CaseCard
          title="Recent enrichment"
          footer={<Link to="/ops" className="text-sm font-medium text-indigo-600 hover:text-indigo-800">Open ops console →</Link>}
        >
          <Timeline
            entries={data.enrichmentHistory.map((item) => ({
              id: String(item.id),
              primary: item.summary ?? item.status,
              secondary: formatDate(item.createdAt),
              badge: { label: item.status, tone: item.statusCategory },
              meta: item.source ?? undefined,
            }))}
          />
        </CaseCard>

        <CaseCard title="Enforcement tasks">
          <Timeline
            entries={data.enforcementTasks.map((task) => ({
              id: task.id,
              primary: task.label ?? task.status,
              secondary: formatDate(task.createdAt),
              badge: { label: task.status, tone: task.statusCategory },
              meta: task.assignee ? `Assigned to ${task.assignee}` : undefined,
              extra: task.dueAt ? `Due ${formatDate(task.dueAt)}` : undefined,
            }))}
          />
        </CaseCard>
      </section>

      <CaseCard title="Activity stream">
        <ActivityFeed caseId={summary.caseId} limit={40} emptyMessage="No timeline entries captured yet." />
      </CaseCard>
    </div>
  );
}

function useCaseDetail(): [FetchState, CaseDetailData | null, string | null, () => Promise<void>] {
  const params = useParams<{ caseId?: string; caseNumber?: string }>();
  const navigate = useNavigate();
  const [state, setState] = useState<FetchState>('loading');
  const [data, setData] = useState<CaseDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchCase = useCallback(async () => {
    const caseIdParam = params.caseId?.trim();
    const caseNumberParam = params.caseNumber ? decodeURIComponent(params.caseNumber) : null;

    if (!caseIdParam && !caseNumberParam) {
      setState('not-found');
      setData(null);
      setError('Missing case identifier.');
      return;
    }

    setState('loading');
    setError(null);

    try {
      let snapshotQuery = supabaseClient
        .from('v_collectability_snapshot')
        .select('case_id, case_number, judgment_amount, collectability_tier, last_enrichment_status, last_enriched_at')
        .limit(1);
      if (caseIdParam) {
        snapshotQuery = snapshotQuery.eq('case_id', caseIdParam);
      } else if (caseNumberParam) {
        snapshotQuery = snapshotQuery.eq('case_number', caseNumberParam);
      }
      const snapshotRes = await snapshotQuery.maybeSingle();
      if (snapshotRes.error) {
        throw snapshotRes.error;
      }

      const snapshot = snapshotRes.data;
      const effectiveCaseId = caseIdParam ?? snapshot?.case_id ?? null;
      const effectiveCaseNumber = snapshot?.case_number ?? caseNumberParam;

      if (!effectiveCaseId) {
        setState('not-found');
        setData(null);
        setError('Case not found.');
        return;
      }

      if (!caseIdParam && effectiveCaseId) {
        navigate(`/cases/${effectiveCaseId}`, { replace: true });
        return;
      }

      const metricsPromise = supabaseClient
        .from('v_cases')
        .select('case_id, collectability_score, collectability_tier, status, last_enriched_at, last_scored_at, updated_at')
        .eq('case_id', effectiveCaseId)
        .maybeSingle();

      const entitiesPromise = supabaseClient
        .from('v_entities_simple')
        .select('case_id, role, name_full')
        .eq('case_id', effectiveCaseId);

      const enrichmentPromise = supabaseClient
        .from('enrichment_runs')
        .select('id, status, summary, raw, created_at')
        .eq('case_id', effectiveCaseId)
        .order('created_at', { ascending: false, nullsFirst: false })
        .limit(15);

      const taskOrClauses = [
        `case_id.eq.${effectiveCaseId}`,
        `ref_case_id.eq.${effectiveCaseId}`,
      ];
      if (effectiveCaseNumber) {
        taskOrClauses.push(`case_number.eq.${effectiveCaseNumber}`);
      }

      const tasksPromise = supabaseClient
        .from('enforcement.tasks')
        .select('task_id, label, status, due_at, created_at, payload, case_number, case_id')
        .or(taskOrClauses.join(','))
        .order('created_at', { ascending: false, nullsFirst: false })
        .limit(15);

      const [metricsRes, entitiesRes, enrichmentRes, tasksRes] = await Promise.all([
        metricsPromise,
        entitiesPromise,
        enrichmentPromise,
        tasksPromise,
      ]);

      if (metricsRes.error) throw metricsRes.error;
      if (entitiesRes.error) throw entitiesRes.error;
      if (enrichmentRes.error) throw enrichmentRes.error;
      if (tasksRes.error) throw tasksRes.error;

      const metrics = metricsRes.data;
      const entities = entitiesRes.data ?? [];

      const plaintiffs: string[] = [];
      const defendants: string[] = [];
      for (const entity of entities) {
        const role = (entity.role ?? '').toLowerCase();
        const name = (entity.name_full ?? '').trim();
        if (!name) continue;
        if (role === 'plaintiff' && !plaintiffs.includes(name)) {
          plaintiffs.push(name);
        }
        if (role === 'defendant' && !defendants.includes(name)) {
          defendants.push(name);
        }
      }

      const status = metrics?.status ?? snapshot?.last_enrichment_status ?? null;

      const summary: CaseSummary = {
        caseId: effectiveCaseId,
        caseNumber: effectiveCaseNumber,
        plaintiff: plaintiffs[0] ?? null,
        defendant: defendants[0] ?? null,
        judgmentAmount: snapshot?.judgment_amount ?? null,
        collectabilityScore: safeNumber(metrics?.collectability_score),
        collectabilityTier: metrics?.collectability_tier ?? snapshot?.collectability_tier ?? null,
        statusLabel: status ? titleCase(status.replace(/[_-]+/g, ' ')) : null,
        lastEnrichedAt: metrics?.last_enriched_at ?? snapshot?.last_enriched_at ?? null,
        lastScoredAt: metrics?.last_scored_at ?? null,
        lastUpdatedAt: metrics?.updated_at ?? snapshot?.last_enriched_at ?? null,
      };

      const enrichmentHistory: EnrichmentEntry[] = (enrichmentRes.data ?? []).map((row) => ({
        id: row.id,
        status: row.status ?? 'unknown',
        statusCategory: categorizeStatus(row.status),
        summary: row.summary ?? null,
        createdAt: row.created_at ?? null,
        source: extractSource(row.raw),
      }));

      const enforcementTasks: EnforcementTaskEntry[] = (tasksRes.data ?? []).map((row) => ({
        id: row.task_id,
        label: row.label ?? null,
        status: row.status ?? 'open',
        statusCategory: categorizeStatus(row.status),
        dueAt: row.due_at ?? null,
        createdAt: row.created_at ?? null,
        assignee: extractAssignee(row.payload),
      }));

      setData({ summary, enrichmentHistory, enforcementTasks });
      setState('ready');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load case detail.';
      setError(message);
      setState('error');
    }
  }, [navigate, params.caseId, params.caseNumber]);

  useEffect(() => {
    fetchCase();
  }, [fetchCase]);

  const refresh = useCallback(async () => {
    await fetchCase();
  }, [fetchCase]);

  return [state, data, error, refresh];
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-slate-700">{value}</dd>
    </div>
  );
}

function CaseCard({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode | null }) {
  return (
    <div className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      </header>
      <div className="flex flex-1 flex-col justify-between">
        <div className="px-5 py-4">{children}</div>
        {footer ? <div className="border-t border-slate-100 px-5 py-3 text-sm text-slate-500">{footer}</div> : null}
      </div>
    </div>
  );
}

interface TimelineEntry {
  id: string;
  primary: string;
  secondary?: string;
  badge?: { label: string; tone: StatusTone };
  meta?: string;
  extra?: string;
}

function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <p className="text-sm text-slate-500">No activity recorded.</p>;
  }
  return (
    <ol className="space-y-4">
      {entries.map((entry) => (
        <li key={entry.id} className="flex items-start gap-3">
          <span className="mt-1 h-2 w-2 rounded-full bg-slate-300" aria-hidden />
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-slate-800">{entry.primary}</p>
              {entry.badge ? <StatusBadge tone={entry.badge.tone} label={entry.badge.label} /> : null}
            </div>
            {entry.secondary ? <p className="text-xs text-slate-500">{entry.secondary}</p> : null}
            {entry.meta ? <p className="text-xs text-slate-500">{entry.meta}</p> : null}
            {entry.extra ? <p className="text-xs text-slate-500">{entry.extra}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function StatusBadge({ tone, label }: { tone: StatusTone; label: string }) {
  const palette: Record<StatusTone, string> = {
    pending: 'bg-amber-100 text-amber-800 border-amber-200',
    completed: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    failed: 'bg-rose-100 text-rose-800 border-rose-200',
    other: 'bg-slate-100 text-slate-700 border-slate-200',
  };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${palette[tone]}`}>
      {label}
    </span>
  );
}

function categorizeStatus(raw: string | null | undefined): StatusTone {
  if (!raw) {
    return 'other';
  }
  const normalized = raw.trim().toLowerCase();
  if (!normalized) {
    return 'other';
  }
  if (['success', 'completed', 'complete', 'closed', 'done'].includes(normalized)) {
    return 'completed';
  }
  if (['failed', 'error', 'errored', 'aborted', 'cancelled'].includes(normalized)) {
    return 'failed';
  }
  if (['pending', 'running', 'queued', 'in_progress', 'open', 'active'].includes(normalized)) {
    return 'pending';
  }
  return 'other';
}

function extractSource(raw: unknown): string | null {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const record = raw as Record<string, unknown>;
  const value = record['source'] ?? record['channel'] ?? record['origin'];
  if (typeof value === 'string' && value.trim()) {
    return value.trim();
  }
  return null;
}

function extractAssignee(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const record = payload as Record<string, unknown>;
  const direct = record['assignee'];
  const nested = record['assigned_to'];
  if (typeof direct === 'string' && direct.trim()) {
    return direct.trim();
  }
  if (typeof nested === 'string' && nested.trim()) {
    return nested.trim();
  }
  return null;
}

function safeNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
}

function formatCurrency(value: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);
}

function formatScore(score: number | null, tier: string | null): string {
  if (typeof score !== 'number' || Number.isNaN(score)) {
    return tier ? `Tier ${tier}` : '—';
  }
  const rounded = Math.round(score);
  return tier ? `${rounded} (Tier ${tier})` : String(rounded);
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return parsed.toLocaleString();
}

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}
