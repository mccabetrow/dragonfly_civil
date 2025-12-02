import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { DashboardError } from '../components/DashboardError.tsx';
import { InlineSpinner } from '../components/InlineSpinner.tsx';
import CaseCopilotPanel from '../components/CaseCopilotPanel.tsx';
import DemoLockCard from '../components/DemoLockCard';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import { useEnforcementOverview, type EnforcementOverviewRow } from '../hooks/useEnforcementOverview';
import { useEnforcementRecent } from '../hooks/useEnforcementRecent';
import { useCaseCopilotInsight, type CaseCopilotInsight } from '../hooks/useCaseCopilotInsight';
import { supabaseClient } from '../lib/supabaseClient';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import PageHeader from '../components/PageHeader';
import SectionHeader from '../components/SectionHeader';
import MetricsGate from '../components/MetricsGate';
import StatusMessage from '../components/StatusMessage';
import RefreshButton from '../components/RefreshButton';

const STAGE_ORDER = [
  'pre_enforcement',
  'paperwork_filed',
  'levy_issued',
  'waiting_payment',
  'payment_plan',
  'collected',
  'closed_no_recovery',
  'unknown',
];

const STAGE_LABELS: Record<string, string> = {
  pre_enforcement: 'Pre-enforcement',
  paperwork_filed: 'Paperwork filed',
  levy_issued: 'Levy issued',
  waiting_payment: 'Waiting for payment',
  payment_plan: 'Payment plan',
  collected: 'Collected',
  closed_no_recovery: 'Closed · no recovery',
  unknown: 'Other',
};

const CASE_COPILOT_DOCS_URL =
  'https://github.com/mccabetrow/dragonfly_civil/blob/main/RUNBOOK_DAD.md#case-copilot';

interface StageTierBreakdown {
  tier: string;
  label: string;
  caseCount: number;
}

interface StageGroup {
  stage: string;
  label: string;
  totalCases: number;
  totalJudgmentAmount: number;
  tiers: StageTierBreakdown[];
}

