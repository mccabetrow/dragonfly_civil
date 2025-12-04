/**
 * RecoveryAreaChart - Tremor AreaChart for recovery velocity
 *
 * Shows dollars collected over time with:
 * - Gradient fill area
 * - Interactive tooltips
 * - Responsive sizing
 * - Animated transitions
 *
 * Theme: Dragonfly Civil
 * - Deep blue: #0f172a
 * - Emerald accent: #10b981
 * - Steel gray: #f1f5f9
 */
import { type FC, useMemo } from 'react';
import { Card, AreaChart, Title, Text, Legend } from '@tremor/react';
import { cn } from '../../lib/design-tokens';

export interface RecoveryDataPoint {
  date: string;
  label?: string;
  collected: number;
  projected?: number;
}

export interface RecoveryAreaChartProps {
  data: RecoveryDataPoint[];
  title?: string;
  subtitle?: string;
  loading?: boolean;
  className?: string;
  height?: string;
  showProjected?: boolean;
  /** Color palette - maps to Tremor color names */
  colors?: string[];
}

const formatCurrency = (value: number): string => {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toLocaleString()}`;
};

export const RecoveryAreaChart: FC<RecoveryAreaChartProps> = ({
  data,
  title = 'Recovery Velocity',
  subtitle,
  loading = false,
  className,
  height = 'h-72',
  showProjected = false,
  colors = ['emerald', 'violet'],
}) => {
  // Calculate totals for subtitle
  const totalCollected = useMemo(
    () => data.reduce((sum, d) => sum + d.collected, 0),
    [data]
  );

  // Determine which categories to display
  const categories = useMemo(() => {
    const cats = ['collected'];
    if (showProjected) cats.push('projected');
    return cats;
  }, [showProjected]);

  if (loading) {
    return (
      <Card className={cn('animate-pulse', className)}>
        <div className="mb-4 h-6 w-40 rounded bg-slate-100" />
        <div className="h-72 rounded-lg bg-slate-50" />
      </Card>
    );
  }

  return (
    <Card className={cn('bg-white', className)}>
      {/* Header */}
      <div className="mb-4">
        <Title className="text-dragonfly-deep">{title}</Title>
        <Text className="mt-1 text-slate-500">
          {subtitle ?? `Total: ${formatCurrency(totalCollected)}`}
        </Text>
      </div>

      {/* Tremor AreaChart */}
      <AreaChart
        data={data}
        index="label"
        categories={categories}
        colors={colors}
        valueFormatter={formatCurrency}
        className={height}
        showAnimation
        showLegend={false}
        showGridLines
        curveType="monotone"
        yAxisWidth={65}
      />

      {/* Legend */}
      <Legend
        categories={showProjected ? ['Collected', 'Projected'] : ['Collected']}
        colors={showProjected ? colors : [colors[0]]}
        className="mt-4 justify-center"
      />
    </Card>
  );
};

export default RecoveryAreaChart;
