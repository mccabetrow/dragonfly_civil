/**
 * PortfolioDonutChart - Tremor DonutChart for portfolio composition
 *
 * Shows enforcement method distribution with:
 * - Wage Garnishments vs Bank Levies vs Other
 * - Interactive legend
 * - Center label with total
 * - Hover effects with Tremor styling
 *
 * Theme: Dragonfly Civil
 * - Deep blue: #0f172a
 * - Emerald accent: #10b981
 * - Steel gray: #f1f5f9
 */
import { type FC, useMemo } from 'react';
import { Card, DonutChart, Title, Text, Legend } from '@tremor/react';
import { cn } from '../../lib/design-tokens';

export interface PortfolioSegment {
  name: string;
  value: number;
  color?: string;
}

export interface PortfolioDonutChartProps {
  data: PortfolioSegment[];
  title?: string;
  subtitle?: string;
  loading?: boolean;
  className?: string;
  centerLabel?: string;
  centerValue?: string | number;
  /** Color palette for segments - maps to Tremor color names */
  colors?: string[];
}

const formatCurrency = (value: number): string => {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toLocaleString()}`;
};

export const PortfolioDonutChart: FC<PortfolioDonutChartProps> = ({
  data,
  title = 'Portfolio Composition',
  subtitle,
  loading = false,
  className,
  centerLabel,
  centerValue,
  colors = ['emerald', 'cyan', 'indigo', 'violet', 'fuchsia'],
}) => {
  const total = useMemo(() => data.reduce((sum, d) => sum + d.value, 0), [data]);
  const categories = useMemo(() => data.map((d) => d.name), [data]);

  if (loading) {
    return (
      <Card className={cn('animate-pulse', className)}>
        <div className="mb-4 h-6 w-40 rounded bg-slate-100" />
        <div className="flex items-center justify-center">
          <div className="h-48 w-48 rounded-full bg-slate-50" />
        </div>
      </Card>
    );
  }

  return (
    <Card className={cn('bg-white', className)}>
      {/* Header */}
      <div className="mb-4">
        <Title className="text-dragonfly-deep">{title}</Title>
        {subtitle && (
          <Text className="mt-1 text-slate-500">{subtitle}</Text>
        )}
      </div>

      {/* Tremor DonutChart with center label */}
      <DonutChart
        data={data}
        category="value"
        index="name"
        colors={colors}
        valueFormatter={formatCurrency}
        className="h-48"
        showAnimation
        showTooltip
        label={centerValue?.toString() ?? formatCurrency(total)}
        variant="donut"
      />

      {/* Legend */}
      <Legend
        categories={categories}
        colors={colors}
        className="mt-4 justify-center"
      />

      {/* Center label description */}
      {centerLabel && (
        <Text className="mt-2 text-center text-slate-500">{centerLabel}</Text>
      )}
    </Card>
  );
};

export default PortfolioDonutChart;
