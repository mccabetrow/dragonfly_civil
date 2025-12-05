/**
 * CeoOverviewPage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Executive overview page for CEO and investor presentations.
 * Shows portfolio KPIs, offer performance, system health, and recent activity.
 *
 * Route: /ceo/overview
 */
import { type FC, useMemo } from 'react';
import {
  Card,
  Title,
  Text,
  Metric,
  Flex,
  ProgressBar,
  Badge,
  AreaChart,
  DonutChart,
  Legend,
} from '@tremor/react';
import {
  Briefcase,
  TrendingUp,
  CheckCircle,
  XCircle,
  Activity,
  Shield,
  AlertTriangle,
  Clock,
  DollarSign,
  Target,
  BarChart3,
  Zap,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import { KPICard } from '../components/charts/KPICard';
import { useCeoOverviewStats } from '../hooks/useCeoOverviewStats';
import { useRecentEvents, type EventType } from '../hooks/useRecentEvents';
import { useOfferStats } from '../hooks/useOfferStats';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// FORMATTERS
// ═══════════════════════════════════════════════════════════════════════════

const formatCurrency = (value: number, compact = false): string => {
  if (compact) {
    if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
};

const formatNumber = (value: number): string => {
  return new Intl.NumberFormat('en-US').format(value);
};

const formatPercent = (value: number): string => {
  return `${value.toFixed(1)}%`;
};

const timeAgo = (timestamp: string): string => {
  const now = new Date();
  const then = new Date(timestamp);
  const diffMs = now.getTime() - then.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
};

// ═══════════════════════════════════════════════════════════════════════════
// EVENT ICONS
// ═══════════════════════════════════════════════════════════════════════════

const EVENT_ICONS: Record<EventType, FC<{ className?: string }>> = {
  judgment_created: Briefcase,
  judgment_enriched: Zap,
  offer_created: DollarSign,
  offer_accepted: CheckCircle,
  offer_rejected: XCircle,
  batch_ingested: BarChart3,
  entity_linked: Target,
  score_updated: TrendingUp,
  packet_generated: Briefcase,
  system_alert: AlertTriangle,
  unknown: Activity,
};

const EVENT_COLORS: Record<EventType, string> = {
  judgment_created: 'bg-blue-500',
  judgment_enriched: 'bg-indigo-500',
  offer_created: 'bg-amber-500',
  offer_accepted: 'bg-emerald-500',
  offer_rejected: 'bg-rose-500',
  batch_ingested: 'bg-cyan-500',
  entity_linked: 'bg-violet-500',
  score_updated: 'bg-teal-500',
  packet_generated: 'bg-slate-500',
  system_alert: 'bg-orange-500',
  unknown: 'bg-slate-400',
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface SystemHealthBadgeProps {
  healthy: boolean;
  pendingJobs: number;
  failedJobs: number;
}

const SystemHealthBadge: FC<SystemHealthBadgeProps> = ({
  healthy,
  pendingJobs,
  failedJobs,
}) => {
  if (failedJobs > 0) {
    return (
      <Badge color="red" icon={AlertTriangle}>
        {failedJobs} Failed Jobs
      </Badge>
    );
  }
  if (pendingJobs > 50) {
    return (
      <Badge color="yellow" icon={Clock}>
        {pendingJobs} Pending
      </Badge>
    );
  }
  if (healthy) {
    return (
      <Badge color="emerald" icon={Shield}>
        All Systems Healthy
      </Badge>
    );
  }
  return (
    <Badge color="slate" icon={Activity}>
      Unknown
    </Badge>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// PAGE
// ═══════════════════════════════════════════════════════════════════════════

const CeoOverviewPage: FC = () => {
  const { data: stats, loading: statsLoading } = useCeoOverviewStats();
  const { data: events, loading: eventsLoading } = useRecentEvents(10);
  // offerStats available for future enhancements
  useOfferStats();

  // Portfolio composition chart data
  const portfolioData = useMemo(() => {
    if (!stats) return [];
    return [
      { name: 'Buy Candidates', value: stats.buyCandidateCount, color: 'emerald' },
      { name: 'Contingency', value: stats.contingencyCount, color: 'blue' },
      {
        name: 'Other',
        value: stats.totalJudgments - stats.buyCandidateCount - stats.contingencyCount,
        color: 'slate',
      },
    ].filter((d) => d.value > 0);
  }, [stats]);

  // Offer funnel data for donut chart (currently using inline rendering)
  // Reserved for future chart upgrades
  // const offerFunnelData = useMemo(() => {
  //   if (!stats) return [];
  //   return [
  //     { name: 'Accepted', value: stats.offersAccepted, color: 'emerald' },
  //     { name: 'Pending', value: stats.offersPending, color: 'amber' },
  //     { name: 'Rejected', value: stats.offersRejected, color: 'rose' },
  //   ].filter((d) => d.value > 0);
  // }, [stats]);

  // Mock trend data for area chart (would come from time-series view)
  const trendData = useMemo(() => {
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    return days.map((day) => ({
      day,
      offers: Math.floor(Math.random() * 10) + 5,
      accepted: Math.floor(Math.random() * 5) + 2,
    }));
  }, []);

  return (
    <div className="space-y-8">
      {/* Header */}
      <PageHeader
        title="CEO Overview"
        subtitle="Portfolio performance and system status at a glance"
      />

      {/* Top KPIs */}
      <section aria-label="Key Performance Indicators">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KPICard
            title="Judgments Under Management"
            value={stats ? formatNumber(stats.totalJudgments) : '—'}
            subtitle={stats ? formatCurrency(stats.totalJudgmentValue, true) : undefined}
            icon={<Briefcase className="h-5 w-5" />}
            loading={statsLoading}
            color="blue"
          />

          <KPICard
            title="Buy Candidates"
            value={stats ? formatNumber(stats.buyCandidateCount) : '—'}
            subtitle={stats ? formatCurrency(stats.buyCandidateValue, true) : undefined}
            trend={
              stats
                ? {
                    value: Math.round((stats.buyCandidateCount / Math.max(stats.totalJudgments, 1)) * 100),
                    label: 'of portfolio',
                  }
                : undefined
            }
            icon={<Target className="h-5 w-5" />}
            loading={statsLoading}
            color="emerald"
          />

          <KPICard
            title="Offers Accepted"
            value={stats ? formatNumber(stats.offersAccepted) : '—'}
            subtitle={
              stats
                ? `${formatPercent(stats.acceptanceRate)} acceptance rate`
                : undefined
            }
            trend={
              stats && stats.offersAccepted > 0
                ? {
                    value: stats.acceptanceRate > 50 ? 1 : -1,
                  }
                : undefined
            }
            icon={<CheckCircle className="h-5 w-5" />}
            loading={statsLoading}
            color="indigo"
          />

          <Card className="relative overflow-hidden">
            <Text className="text-tremor-default text-tremor-content dark:text-dark-tremor-content">
              System Health
            </Text>
            <div className="mt-2">
              {statsLoading ? (
                <div className="h-8 w-32 animate-pulse rounded bg-slate-100" />
              ) : stats ? (
                <div className="space-y-2">
                  <SystemHealthBadge
                    healthy={stats.systemHealthy}
                    pendingJobs={stats.pendingJobs}
                    failedJobs={stats.failedJobs}
                  />
                  <Text className="text-xs text-slate-500">
                    {stats.pendingJobs} pending · {stats.failedJobs} failed
                  </Text>
                </div>
              ) : (
                <Text className="text-slate-400">No data</Text>
              )}
            </div>
          </Card>
        </div>
      </section>

      {/* Middle Section - Charts */}
      <section aria-label="Performance Charts" className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Portfolio Composition */}
        <Card>
          <Title>Portfolio Composition</Title>
          <Text className="mt-1">Breakdown by offer strategy</Text>
          {statsLoading ? (
            <div className="mt-4 h-48 animate-pulse rounded-lg bg-slate-50" />
          ) : portfolioData.length > 0 ? (
            <>
              <DonutChart
                data={portfolioData}
                category="value"
                index="name"
                colors={['emerald', 'blue', 'slate']}
                className="mt-4 h-48"
                valueFormatter={(v) => formatNumber(v)}
                showAnimation
              />
              <Legend
                categories={portfolioData.map((d) => d.name)}
                colors={['emerald', 'blue', 'slate']}
                className="mt-4 justify-center"
              />
            </>
          ) : (
            <div className="mt-8 text-center text-sm text-slate-400">
              No portfolio data available
            </div>
          )}
        </Card>

        {/* Offer Performance */}
        <Card>
          <Title>Offer Performance (Last 7 Days)</Title>
          <Text className="mt-1">Daily offers and acceptances</Text>
          {statsLoading ? (
            <div className="mt-4 h-48 animate-pulse rounded-lg bg-slate-50" />
          ) : (
            <AreaChart
              data={trendData}
              index="day"
              categories={['offers', 'accepted']}
              colors={['blue', 'emerald']}
              className="mt-4 h-48"
              showAnimation
              showLegend={false}
            />
          )}
          <Flex className="mt-4" justifyContent="center">
            <Legend
              categories={['Offers Made', 'Accepted']}
              colors={['blue', 'emerald']}
            />
          </Flex>
        </Card>
      </section>

      {/* Offer Funnel & Value */}
      <section aria-label="Offer Metrics" className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Offer Funnel */}
        <Card>
          <Title>Offer Funnel</Title>
          <Text className="mt-1">{stats ? formatNumber(stats.totalOffers) : '—'} total offers</Text>
          <div className="mt-6 space-y-4">
            <div>
              <Flex>
                <Text>Accepted</Text>
                <Text>{stats ? formatNumber(stats.offersAccepted) : '—'}</Text>
              </Flex>
              <ProgressBar
                value={stats ? (stats.offersAccepted / Math.max(stats.totalOffers, 1)) * 100 : 0}
                color="emerald"
                className="mt-2"
              />
            </div>
            <div>
              <Flex>
                <Text>Pending</Text>
                <Text>{stats ? formatNumber(stats.offersPending) : '—'}</Text>
              </Flex>
              <ProgressBar
                value={stats ? (stats.offersPending / Math.max(stats.totalOffers, 1)) * 100 : 0}
                color="amber"
                className="mt-2"
              />
            </div>
            <div>
              <Flex>
                <Text>Rejected</Text>
                <Text>{stats ? formatNumber(stats.offersRejected) : '—'}</Text>
              </Flex>
              <ProgressBar
                value={stats ? (stats.offersRejected / Math.max(stats.totalOffers, 1)) * 100 : 0}
                color="rose"
                className="mt-2"
              />
            </div>
          </div>
        </Card>

        {/* Dollar Values */}
        <Card className="lg:col-span-2">
          <Title>Offer Value Summary</Title>
          <Text className="mt-1">Total amounts offered and accepted</Text>
          <div className="mt-6 grid grid-cols-2 gap-6">
            <div className="rounded-xl bg-slate-50 p-4">
              <Text className="text-xs uppercase tracking-wide text-slate-500">
                Total Offered
              </Text>
              <Metric className="mt-1">
                {stats ? formatCurrency(stats.totalOfferedAmount, true) : '—'}
              </Metric>
            </div>
            <div className="rounded-xl bg-emerald-50 p-4">
              <Text className="text-xs uppercase tracking-wide text-emerald-700">
                Total Accepted
              </Text>
              <Metric className="mt-1 text-emerald-700">
                {stats ? formatCurrency(stats.totalAcceptedAmount, true) : '—'}
              </Metric>
            </div>
          </div>
          {stats && stats.totalOfferedAmount > 0 && (
            <div className="mt-4">
              <Text className="text-sm text-slate-600">
                Capture Rate:{' '}
                <span className="font-semibold">
                  {formatPercent(
                    (stats.totalAcceptedAmount / stats.totalOfferedAmount) * 100
                  )}
                </span>{' '}
                of offered value accepted
              </Text>
            </div>
          )}
        </Card>
      </section>

      {/* Recent Activity Timeline */}
      <section aria-label="Recent Activity">
        <Card>
          <Flex justifyContent="between" alignItems="center">
            <div>
              <Title>Recent Activity</Title>
              <Text className="mt-1">Latest system events and updates</Text>
            </div>
            <Badge color="slate">{events.length} events</Badge>
          </Flex>

          <div className="mt-6 space-y-3">
            {eventsLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3"
                >
                  <div className="h-8 w-8 animate-pulse rounded-full bg-slate-200" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-32 animate-pulse rounded bg-slate-200" />
                    <div className="h-3 w-48 animate-pulse rounded bg-slate-100" />
                  </div>
                </div>
              ))
            ) : events.length > 0 ? (
              events.map((event) => {
                const Icon = EVENT_ICONS[event.eventType] ?? Activity;
                const bgColor = EVENT_COLORS[event.eventType] ?? 'bg-slate-400';

                return (
                  <div
                    key={event.id}
                    className="flex items-start gap-3 rounded-lg border border-slate-100 bg-white p-3 transition hover:border-slate-200 hover:bg-slate-50"
                  >
                    <span
                      className={cn(
                        'flex h-8 w-8 items-center justify-center rounded-full text-white',
                        bgColor
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </span>
                    <div className="flex-1">
                      <Flex justifyContent="between" alignItems="start">
                        <Text className="font-medium text-slate-900">
                          {event.label}
                        </Text>
                        <Text className="text-xs text-slate-400">
                          {timeAgo(event.timestamp)}
                        </Text>
                      </Flex>
                      <Text className="mt-0.5 text-sm text-slate-600">
                        {event.description}
                      </Text>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-8 text-center text-sm text-slate-400">
                No recent activity
              </div>
            )}
          </div>
        </Card>
      </section>

      {/* Footer - Last Updated */}
      {stats?.lastActivityAt && (
        <footer className="text-center text-xs text-slate-400">
          Last system activity: {timeAgo(stats.lastActivityAt)}
        </footer>
      )}
    </div>
  );
};

export default CeoOverviewPage;
