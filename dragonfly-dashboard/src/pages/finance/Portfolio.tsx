/**
 * Portfolio Page
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * CEO-facing portfolio page showing Assets Under Management (AUM) and
 * key financial metrics for investor presentations and strategic planning.
 *
 * Metrics:
 *   - Total AUM: Sum of all judgment amounts
 *   - Actionable Liquidity: Sum where collectability score > 40
 *   - Pipeline Value: Sum of BUY_CANDIDATE amounts
 *   - Offers Outstanding: Count of pending offers
 *
 * Charts:
 *   - Donut: Score tier allocation (A/B/C) by amount
 *   - Bar: Top 5 counties by judgment amount
 *
 * Route: /finance/portfolio
 */
import { type FC } from 'react';
import {
  Card,
  Title,
  Text,
  DonutChart,
  BarChart,
  Legend,
  Flex,
} from '@tremor/react';
import {
  DollarSign,
  TrendingUp,
  Target,
  FileText,
} from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { KPICard } from '../../components/charts/KPICard';
import { usePortfolioStats } from '../../hooks/usePortfolioStats';

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

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

const LoadingSkeleton: FC = () => (
  <div className="space-y-6">
    {/* KPI Cards Skeleton */}
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {[1, 2, 3, 4].map((i) => (
        <Card key={i} className="animate-pulse">
          <div className="space-y-3">
            <div className="h-4 w-24 rounded bg-slate-100" />
            <div className="h-9 w-32 rounded-lg bg-slate-100" />
            <div className="h-3 w-40 rounded bg-slate-50" />
          </div>
        </Card>
      ))}
    </div>
    {/* Charts Skeleton */}
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Card className="animate-pulse">
        <div className="h-64 rounded-lg bg-slate-100" />
      </Card>
      <Card className="animate-pulse">
        <div className="h-64 rounded-lg bg-slate-100" />
      </Card>
    </div>
  </div>
);

const ErrorState: FC<{ message: string; onRetry: () => void }> = ({
  message,
  onRetry,
}) => (
  <Card className="text-center py-12">
    <Text className="text-rose-600 mb-4">{message}</Text>
    <button
      onClick={onRetry}
      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
    >
      Retry
    </button>
  </Card>
);

// ═══════════════════════════════════════════════════════════════════════════
// PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const PortfolioPage: FC = () => {
  const { data, loading, error, refetch } = usePortfolioStats();

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Portfolio"
          subtitle="Assets Under Management & Financial Metrics"
        />
        <LoadingSkeleton />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Portfolio"
          subtitle="Assets Under Management & Financial Metrics"
        />
        <ErrorState message={error} onRetry={refetch} />
      </div>
    );
  }

  if (!data) {
    return null;
  }

  // Transform tier allocation for DonutChart
  const tierChartData = data.tierAllocation.map((tier) => ({
    name: tier.label,
    value: tier.amount,
    count: tier.count,
  }));

  // Transform county data for BarChart
  const countyChartData = data.topCounties.map((c) => ({
    county: c.county.replace(' County', ''),
    Amount: c.amount,
    count: c.count,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageHeader
        title="Portfolio"
        subtitle="Assets Under Management & Financial Metrics"
      />

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="kpi-grid">
        <KPICard
          title="Total AUM"
          value={formatCurrency(data.totalAum, true)}
          subtitle={`${formatNumber(data.totalJudgments)} judgments`}
          icon={<DollarSign className="h-5 w-5" />}
          color="emerald"
        />
        <KPICard
          title="Actionable Liquidity"
          value={formatCurrency(data.actionableLiquidity, true)}
          subtitle={`${formatNumber(data.actionableCount)} cases (score > 40)`}
          icon={<TrendingUp className="h-5 w-5" />}
          color="blue"
        />
        <KPICard
          title="Pipeline Value"
          value={formatCurrency(data.pipelineValue, true)}
          subtitle="Buy candidates"
          icon={<Target className="h-5 w-5" />}
          color="indigo"
        />
        <KPICard
          title="Offers Outstanding"
          value={formatNumber(data.offersOutstanding)}
          subtitle="Pending responses"
          icon={<FileText className="h-5 w-5" />}
          color="violet"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Score Tier Allocation Donut Chart */}
        <Card>
          <Title>Score Tier Allocation</Title>
          <Text className="text-slate-500 mb-4">
            Portfolio breakdown by collectability tier
          </Text>
          <DonutChart
            className="h-64"
            data={tierChartData}
            category="value"
            index="name"
            valueFormatter={(v) => formatCurrency(v, true)}
            colors={['emerald', 'blue', 'gray']}
            showLabel
            showAnimation
            data-testid="tier-donut-chart"
          />
          <Legend
            className="mt-4 justify-center"
            categories={tierChartData.map((t) => t.name)}
            colors={['emerald', 'blue', 'gray']}
          />
          <div className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
            {data.tierAllocation.map((tier) => (
              <div key={tier.tier}>
                <Text className="text-slate-500">{tier.tier}</Text>
                <Text className="font-medium">{formatNumber(tier.count)} cases</Text>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Counties Bar Chart */}
        <Card>
          <Title>Top 5 Counties</Title>
          <Text className="text-slate-500 mb-4">
            By total judgment amount
          </Text>
          <BarChart
            className="h-64"
            data={countyChartData}
            index="county"
            categories={['Amount']}
            colors={['blue']}
            valueFormatter={(v) => formatCurrency(v, true)}
            showLegend={false}
            showAnimation
            data-testid="county-bar-chart"
          />
          <div className="mt-4 space-y-2">
            {data.topCounties.slice(0, 3).map((c, idx) => (
              <Flex key={c.county} justifyContent="between">
                <Text className="text-slate-600">
                  {idx + 1}. {c.county}
                </Text>
                <Text className="font-medium">
                  {formatCurrency(c.amount, true)} ({formatNumber(c.count)} cases)
                </Text>
              </Flex>
            ))}
          </div>
        </Card>
      </div>

      {/* Summary Footer */}
      <Card className="bg-gradient-to-r from-slate-50 to-blue-50">
        <Flex justifyContent="between" alignItems="center">
          <div>
            <Title className="text-slate-900">Portfolio Summary</Title>
            <Text className="text-slate-600">
              {formatNumber(data.actionableCount)} of {formatNumber(data.totalJudgments)} judgments 
              ({((data.actionableCount / data.totalJudgments) * 100).toFixed(0)}%) 
              are actionable with collectability score above 40.
            </Text>
          </div>
          <div className="text-right">
            <Text className="text-sm text-slate-500">Actionable Ratio</Text>
            <Text className="text-2xl font-bold text-blue-600">
              {((data.actionableLiquidity / data.totalAum) * 100).toFixed(1)}%
            </Text>
          </div>
        </Flex>
      </Card>
    </div>
  );
};

export default PortfolioPage;
