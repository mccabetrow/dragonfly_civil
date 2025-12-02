import React, { useEffect, useMemo, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { supabaseClient } from '../lib/supabaseClient';
import HelpTooltip from '../components/HelpTooltip';
import ZeroStateCard from '../components/ZeroStateCard';

type CollectabilityTier = 'A' | 'B' | 'C';

interface SnapshotRow {
  case_id: string;
  case_number: string | null;
  judgment_amount: number | null;
  age_days: number | null;
  collectability_tier: CollectabilityTier;
  last_enrichment_status: string | null;
  last_enriched_at: string | null;
}

interface FoilLatestRow {
  agency: string | null;
  received_date: string | null;
  created_at: string | null;
}

interface FoilSummary {
  total: number;
  recent: number;
  uniqueAgencies: number;
  latestAgency: string | null;
  latestDate: string | null;
}

type FetchState = 'idle' | 'loading' | 'error' | 'ready';

const ACTIVE_WORKFLOW_STATUSES = new Set(['queued', 'in_progress', 'researching']);
const RECENT_WINDOW_DAYS = 7;
const RECENT_FOIL_DAYS = 30;

const OverviewPage: React.FC = () => {
  const [rows, setRows] = useState<SnapshotRow[]>([]);
  const [collectabilityState, setCollectabilityState] = useState<FetchState>('idle');
  const [collectabilityError, setCollectabilityError] = useState<PostgrestError | Error | null>(null);

  const [foilSummary, setFoilSummary] = useState<FoilSummary | null>(null);
  const [foilState, setFoilState] = useState<FetchState>('idle');
  const [foilError, setFoilError] = useState<PostgrestError | Error | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCollectability() {
      setCollectabilityState('loading');
      setCollectabilityError(null);

      try {
        const snapshotResponse = await supabaseClient
          .from('v_collectability_snapshot')
          .select(
            'case_id, case_number, judgment_amount, age_days, collectability_tier, last_enrichment_status, last_enriched_at'
          );

        if (cancelled) {
          return;
        }

        if (snapshotResponse.error) {
          setCollectabilityError(snapshotResponse.error);
          setCollectabilityState('error');
          return;
        }

        const snapshotRows = (snapshotResponse.data ?? []) as SnapshotRow[];
        setRows(snapshotRows);
        setCollectabilityState('ready');
      } catch (exc) {
        if (cancelled) {
          return;
        }
        setCollectabilityError(exc instanceof Error ? exc : new Error('Unknown error fetching collectability data.'));
        setCollectabilityState('error');
      }
    }

    async function loadFoil() {
      setFoilState('loading');
      setFoilError(null);

      try {
        const cutoffDate = new Date(Date.now() - RECENT_FOIL_DAYS * 24 * 60 * 60 * 1000)
          .toISOString()
          .slice(0, 10);

        const [totalFoilResponse, recentFoilResponse, latestFoilResponse, agencyResponse] = await Promise.all([
          supabaseClient.from('foil_responses').select('id', { count: 'exact', head: true }),
          supabaseClient
            .from('foil_responses')
            .select('id', { count: 'exact', head: true })
            .gte('received_date', cutoffDate),
          supabaseClient
            .from('foil_responses')
            .select('agency, received_date, created_at')
            .order('received_date', { ascending: false })
            .order('created_at', { ascending: false })
            .limit(1),
          supabaseClient.from('foil_responses').select('agency').not('agency', 'is', null),
        ]);

        if (cancelled) {
          return;
        }

        const combinedError =
          totalFoilResponse.error ??
          recentFoilResponse.error ??
          latestFoilResponse.error ??
          agencyResponse.error ??
          null;

        if (combinedError) {
          setFoilError(combinedError);
          setFoilState('error');
          return;
        }

        const latest = ((latestFoilResponse.data ?? []) as FoilLatestRow[])[0];
        const agencies = ((agencyResponse.data ?? []) as { agency: string | null }[])
          .map((row) => row.agency?.trim() ?? '')
          .filter((value) => value.length > 0);
        const uniqueAgencies = new Set(agencies).size;

        setFoilSummary({
          total: totalFoilResponse.count ?? 0,
          recent: recentFoilResponse.count ?? 0,
          uniqueAgencies,
          latestAgency: latest?.agency ?? null,
          latestDate: latest?.received_date ?? latest?.created_at ?? null,
        });
        setFoilState('ready');
      } catch (exc) {
        if (cancelled) {
          return;
        }
        setFoilError(exc instanceof Error ? exc : new Error('Unknown error fetching FOIL metrics.'));
        setFoilState('error');
      }
    }

    loadCollectability();
    loadFoil();

    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = useMemo(() => {
    const base = {
      casesInPipeline: 0,
      activeWorkflows: 0,
      recentEnrichments: 0,
      tierCounts: { A: 0, B: 0, C: 0 } as Record<CollectabilityTier, number>,
      lastRefresh: null as Date | null,
    };

    if (rows.length === 0) {
      return base;
    }

    const now = Date.now();
    const recentCutoff = now - RECENT_WINDOW_DAYS * 24 * 60 * 60 * 1000;

    let newest = 0;

    for (const row of rows) {
      base.casesInPipeline += 1;
      base.tierCounts[row.collectability_tier] += 1;

      if (row.last_enrichment_status && ACTIVE_WORKFLOW_STATUSES.has(row.last_enrichment_status)) {
        base.activeWorkflows += 1;
      }

      if (row.last_enriched_at) {
        const timestamp = Date.parse(row.last_enriched_at);
        if (!Number.isNaN(timestamp)) {
          if (timestamp >= recentCutoff) {
            base.recentEnrichments += 1;
          }
          if (timestamp > newest) {
            newest = timestamp;
          }
        }
      }
    }

    base.lastRefresh = newest ? new Date(newest) : null;
    return base;
  }, [rows]);

  const collectabilityLoading = collectabilityState === 'idle' || collectabilityState === 'loading';
  const foilLoading = foilState === 'idle' || foilState === 'loading';

  const nextActions = useMemo(() => {
    if (collectabilityLoading) {
      return [];
    }

    const now = Date.now();
    const recentCutoff = now - RECENT_WINDOW_DAYS * 24 * 60 * 60 * 1000;

    return rows
      .filter((row) => row.collectability_tier === 'A' || row.collectability_tier === 'B')
      .filter((row) => {
        if (!row.last_enriched_at) {
          return true;
        }
        const timestamp = Date.parse(row.last_enriched_at);
        if (Number.isNaN(timestamp)) {
          return true;
        }
        return timestamp < recentCutoff;
      })
      .sort((a, b) => {
        const amountA = typeof a.judgment_amount === 'number' ? a.judgment_amount : -Infinity;
        const amountB = typeof b.judgment_amount === 'number' ? b.judgment_amount : -Infinity;
        if (amountA !== amountB) {
          return amountB - amountA;
        }
        return (a.case_number ?? '').localeCompare(b.case_number ?? '');
      })
      .slice(0, 10);
  }, [collectabilityLoading, rows]);

  const metricCards = [
    {
      key: 'cases',
      label: 'Total judgments',
      value: metrics.casesInPipeline,
      description: 'All the judgments we\'re currently working on.',
    },
    {
      key: 'active',
      label: 'Being researched',
      value: metrics.activeWorkflows,
      description: 'Cases where we\'re actively gathering information right now.',
    },
    {
      key: 'recent',
      label: 'Updated this week',
      value: metrics.recentEnrichments,
      description: `Cases with new information added in the last ${RECENT_WINDOW_DAYS} days.`,
    },
  ];

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Today's Snapshot</h2>
        <p className="mt-2 text-sm text-slate-600">
          Here's the big picture of all the judgments we're tracking. Check these numbers each morning to see what's happening across the portfolio.
        </p>
        {!collectabilityLoading && metrics.lastRefresh && (
          <p className="mt-4 text-xs font-medium uppercase tracking-wide text-slate-400">
            Last enrichment recorded&nbsp;
            {metrics.lastRefresh.toLocaleString()}
          </p>
        )}
      </section>

      {!collectabilityLoading && !collectabilityError && rows.length === 0 && (
        <ZeroStateCard
          title="No judgments yet"
          description="Once cases are imported into the system, you'll see them here. Check back soon or ask if you're expecting data."
          actionLink="/help"
          actionLabel="View the Help Guide"
        />
      )}

      <section className="grid gap-4 md:grid-cols-3">
        {collectabilityError ? (
          <div className="md:col-span-3">
            <StatusMessage message={collectabilityError.message} tone="error" />
          </div>
        ) : (
          metricCards.map((card) => (
            <MetricCard
              key={card.key}
              label={card.label}
              value={collectabilityLoading ? null : card.value}
              description={card.description}
            />
          ))
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Tier distribution
          <HelpTooltip text="We sort cases into A, B, and C tiers based on how likely they are to pay. A = best chances, B = worth pursuing, C = lower priority." />
        </h3>
        {collectabilityError ? (
          <div className="mt-3">
            <StatusMessage message={collectabilityError.message} tone="error" />
          </div>
        ) : collectabilityLoading ? (
          <p className="mt-3 text-sm text-slate-500">Loading tier metrics...</p>
        ) : (
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {(['A', 'B', 'C'] as CollectabilityTier[]).map((tier) => (
              <div
                key={tier}
                className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 text-sm text-slate-600 shadow-sm"
              >
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tier {tier}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">
                  {metrics.tierCounts[tier].toLocaleString()}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {tier === 'A' ? 'Best chances to collect — focus here first.' : tier === 'B' ? 'Good potential — worth following up.' : 'Lower priority — check periodically.'}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Public Records Activity
          <HelpTooltip text="When we request information from government agencies (like DMV or tax offices), their responses appear here. This helps us find assets to collect on." />
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Responses we've received back from government agencies.
        </p>
        {foilError ? (
          <div className="mt-3">
            <StatusMessage message={foilError.message} tone="error" />
          </div>
        ) : foilLoading ? (
          <p className="mt-3 text-sm text-slate-500">Loading FOIL metrics...</p>
        ) : (
          <div className="mt-4">
            {foilSummary ? (
              <FoilSummaryCard summary={foilSummary} />
            ) : (
              <StatusMessage message="No public records responses yet. These will appear as agencies reply to our requests." tone="neutral" />
            )}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Next actions
          <HelpTooltip text="These are your highest-priority cases that haven't been touched recently. Start here each morning — work from top to bottom." />
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Your top priority cases to work on today, sorted by dollar amount.
        </p>
        {collectabilityError ? (
          <div className="mt-3">
            <StatusMessage message={collectabilityError.message} tone="error" />
          </div>
        ) : collectabilityLoading ? (
          <p className="mt-3 text-sm text-slate-500">Evaluating enforcement priorities…</p>
        ) : nextActions.length === 0 ? (
          <div className="mt-4">
            <StatusMessage message="Great news — no urgent cases need attention right now. Check back tomorrow or review the Cases tab for the full list." tone="neutral" />
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm text-slate-700">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Case</th>
                    <th className="px-4 py-3">Tier</th>
                    <th className="px-4 py-3">Judgment</th>
                    <th className="px-4 py-3">Age (days)</th>
                    <th className="px-4 py-3">Last enrichment</th>
                  </tr>
                </thead>
                <tbody>
                  {nextActions.map((row) => {
                    const status = row.last_enrichment_status ?? '—';
                    const formattedDate = formatDateTime(row.last_enriched_at ?? null);
                    const statusDisplay = formattedDate === '—' ? status : `${status} · ${formattedDate}`;
                    return (
                      <tr key={row.case_id} className="border-t border-slate-100 bg-white">
                        <td className="px-4 py-3 text-sm text-slate-700">{row.case_number ?? '—'}</td>
                        <td className="px-4 py-3 text-sm font-semibold text-slate-700">Tier {row.collectability_tier}</td>
                        <td className="px-4 py-3 text-sm text-slate-700">
                          {formatCurrency(row.judgment_amount)}
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-700">{formatAgeDays(row.age_days)}</td>
                        <td className="px-4 py-3 text-sm text-slate-600">{statusDisplay}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

export default OverviewPage;

function MetricCard({
  label,
  value,
  description,
}: {
  label: string;
  value: number | null;
  description: string;
}) {
  return (
    <article className="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <p className="mt-2 text-sm text-slate-600">{description}</p>
      </div>
      <p className="mt-6 text-3xl font-semibold text-slate-900">{value === null ? '...' : value.toLocaleString()}</p>
    </article>
  );
}

function StatusMessage({ message, tone }: { message: string; tone: 'neutral' | 'error' }) {
  if (tone === 'error') {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 shadow-sm">
        {message}
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-center text-sm text-slate-600 shadow-sm">
      {message}
    </div>
  );
}

const foilDateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function formatFoilDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return foilDateFormatter.format(parsed);
}

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

function formatCurrency(value: number | null): string {
  if (typeof value !== 'number') {
    return '—';
  }
  return currencyFormatter.format(value);
}

function formatAgeDays(value: number | null): string {
  if (typeof value !== 'number') {
    return '—';
  }
  return value.toLocaleString();
}

function FoilSummaryCard({ summary }: { summary: FoilSummary }) {
  const items = [
    {
      label: `FOIL responses in last ${RECENT_FOIL_DAYS} days`,
      value: summary.recent.toLocaleString(),
    },
    {
      label: 'Unique agencies',
      value: summary.uniqueAgencies.toLocaleString(),
    },
    {
      label: 'Most recent disclosure date',
      value: formatFoilDate(summary.latestDate),
    },
  ];

  return (
    <article className="rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">FOIL overview</p>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Total responses {summary.total.toLocaleString()}
        </p>
      </div>
      <dl className="mt-4 grid gap-3 text-sm text-slate-600">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 shadow-sm">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.label}</dt>
            <dd className="mt-1 text-base font-semibold text-slate-900">{item.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-xs text-slate-500">
        Latest agency response: {summary.latestAgency?.trim() || '—'}
      </p>
    </article>
  );
}
