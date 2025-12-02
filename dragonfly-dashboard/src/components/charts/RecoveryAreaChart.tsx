/**
 * RecoveryAreaChart - Tremor-style area chart for recovery velocity
 *
 * Shows dollars collected over time with:
 * - Gradient fill area
 * - Interactive tooltips
 * - Responsive sizing
 * - Animated transitions
 */
import { type FC, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
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
  height?: number;
  showProjected?: boolean;
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
  height = 280,
  showProjected = false,
}) => {
  // Calculate totals for subtitle
  const totalCollected = useMemo(
    () => data.reduce((sum, d) => sum + d.collected, 0),
    [data]
  );

  if (loading) {
    return (
      <div className={cn('rounded-xl border border-slate-200 bg-white p-5', className)}>
        <div className="mb-4 h-6 w-40 animate-pulse rounded bg-slate-100" />
        <div className="h-[280px] animate-pulse rounded-lg bg-slate-50" />
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
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            {subtitle ?? `Total: ${formatCurrency(totalCollected)}`}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-indigo-500" />
            <span className="text-slate-600">Collected</span>
          </div>
          {showProjected && (
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-violet-300" />
              <span className="text-slate-600">Projected</span>
            </div>
          )}
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart
          data={data}
          margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
        >
          <defs>
            <linearGradient id="colorCollected" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="colorProjected" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#a78bfa" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#a78bfa" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#e2e8f0"
            vertical={false}
          />
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 11, fill: '#64748b' }}
            dy={10}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 11, fill: '#64748b' }}
            tickFormatter={formatCurrency}
            dx={-5}
            width={60}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'white',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
              fontSize: '12px',
              fontFamily: 'Inter, system-ui, sans-serif',
            }}
            formatter={(value: number, name: string) => [
              formatCurrency(value),
              name === 'collected' ? 'Collected' : 'Projected',
            ]}
            labelFormatter={(label) => `Week: ${label}`}
          />
          <Area
            type="monotone"
            dataKey="collected"
            stroke="#6366f1"
            strokeWidth={2}
            fill="url(#colorCollected)"
            animationDuration={1000}
          />
          {showProjected && (
            <Area
              type="monotone"
              dataKey="projected"
              stroke="#a78bfa"
              strokeWidth={2}
              strokeDasharray="4 4"
              fill="url(#colorProjected)"
              animationDuration={1000}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

export default RecoveryAreaChart;