export default function EnforcementPage() {
  const navigate = useNavigate();
  const { state: overviewState, refetch: refetchOverview } = useEnforcementOverview();
  const { state: recentState, refetch: refetchRecent } = useEnforcementRecent();

  const overviewRows = overviewState.data ?? [];
  const recentRows = recentState.data ?? [];
  const overviewStatus = overviewState.status;
  const recentStatus = recentState.status;
  const recentError = recentState.error;
  const recentErrorMessage = recentState.errorMessage;
  const overviewLoading = overviewStatus === 'loading' || overviewStatus === 'idle';
  const recentLoading = recentStatus === 'loading' || recentStatus === 'idle';

  const [selectedCaseNumber, setSelectedCaseNumber] = useState<string | null>(null);
  const [caseInputValue, setCaseInputValue] = useState('');
  const [copilotStatusMessage, setCopilotStatusMessage] = useState<string | null>(null);
  const [copilotActionError, setCopilotActionError] = useState<string | null>(null);
  const [isRegeneratingCopilot, setIsRegeneratingCopilot] = useState(false);

  const {
    data: copilotData,
    status: copilotStatus,
    error: copilotErrorValue,
    errorMessage: copilotErrorMessage,
    lockMessage: copilotLockMessage,
    refetch: refetchCopilot,
  } = useCaseCopilotInsight(selectedCaseNumber);

  const copilotCaseInfo = copilotData?.caseInfo ?? null;
  const copilotInsight = copilotData?.insight ?? null;
  const copilotLoading = copilotStatus === 'loading' || copilotStatus === 'idle';
  const copilotDemoLocked = copilotStatus === 'demo_locked';
  const copilotLoadError =
    copilotStatus === 'error'
      ? copilotErrorMessage ?? (typeof copilotErrorValue === 'string' ? copilotErrorValue : copilotErrorValue?.message) ?? null
      : null;

  const copilotInsightRef = useRef<CaseCopilotInsight | null>(null);
  useEffect(() => {
    copilotInsightRef.current = copilotInsight;
  }, [copilotInsight]);

  const stageGroups = useMemo(() => buildStageGroups(overviewRows), [overviewRows]);
  const caseOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: string[] = [];
    for (const row of recentRows) {
      const value = row.caseNumber?.trim();
      if (!value || value === '—') {
        continue;
      }
      const normalized = value.toUpperCase();
      if (seen.has(normalized)) {
        continue;
      }
      seen.add(normalized);
      options.push(normalized);
    }
    return options;
  }, [recentRows]);
  const quickPickOptions = useMemo(() => caseOptions.slice(0, 5), [caseOptions]);
  const overviewReadyContent =
    stageGroups.length === 0 ? (
      <StatusMessage tone="info">No enforcement metrics recorded yet. Run an intake to populate this view.</StatusMessage>
    ) : (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {stageGroups.map((group) => (
          <StageCard key={group.stage} group={group} isLoading={overviewLoading} />
        ))}
      </div>
    );
  const overviewLoadingContent = (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <StageSkeletonGroup />
    </div>
  );
  const recentDemoLocked = recentStatus === 'demo_locked';
  const recentHeaderActions = recentDemoLocked
    ? null
    : (
        <RefreshButton
          onClick={() => void refetchRecent()}
          isLoading={recentLoading}
          hasData={recentRows.length > 0}
        />
      );

  useEffect(() => {
    if (selectedCaseNumber) {
      return;
    }
    const first = caseOptions[0];
    if (first) {
      setSelectedCaseNumber(first);
      setCaseInputValue(first);
    }
  }, [caseOptions, selectedCaseNumber]);

  useEffect(() => {
    setCopilotActionError(null);
    setCopilotStatusMessage(null);
  }, [selectedCaseNumber]);

  const recentProblem =
    recentErrorMessage || (typeof recentError === 'string' ? recentError : recentError?.message) || null;
  const showRecentSkeleton = recentLoading && recentRows.length === 0;
  const showRecentEmpty = recentStatus === 'ready' && recentRows.length === 0;
  const showRecentTable = recentStatus === 'ready' && recentRows.length > 0;

  const handleCaseInputChange = useCallback((value: string) => {
    const normalized = value.trim().toUpperCase();
    setCaseInputValue(normalized);
    setSelectedCaseNumber(normalized.length > 0 ? normalized : null);
  }, []);

  const waitForCopilotRefresh = useCallback(
    async (previousTimestamp: string | null) => {
      const maxAttempts = 5;
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        await delay(4000);
        await refetchCopilot();
        const current = copilotInsightRef.current?.generatedAt ?? null;
        if (current && current !== previousTimestamp) {
          return true;
        }
      }
      return false;
    },
    [refetchCopilot],
  );

  const handleCopilotRegenerate = useCallback(async () => {
    if (!copilotCaseInfo?.caseId) {
      setCopilotActionError('Select an enforcement case first.');
      return;
    }
    setCopilotActionError(null);
    setCopilotStatusMessage('Queued new summary…');
    setIsRegeneratingCopilot(true);
    try {
      const { error } = await supabaseClient.rpc('request_case_copilot', {
        case_id: copilotCaseInfo.caseId,
        requested_by: 'dashboard',
      });
      if (error) {
        throw new Error(error.message ?? 'Failed to queue Case Copilot');
      }
      const previous = copilotInsight?.generatedAt ?? null;
      const updated = await waitForCopilotRefresh(previous);
      setCopilotStatusMessage(updated ? 'Summary refreshed.' : 'Worker is still running. Refresh again in ~30 seconds.');
    } catch (err) {
      console.error('[CaseCopilot] regenerate error', err);
      setCopilotActionError(err instanceof Error ? err.message : 'Failed to run Case Copilot');
      setCopilotStatusMessage(null);
    } finally {
      setIsRegeneratingCopilot(false);
    }
  }, [copilotCaseInfo?.caseId, copilotInsight?.generatedAt, waitForCopilotRefresh]);

  const caseCopilotError = copilotDemoLocked ? copilotActionError : copilotActionError ?? copilotLoadError;

  const handleNavigate = (caseNumber: string) => {
    if (!caseNumber || caseNumber === '—') {
      return;
    }
    navigate(`/cases/number/${encodeURIComponent(caseNumber)}`);
  };

  return (
    <div className="df-page">
      <PageHeader title="Enforcement" subtitle="Supabase production parity" eyebrow="Case control" />
      <CaseCopilotPanel
        caseInputValue={caseInputValue}
        onCaseInputChange={handleCaseInputChange}
        caseOptions={caseOptions}
        quickPickOptions={quickPickOptions}
        caseInfo={copilotCaseInfo}
        insight={copilotInsight}
        isLoading={copilotLoading}
        error={caseCopilotError}
        isRegenerating={isRegeneratingCopilot}
        statusMessage={copilotStatusMessage}
        onRegenerate={() => void handleCopilotRegenerate()}
        onRefresh={() => void refetchCopilot()}
        docsUrl={CASE_COPILOT_DOCS_URL}
        isLocked={copilotDemoLocked}
        lockMessage={copilotLockMessage}
      />
      <section className="space-y-4">
        <SectionHeader
          title="Enforcement overview"
          description="Track judgments by enforcement stage and pinpoint today’s dollar exposure."
        />
        <MetricsGate
          state={overviewState}
          errorTitle="Enforcement overview unavailable"
          onRetry={() => void refetchOverview()}
          loadingFallback={overviewLoadingContent}
          ready={overviewReadyContent}
          showReadyWhileLoading={overviewRows.length > 0}
          refreshingMessage="Refreshing enforcement overview…"
        />
      </section>

      <section className="df-card">
        <div className="border-b border-slate-100 px-6 py-5">
          <SectionHeader
            title="Recent enforcement activity"
            description="Newest enforcement updates first. Click a row to open the case file."
            actions={recentHeaderActions}
          />
        </div>

        {recentDemoLocked ? (
          <div className="px-6 py-6">
            <DemoLockCard description={recentState.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
          </div>
        ) : recentStatus === 'error' ? (
          <div className="px-6 py-6">
            <DashboardError
              title="Enforcement activity error"
              message={recentProblem ?? 'We couldn’t load recent enforcement activity.'}
              onRetry={() => void refetchRecent()}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-100 text-left">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <HeaderCell>Case number</HeaderCell>
                  <HeaderCell>Plaintiff</HeaderCell>
                  <HeaderCell>Stage</HeaderCell>
                  <HeaderCell>Collectability</HeaderCell>
                  <HeaderCell>Judgment</HeaderCell>
                  <HeaderCell>Updated</HeaderCell>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
                {showRecentSkeleton ? <RecentSkeletonRows /> : null}
                {showRecentEmpty ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-10 text-center text-sm text-slate-500">
                      No enforcement updates recorded yet. Activity will appear here automatically.
                    </td>
                  </tr>
                ) : null}
                {showRecentTable
                  ? recentRows.map((row, index) => (
                      <RecentRow
                        key={`${row.judgmentId || row.caseNumber || index}-${row.updatedAt ?? 'na'}`}
                        row={row}
                        onNavigate={handleNavigate}
                      />
                    ))
                  : null}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StageCard({ group, isLoading }: { group: StageGroup; isLoading: boolean }) {
  return (
    <article className="df-card flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stage</p>
          <h4 className="mt-1 text-lg font-semibold text-slate-900">{group.label}</h4>
        </div>
        {isLoading ? <InlineSpinner /> : null}
      </div>
      <dl className="grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
        <div className="df-subcard">
          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total cases</dt>
          <dd className="mt-1 text-base font-semibold text-slate-900">{group.totalCases.toLocaleString()}</dd>
        </div>
        <div className="df-subcard">
          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total judgment</dt>
          <dd className="mt-1 text-base font-semibold text-slate-900">{formatCurrency(group.totalJudgmentAmount)}</dd>
        </div>
      </dl>
      <TierBreakdown tiers={group.tiers} totalCases={group.totalCases} />
    </article>
  );
}

function TierBreakdown({ tiers, totalCases }: { tiers: StageTierBreakdown[]; totalCases: number }) {
  if (totalCases === 0) {
    return <p className="text-xs text-slate-500">No cases in this stage yet.</p>;
  }
  if (tiers.length === 0) {
    return <p className="text-xs text-slate-500">Cases are present but not yet scored.</p>;
  }
  return (
    <ul className="grid gap-1 text-xs text-slate-600">
      {tiers.map((tier) => (
        <li key={tier.tier} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
          <span className="font-medium text-slate-700">{tier.label}</span>
          <span className="text-slate-500">{tier.caseCount.toLocaleString()} cases</span>
        </li>
      ))}
    </ul>
  );
}

function StageSkeletonGroup() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, index) => (
        <article key={`stage-skeleton-${index}`} className="df-card animate-pulse">
          <div className="h-4 w-32 rounded bg-slate-200" />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="h-14 rounded bg-slate-200" />
            <div className="h-14 rounded bg-slate-200" />
          </div>
          <div className="mt-4 space-y-2">
            <div className="h-10 rounded bg-slate-200" />
            <div className="h-10 rounded bg-slate-200" />
          </div>
        </article>
      ))}
    </>
  );
}

