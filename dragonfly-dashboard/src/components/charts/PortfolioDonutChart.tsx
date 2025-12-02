/**
 * PortfolioDonutChart - Tremor-style donut chart for portfolio composition
 *
 * Shows enforcement method distribution with:
 * - Wage Garnishments vs Bank Levies vs Other
 * - Interactive legend
 * - Center label with total
 * - Hover effects
 */
import { type FC, useState, useMemo } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';
import { cn } from '../../lib/design-tokens';

export interface PortfolioSegment {
  name: string;
  value: number;
  color: string;
  [key: string]: string | number; // Index signature for Recharts compatibility
}

export interface PortfolioDonutChartProps {
  data: PortfolioSegment[];
  title?: string;
  subtitle?: string;
  loading?: boolean;
  className?: string;
  centerLabel?: string;
  centerValue?: string | number;
}

const formatCurrency = (value: number): string => {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toLocaleString()}`;
};

const formatPercent = (value: number, total: number): string => {
  if (total === 0) return '0%';
  return `${((value / total) * 100).toFixed(1)}%`;
};

export const PortfolioDonutChart: FC<PortfolioDonutChartProps> = ({
  data,
  title = 'Portfolio Composition',
  subtitle,
  loading = false,
  className,
  centerLabel,
  centerValue,
}) => {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const total = useMemo(() => data.reduce((sum, d) => sum + d.value, 0), [data]);

  const onPieEnter = (_: any, index: number) => {
    setActiveIndex(index);
  };

  const onPieLeave = () => {
    setActiveIndex(null);
  };

  if (loading) {
    return (
      <div className={cn('rounded-xl border border-slate-200 bg-white p-5', className)}>
        <div className="mb-4 h-6 w-40 animate-pulse rounded bg-slate-100" />
        <div className="flex items-center justify-center">
          <div className="h-48 w-48 animate-pulse rounded-full bg-slate-50" />
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'rounded-xl border border-slate-200 bg-white p-5 shadow-sm',
        className
      )}
    >
      {/* Header */}
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>

      {/* Chart + Legend Container */}
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start sm:justify-between">
        {/* Donut Chart */}
        <div className="relative h-48 w-48 flex-shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={activeIndex !== null ? 85 : 80}
                paddingAngle={2}
                dataKey="value"
                onMouseEnter={onPieEnter}
                onMouseLeave={onPieLeave}
                animationDuration={800}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.color}
                    className="outline-none transition-all duration-200"
                    style={{
                      opacity: activeIndex === null || activeIndex === index ? 1 : 0.5,
                      transform: activeIndex === index ? 'scale(1.05)' : 'scale(1)',
                      transformOrigin: 'center',
                    }}
                  />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>

          {/* Center Label */}
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <p className="font-mono text-xl font-semibold text-slate-900">
              {centerValue ?? formatCurrency(total)}
            </p>
            <p className="text-xs text-slate-500">{centerLabel ?? 'Total'}</p>
          </div>
        </div>

        {/* Legend */}
        <div className="flex flex-1 flex-col gap-2">
          {data.map((segment, index) => (
            <div
              key={segment.name}
              className={cn(
                'flex items-center justify-between rounded-lg px-3 py-2 transition-colors',
                activeIndex === index ? 'bg-slate-50' : 'hover:bg-slate-50/50'
              )}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseLeave={() => setActiveIndex(null)}
            >
              <div className="flex items-center gap-2">
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: segment.color }}
                />
                <span className="text-sm text-slate-700">{segment.name}</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="font-mono font-medium text-slate-900">
                  {formatCurrency(segment.value)}
                </span>
                <span className="w-12 text-right text-slate-500">
                  {formatPercent(segment.value, total)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default PortfolioDonutChart;
