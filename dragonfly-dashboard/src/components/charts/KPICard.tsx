/**
 * KPICard - Tremor-powered KPI metric card
 *
 * Displays a key performance indicator with:
 * - Title and value using Tremor Metric/Text
 * - Trend indicator using Tremor BadgeDelta
 * - Optional subtitle for context
 * - Skeleton loading state
 *
 * Dragonfly Theme:
 * - Deep blue (#0f172a) primary
 * - Emerald accents (#10b981)
 * - Steel gray backgrounds (#f1f5f9)
 */
import { type FC, type ReactNode } from 'react';
import {
  Card,
  Metric,
  Text,
  Flex,
  BadgeDelta,
  type DeltaType,
} from '@tremor/react';
import { cn } from '../../lib/design-tokens';

export interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: {
    value: number;
    label?: string;
  };
  icon?: ReactNode;
  loading?: boolean;
  className?: string;
  valueClassName?: string;
  /** Color accent: emerald (default), blue, indigo, violet */
  color?: 'emerald' | 'blue' | 'indigo' | 'violet';
}

export const KPICard: FC<KPICardProps> = ({
  title,
  value,
  subtitle,
  trend,
  icon,
  loading = false,
  className,
  valueClassName,
  color = 'emerald',
}) => {
  // Determine delta type for trend badge
  const deltaType: DeltaType = trend
    ? trend.value > 0
      ? 'increase'
      : trend.value < 0
        ? 'decrease'
        : 'unchanged'
    : 'unchanged';

  // Color mapping for decoration
  const colorClass = {
    emerald: 'from-emerald-500 to-teal-500',
    blue: 'from-blue-500 to-cyan-500',
    indigo: 'from-indigo-500 to-violet-500',
    violet: 'from-violet-500 to-purple-500',
  }[color];

  // Icon background color
  const iconBgClass = {
    emerald: 'bg-emerald-50 text-emerald-600',
    blue: 'bg-blue-50 text-blue-600',
    indigo: 'bg-indigo-50 text-indigo-600',
    violet: 'bg-violet-50 text-violet-600',
  }[color];

  if (loading) {
    return (
      <Card
        className={cn(
          'relative overflow-hidden',
          className
        )}
        decoration="left"
        decorationColor={color}
      >
        <div className="space-y-3">
          <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
          <div className="h-9 w-32 animate-pulse rounded-lg bg-slate-100" />
          <div className="h-3 w-40 animate-pulse rounded bg-slate-50" />
        </div>
      </Card>
    );
  }

  return (
    <Card
      className={cn(
        'relative overflow-hidden transition-shadow hover:shadow-md',
        className
      )}
      decoration="left"
      decorationColor={color}
    >
      {/* Header */}
      <Flex justifyContent="between" alignItems="start">
        <div className="flex items-center gap-2">
          {icon && (
            <div className={cn('flex h-8 w-8 items-center justify-center rounded-lg', iconBgClass)}>
              {icon}
            </div>
          )}
          <Text className="text-slate-500 font-medium">{title}</Text>
        </div>

        {trend && (
          <BadgeDelta deltaType={deltaType} size="sm">
            {Math.abs(trend.value).toFixed(1)}%
          </BadgeDelta>
        )}
      </Flex>

      {/* Value */}
      <Metric className={cn('mt-3 font-mono', valueClassName)}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </Metric>

      {/* Subtitle / Trend Label */}
      {(subtitle || trend?.label) && (
        <Text className="mt-1.5 text-slate-500">
          {trend?.label ?? subtitle}
        </Text>
      )}

      {/* Decorative gradient line */}
      <div className={cn(
        'absolute left-0 top-0 h-full w-1 bg-gradient-to-b',
        colorClass
      )} />
    </Card>
  );
};

export default KPICard;