function HeaderCell({ children }: { children: ReactNode }) {
  return <th className="px-6 py-3">{children}</th>;
}

function DataCell({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <td className={`px-6 py-4 align-middle ${className}`.trim()}>{children}</td>;
}

function RecentSkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, rowIndex) => (
        <tr key={`recent-skeleton-${rowIndex}`} className="animate-pulse">
          {Array.from({ length: 6 }).map((__, colIndex) => (
            <td key={`recent-skeleton-${rowIndex}-${colIndex}`} className="px-6 py-4">
              <div className="h-4 rounded bg-slate-200" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

type RecentRowType = NonNullable<ReturnType<typeof useEnforcementRecent>['data']>[number];

function RecentRow({ row, onNavigate }: { row: RecentRowType; onNavigate: (caseNumber: string) => void }) {
  return (
    <tr
      tabIndex={0}
      onClick={() => onNavigate(row.caseNumber)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onNavigate(row.caseNumber);
        }
      }}
      className="cursor-pointer transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500/40"
    >
      <DataCell className="font-medium text-slate-800">{row.caseNumber}</DataCell>
      <DataCell>{row.plaintiffName}</DataCell>
      <DataCell>
        <span className={stageBadgeClass(row.enforcementStage)}>{humanizeStage(row.enforcementStage)}</span>
      </DataCell>
      <DataCell>{row.collectabilityTier ? formatTierLabel(row.collectabilityTier) : 'Not scored'}</DataCell>
      <DataCell>{formatCurrency(row.judgmentAmount)}</DataCell>
      <DataCell>{formatDateTime(row.updatedAt)}</DataCell>
    </tr>
  );
}

function buildStageGroups(rows: EnforcementOverviewRow[]): StageGroup[] {
  const stageMap = new Map<string, { stage: string; label: string; totalCases: number; totalJudgmentAmount: number; tiers: Map<string, StageTierBreakdown> }>();

  for (const stage of STAGE_ORDER) {
    stageMap.set(stage, {
      stage,
      label: humanizeStage(stage),
      totalCases: 0,
      totalJudgmentAmount: 0,
      tiers: new Map(),
    });
  }

  for (const row of rows) {
    const stageKey = row.enforcementStage || 'unknown';
    const group = stageMap.get(stageKey) ?? {
      stage: stageKey,
      label: humanizeStage(stageKey),
      totalCases: 0,
      totalJudgmentAmount: 0,
      tiers: new Map<string, StageTierBreakdown>(),
    };

    group.totalCases += row.caseCount;
    group.totalJudgmentAmount += row.totalJudgmentAmount;

    const tierKey = row.collectabilityTier ?? 'unscored';
    const tier = group.tiers.get(tierKey) ?? {
      tier: tierKey,
      label: formatTierLabel(tierKey),
      caseCount: 0,
    };
    tier.caseCount += row.caseCount;
    group.tiers.set(tierKey, tier);

    stageMap.set(stageKey, group);
  }

  return Array.from(stageMap.values())
    .sort((a, b) => stageOrderIndex(a.stage) - stageOrderIndex(b.stage))
    .map((group) => ({
      stage: group.stage,
      label: group.label,
      totalCases: group.totalCases,
      totalJudgmentAmount: group.totalJudgmentAmount,
      tiers: Array.from(group.tiers.values()).sort((a, b) => a.label.localeCompare(b.label)),
    }));
}

function humanizeStage(stage: string): string {
  if (STAGE_LABELS[stage]) {
    return STAGE_LABELS[stage];
  }
  return stage
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function stageBadgeClass(stage: string): string {
  switch (stage) {
    case 'collected':
      return 'inline-flex w-max items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-700';
    case 'payment_plan':
      return 'inline-flex w-max items-center rounded-full bg-blue-500/10 px-2 py-0.5 text-xs font-semibold text-blue-700';
    case 'waiting_payment':
      return 'inline-flex w-max items-center rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-700';
    case 'levy_issued':
      return 'inline-flex w-max items-center rounded-full bg-indigo-500/10 px-2 py-0.5 text-xs font-semibold text-indigo-700';
    case 'paperwork_filed':
      return 'inline-flex w-max items-center rounded-full bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-700';
    case 'closed_no_recovery':
      return 'inline-flex w-max items-center rounded-full bg-slate-500/10 px-2 py-0.5 text-xs font-semibold text-slate-700';
    case 'pre_enforcement':
    default:
      return 'inline-flex w-max items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700';
  }
}

function formatTierLabel(tier: string): string {
  const normalized = tier.trim().toLowerCase();
  switch (normalized) {
    case 'tier_1':
    case 'tier1':
      return 'Tier 1';
    case 'tier_2':
    case 'tier2':
      return 'Tier 2';
    case 'tier_3':
    case 'tier3':
      return 'Tier 3';
    case 'tier_4':
    case 'tier4':
      return 'Tier 4';
    case 'tier_5':
    case 'tier5':
      return 'Tier 5';
    case 'unscored':
    case 'unscored_cases':
      return 'Not scored';
    default:
      return normalized ? normalized.replace(/[_-]+/g, ' ').replace(/\b([a-z])/g, (match) => match.toUpperCase()) : 'Not scored';
  }
}

function stageOrderIndex(stage: string): number {
  const index = STAGE_ORDER.indexOf(stage);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
