import React, { useEffect, useMemo, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { supabaseClient } from '../lib/supabaseClient';
import HelpTooltip from '../components/HelpTooltip';
import ZeroStateCard from '../components/ZeroStateCard';

type CollectabilityTier = 'A' | 'B' | 'C';
type TierFilter = CollectabilityTier | 'All';

type FetchState = 'idle' | 'loading' | 'error' | 'ready';

interface CaseSnapshotRow {
  case_id: string;
  case_number: string | null;
  judgment_amount: number | null;
  collectability_tier: CollectabilityTier | null;
  last_enrichment_status: string | null;
}

interface PlaintiffRow {
  case_id: string | null;
  name_full: string | null;
}

interface DisplayCase extends CaseSnapshotRow {
  plaintiff: string;
}

interface FoilResponseRow {
  id: string;
  case_id: string | null;
  agency: string | null;
  received_date: string | null;
  created_at: string | null;
  payload: unknown;
}

interface FoilDisplayRow {
  id: string;
  caseNumber: string;
  agency: string;
  receivedAt: string | null;
  summary: string;
}

interface CaseDetailSnapshot {
  case_id: string;
  case_number: string | null;
  judgment_amount: number | null;
  judgment_date: string | null;
  collectability_tier: CollectabilityTier | null;
  last_enrichment_status: string | null;
  last_enriched_at: string | null;
}

interface EnrichmentRunRow {
  id: string;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  summary?: string | null;
}

interface CaseDetailData {
  snapshot: CaseDetailSnapshot | null;
  plaintiffs: string[];
  defendants: string[];
  enrichmentRuns: EnrichmentRunRow[];
  foilResponses: FoilResponseRow[];
}

const tierOptions: TierFilter[] = ['All', 'A', 'B', 'C'];
const FOIL_RESPONSE_LIMIT = 10;

const CasesPage: React.FC = () => {
  const [cases, setCases] = useState<CaseSnapshotRow[]>([]);
  const [plaintiffs, setPlaintiffs] = useState<Record<string, string>>({});
  const [foilResponses, setFoilResponses] = useState<FoilResponseRow[]>([]);
  const [state, setState] = useState<FetchState>('idle');
  const [error, setError] = useState<PostgrestError | Error | null>(null);
  const [tierFilter, setTierFilter] = useState<TierFilter>('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCases() {
      setState('loading');
      setError(null);

      try {
        const [snapshotResponse, plaintiffsResponse, foilResponse] = await Promise.all([
          supabaseClient
            .from('v_collectability_snapshot')
            .select('case_id, case_number, judgment_amount, collectability_tier, last_enrichment_status')
            .order('collectability_tier', { ascending: true })
            .order('judgment_amount', { ascending: false, nullsFirst: false }),
          supabaseClient
            .from('v_entities_simple')
            .select('case_id, name_full, role')
            .eq('role', 'plaintiff'),
          supabaseClient
            .from('foil_responses')
            .select('id, case_id, agency, received_date, created_at, payload')
            .order('received_date', { ascending: false })
            .order('created_at', { ascending: false })
            .limit(FOIL_RESPONSE_LIMIT),
        ]);

        if (cancelled) {
          return;
        }

        const queryError = snapshotResponse.error ?? plaintiffsResponse.error ?? foilResponse.error;
        if (queryError) {
          setError(queryError);
          setState('error');
          return;
        }

        const snapshotRows = (snapshotResponse.data ?? []) as CaseSnapshotRow[];
        const plaintiffRows = (plaintiffsResponse.data ?? []) as (PlaintiffRow & { role?: string | null })[];
        const foilRows = (foilResponse.data ?? []) as FoilResponseRow[];

        const plaintiffMap: Record<string, string> = {};
        for (const row of plaintiffRows) {
          if (!row.case_id) {
            continue;
          }
          const name = (row.name_full ?? '').trim();
          if (name && !plaintiffMap[row.case_id]) {
            plaintiffMap[row.case_id] = name;
          }
        }

        setCases(snapshotRows);
        setPlaintiffs(plaintiffMap);
        setFoilResponses(foilRows);
        setState('ready');
      } catch (exc) {
        if (cancelled) {
          return;
        }
        setError(exc instanceof Error ? exc : new Error('Unknown error loading cases.'));
        setState('error');
      }
    }

    loadCases();

    return () => {
      cancelled = true;
    };
  }, []);

  const displayRows = useMemo<DisplayCase[]>(() => {
    return cases.map((row) => ({
      ...row,
      plaintiff: plaintiffs[row.case_id] ?? 'Plaintiff',
    }));
  }, [cases, plaintiffs]);

  const filteredRows = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return displayRows.filter((row) => {
      if (tierFilter !== 'All' && row.collectability_tier !== tierFilter) {
        return false;
      }
      if (!term) {
        return true;
      }
      return (row.case_number ?? '').toLowerCase().includes(term);
    });
  }, [displayRows, tierFilter, searchTerm]);

  const sortedRows = useMemo(() => {
    return [...filteredRows].sort((a, b) => {
      const left = typeof a.judgment_amount === 'number' ? a.judgment_amount : -Infinity;
      const right = typeof b.judgment_amount === 'number' ? b.judgment_amount : -Infinity;
      if (right !== left) {
        return right - left;
      }
      return (a.case_number ?? '').localeCompare(b.case_number ?? '');
    });
  }, [filteredRows]);

  const caseNumberById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const row of cases) {
      map[row.case_id] = row.case_number ?? '—';
    }
    return map;
  }, [cases]);

  const foilDisplayRows = useMemo<FoilDisplayRow[]>(() => {
    return foilResponses.map((row) => {
      const caseNumber = row.case_id ? caseNumberById[row.case_id] ?? '—' : '—';
      return {
        id: row.id,
        caseNumber,
        agency: (row.agency ?? '').trim() || '—',
        receivedAt: row.received_date ?? row.created_at ?? null,
        summary: summarizeFoilPayload(row.payload),
      };
    });
  }, [foilResponses, caseNumberById]);

  const selectedCase = useMemo(() => {
    if (!selectedCaseId) {
      return null;
    }
    return displayRows.find((row) => row.case_id === selectedCaseId) ?? null;
  }, [selectedCaseId, displayRows]);

  const loading = state === 'idle' || state === 'loading';
  const emptyCases = state === 'ready' && sortedRows.length === 0;
  const emptyFoil = state === 'ready' && foilDisplayRows.length === 0;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Your Cases</h2>
        <p className="mt-2 text-sm text-slate-600">
          Here's every judgment we're working on. Click any row to see full details about the plaintiff, defendant, and our research history.
        </p>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">Browse Judgments</h3>
            <p className="mt-1 text-sm text-slate-500">Use the search box to find a specific case number.</p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-end sm:gap-4">
            <div className="flex flex-col gap-2 sm:w-48">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="tier-filter">
                Tier filter
                <HelpTooltip text="Show only cases from a specific tier. Tier A has the highest chance of collecting." />
              </label>
              <select
                id="tier-filter"
                value={tierFilter}
                onChange={(event) => setTierFilter(event.target.value as TierFilter)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                {tierOptions.map((option) => (
                  <option key={option} value={option}>
                    {option === 'All' ? 'All tiers' : `Tier ${option}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-2 sm:max-w-xs sm:flex-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="case-search">
                Search
                <HelpTooltip text="Enter a case number or part of one to find a specific judgment quickly." />
              </label>
              <input
                id="case-search"
                type="search"
                placeholder="Search by case number"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-4 text-xs font-medium uppercase tracking-wide text-slate-400">
          Showing {sortedRows.length} of {displayRows.length} cases
        </div>

        {loading && <StatusMessage message="Loading your cases…" tone="neutral" />}

        {state === 'error' && error && <StatusMessage message={error.message} tone="error" />}

        {state === 'ready' && cases.length === 0 && (
          <div className="px-6 pb-6">
            <ZeroStateCard
              title="No cases yet"
              description="Your first judgments will appear here once we import them from Simplicity. Check back soon!"
              actionLink="/help"
              actionLabel="Learn more"
            />
          </div>
        )}

        {emptyCases && cases.length > 0 && <StatusMessage message="No cases match your search. Try clearing the tier filter or search box." tone="neutral" />}

        {!loading && !emptyCases && state === 'ready' && (
          <div className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm text-slate-700">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <HeaderCell>Case Number</HeaderCell>
                    <HeaderCell>Plaintiff</HeaderCell>
                    <HeaderCell>Judgment Amount</HeaderCell>
                    <HeaderCell>Collectability Tier</HeaderCell>
                    <HeaderCell>Last Enrichment Status</HeaderCell>
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((row) => {
                    const isSelected = selectedCaseId === row.case_id;
                    return (
                      <tr
                        key={row.case_id}
                        tabIndex={0}
                        onClick={() => setSelectedCaseId(row.case_id)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setSelectedCaseId(row.case_id);
                          }
                        }}
                        className={`border-b border-slate-100 transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 ${isSelected ? 'bg-blue-50/60' : 'bg-white'} cursor-pointer`}
                      >
                        <DataCell>{row.case_number ?? '—'}</DataCell>
                        <DataCell>{row.plaintiff}</DataCell>
                        <DataCell>{formatCurrency(row.judgment_amount)}</DataCell>
                        <DataCell>
                          {row.collectability_tier ? (
                            <span className={tierPillClass(row.collectability_tier)}>
                              Tier {row.collectability_tier}
                            </span>
                          ) : (
                            '—'
                          )}
                        </DataCell>
                        <DataCell>{row.last_enrichment_status ?? '—'}</DataCell>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 md:flex-row md:items-end md:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              Public Records Responses
              <HelpTooltip text="When we send information requests to agencies like DMV or tax offices, their replies show up here. This helps us find assets we can collect on." />
            </h3>
            <p className="mt-1 text-sm text-slate-500">Information we've received back from government agencies.</p>
          </div>
        </div>

        {loading && <StatusMessage message="Loading public records…" tone="neutral" />}

        {state === 'error' && error && <StatusMessage message={error.message} tone="error" />}

        {!loading && state === 'ready' && emptyFoil && (
          <StatusMessage message="No public records responses yet. These will show up as agencies reply to our requests." tone="neutral" />
        )}

        {!loading && state === 'ready' && !emptyFoil && (
          <div className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm text-slate-700">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <HeaderCell>Case Number</HeaderCell>
                    <HeaderCell>Agency</HeaderCell>
                    <HeaderCell>Received</HeaderCell>
                    <HeaderCell>Notes</HeaderCell>
                  </tr>
                </thead>
                <tbody>
                  {foilDisplayRows.map((row) => (
                    <tr key={row.id} className="border-b border-slate-100 bg-white transition hover:bg-slate-50">
                      <DataCell>{row.caseNumber}</DataCell>
                      <DataCell>{row.agency}</DataCell>
                      <DataCell>{formatFoilTimestamp(row.receivedAt)}</DataCell>
                      <DataCell>{row.summary}</DataCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      <CaseDetailDrawer
        caseId={selectedCaseId}
        onClose={() => setSelectedCaseId(null)}
        initialCase={selectedCase}
      />
    </div>
  );
};

export default CasesPage;

interface CaseDetailDrawerProps {
  caseId: string | null;
  onClose: () => void;
  initialCase: DisplayCase | null;
}

const CaseDetailDrawer: React.FC<CaseDetailDrawerProps> = ({ caseId, onClose, initialCase }) => {
  const open = Boolean(caseId);
  const [detailState, setDetailState] = useState<FetchState>('idle');
  const [detailError, setDetailError] = useState<PostgrestError | Error | null>(null);
  const [detail, setDetail] = useState<CaseDetailData | null>(null);

  useEffect(() => {
    if (!open) {
      setDetail(null);
      setDetailState('idle');
      setDetailError(null);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setDetailState('loading');
      setDetailError(null);

      try {
        const [snapshotResponse, entityResponse, runsResponse, foilResponse] = await Promise.all([
          supabaseClient
            .from('v_collectability_snapshot')
            .select('case_id, case_number, judgment_amount, judgment_date, collectability_tier, last_enrichment_status, last_enriched_at')
            .eq('case_id', caseId)
            .maybeSingle(),
          supabaseClient
            .from('v_entities_simple')
            .select('name_full, role')
            .eq('case_id', caseId),
          supabaseClient
            .from('enrichment_runs')
            .select('*')
            .eq('case_id', caseId)
            .order('created_at', { ascending: false }),
          supabaseClient
            .from('foil_responses')
            .select('id, case_id, agency, received_date, created_at, payload')
            .eq('case_id', caseId)
            .order('received_date', { ascending: false })
            .order('created_at', { ascending: false })
            .limit(FOIL_RESPONSE_LIMIT),
        ]);

        if (cancelled) {
          return;
        }

        const queryError =
          snapshotResponse.error ?? entityResponse.error ?? runsResponse.error ?? foilResponse.error;
        if (queryError) {
          setDetailError(queryError);
          setDetailState('error');
          return;
        }

        const snapshot = (snapshotResponse.data ?? null) as CaseDetailSnapshot | null;
        const entityRows = (entityResponse.data ?? []) as { name_full: string | null; role: string | null }[];
        const plaintiffNames = entityRows
          .filter((row) => row.role === 'plaintiff')
          .map((row) => (row.name_full ?? '').trim())
          .filter((name) => !!name);
        const defendantNames = entityRows
          .filter((row) => row.role === 'defendant')
          .map((row) => (row.name_full ?? '').trim())
          .filter((name) => !!name);

        const runsRaw = (runsResponse.data ?? []) as Record<string, unknown>[];
        const enrichmentRuns: EnrichmentRunRow[] = runsRaw.map((run, index) => {
          const toIso = (value: unknown): string | null =>
            typeof value === 'string' && value.trim().length > 0 ? value : null;
          const summary = run['summary'];
          const idValue = run['id'];
          return {
            id: String(typeof idValue === 'undefined' ? `run-${index}` : idValue),
            status: typeof run['status'] === 'string' ? (run['status'] as string) : null,
            started_at: toIso(run['started_at']),
            finished_at: toIso(run['finished_at']),
            created_at: toIso(run['created_at']),
            summary: typeof summary === 'string' ? (summary as string) : null,
          };
        });

        const foilRows = (foilResponse.data ?? []) as FoilResponseRow[];

        setDetail({
          snapshot,
          plaintiffs: plaintiffNames,
          defendants: defendantNames,
          enrichmentRuns,
          foilResponses: foilRows,
        });
        setDetailState('ready');
      } catch (exc) {
        if (cancelled) {
          return;
        }
        setDetailError(exc instanceof Error ? exc : new Error('Unknown error loading case details.'));
        setDetailState('error');
      }
    }

    loadDetail();

    return () => {
      cancelled = true;
    };
  }, [caseId, open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  const headerCaseNumber = detail?.snapshot?.case_number ?? initialCase?.case_number ?? '—';
  const headerPlaintiff = detail?.plaintiffs?.join(', ') ?? initialCase?.plaintiff ?? '—';
  const headerTier = detail?.snapshot?.collectability_tier ?? initialCase?.collectability_tier ?? null;

  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} aria-hidden="true" />
      <aside className="relative ml-auto flex h-full w-full max-w-5xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Case</p>
            <p className="text-lg font-semibold text-slate-900">{headerCaseNumber}</p>
            <p className="text-sm text-slate-500">{headerPlaintiff}</p>
          </div>
          <div className="flex items-center gap-3">
            {headerTier ? <span className={tierPillClass(headerTier)}>Tier {headerTier}</span> : null}
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
              aria-label="Close case details"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-8 pt-4">
          {detailState === 'loading' && <StatusMessage message="Loading case details…" tone="neutral" />}

          {detailState === 'error' && detailError && (
            <StatusMessage message={detailError.message} tone="error" />
          )}

          {detailState === 'ready' && detail && (
            <div className="grid gap-6 lg:grid-cols-3">
              <article className="rounded-2xl border border-slate-200 bg-white shadow-sm lg:col-span-1">
                <div className="border-b border-slate-200 px-6 py-4">
                  <h3 className="text-base font-semibold text-slate-900">Case overview</h3>
                </div>
                <div className="space-y-5 px-6 py-5 text-sm text-slate-700">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Case number</p>
                      <p className="text-lg font-semibold text-slate-900">
                        {detail.snapshot?.case_number ?? headerCaseNumber}
                      </p>
                    </div>
                    {detail.snapshot?.collectability_tier ? (
                      <span className={tierPillClass(detail.snapshot.collectability_tier)}>
                        Tier {detail.snapshot.collectability_tier}
                      </span>
                    ) : null}
                  </div>
                  <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
                    <DetailItem
                      label="Plaintiff"
                      value={detail.plaintiffs.length ? detail.plaintiffs.join(', ') : '—'}
                    />
                    <DetailItem
                      label="Defendant"
                      value={detail.defendants.length ? detail.defendants.join(', ') : '—'}
                    />
                    <DetailItem
                      label="Judgment amount"
                      value={formatCurrency(detail.snapshot?.judgment_amount ?? null)}
                    />
                    <DetailItem
                      label="Judgment age"
                      value={formatAgeDays(computeAgeDays(detail.snapshot?.judgment_date ?? null))}
                    />
                    <DetailItem
                      label="Judgment date"
                      value={formatFoilTimestamp(detail.snapshot?.judgment_date ?? null)}
                    />
                    <DetailItem
                      label="Last enrichment"
                      value={formatDateTime(detail.snapshot?.last_enriched_at ?? null)}
                    />
                    <DetailItem
                      label="Enrichment status"
                      value={detail.snapshot?.last_enrichment_status ?? '—'}
                    />
                  </dl>
                </div>
              </article>

              <article className="rounded-2xl border border-slate-200 bg-white shadow-sm lg:col-span-1">
                <div className="border-b border-slate-200 px-6 py-4">
                  <h3 className="text-base font-semibold text-slate-900">Enrichment history</h3>
                </div>
                {detail.enrichmentRuns.length === 0 ? (
                  <div className="px-6 py-5 text-sm text-slate-500">
                    No enrichment runs yet. This case will be scored after the first enrichment job completes.
                  </div>
                ) : (
                  <ol className="space-y-4 px-6 py-5">
                    {detail.enrichmentRuns.map((run) => (
                      <li
                        key={`${run.id}-${run.started_at ?? run.created_at ?? '0'}`}
                        className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-slate-900">{run.status ?? '—'}</p>
                            {run.summary ? (
                              <p className="mt-1 text-sm text-slate-600">{run.summary}</p>
                            ) : null}
                          </div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            {formatDateTime(run.started_at ?? run.created_at)}
                          </span>
                        </div>
                        <dl className="mt-3 grid grid-cols-1 gap-3 text-sm text-slate-600 sm:grid-cols-2">
                          <DetailItem
                            label="Started"
                            value={formatDateTime(run.started_at ?? run.created_at)}
                          />
                          <DetailItem label="Finished" value={formatDateTime(run.finished_at)} />
                        </dl>
                      </li>
                    ))}
                  </ol>
                )}
              </article>

              <article className="rounded-2xl border border-slate-200 bg-white shadow-sm lg:col-span-1">
                <div className="border-b border-slate-200 px-6 py-4">
                  <h3 className="text-base font-semibold text-slate-900">FOIL responses</h3>
                </div>
                {detail.foilResponses.length === 0 ? (
                  <div className="px-6 py-5 text-sm text-slate-500">
                    No FOIL responses have been linked to this case.
                  </div>
                ) : (
                  <ul className="space-y-4 px-6 py-5">
                    {detail.foilResponses.map((response) => (
                      <li key={response.id} className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-slate-900">
                              {(response.agency ?? '').trim() || '—'}
                            </p>
                            <p className="mt-1 text-sm text-slate-600">
                              {summarizeFoilPayload(response.payload)}
                            </p>
                          </div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                            {formatFoilTimestamp(response.received_date ?? response.created_at ?? null)}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            </div>
          )}

          {detailState === 'ready' && !detail && (
            <StatusMessage message="No additional details available for this case." tone="neutral" />
          )}
        </div>
      </aside>
    </div>
  );
};

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-700">{value ?? '—'}</dd>
    </div>
  );
}

function HeaderCell({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3">{children}</th>;
}

function DataCell({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 align-middle text-sm text-slate-700">{children}</td>;
}

function computeAgeDays(judgmentDate: string | null): number | null {
  if (!judgmentDate) {
    return null;
  }
  const parsed = new Date(judgmentDate);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const today = new Date();
  const diffMs = today.getTime() - parsed.getTime();
  if (!Number.isFinite(diffMs)) {
    return null;
  }
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  return diffDays < 0 ? 0 : diffDays;
}

function formatAgeDays(ageDays: number | null): string {
  if (ageDays === null) {
    return '—';
  }
  return `${ageDays.toLocaleString()} days`;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function formatCurrency(value: number | null): string {
  if (typeof value !== 'number') {
    return '—';
  }
  return currencyFormatter.format(value);
}

function tierPillClass(tier: CollectabilityTier): string {
  switch (tier) {
    case 'A':
      return 'inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-700';
    case 'B':
      return 'inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-700';
    case 'C':
    default:
      return 'inline-flex items-center rounded-full border border-slate-500/30 bg-slate-500/10 px-2.5 py-0.5 text-xs font-semibold text-slate-700';
  }
}

function StatusMessage({ message, tone }: { message: string; tone: 'neutral' | 'error' }) {
  if (tone === 'error') {
    return (
      <div className="px-6 pb-6">
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{message}</div>
      </div>
    );
  }

  return (
    <div className="px-6 pb-6">
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm text-slate-600">
        {message}
      </div>
    </div>
  );
}

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatDateTime(value: string | null): string {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return dateTimeFormatter.format(parsed);
}

const foilDateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
});

function formatFoilTimestamp(value: string | null): string {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return foilDateFormatter.format(parsed);
}

function summarizeFoilPayload(payload: unknown): string {
  if (!payload) {
    return '—';
  }
  if (typeof payload === 'string') {
    const text = payload.trim();
    return text ? text : '—';
  }
  if (typeof payload === 'object' && payload !== null) {
    const record = payload as Record<string, unknown>;
    const parts: string[] = [];
    const status = record.status;
    if (typeof status === 'string' && status.trim()) {
      parts.push(status.trim());
    }
    const notes = record.notes;
    if (typeof notes === 'string' && notes.trim()) {
      parts.push(notes.trim());
    }
    if (parts.length > 0) {
      return parts.join(' — ');
    }
  }
  return '—';
}
