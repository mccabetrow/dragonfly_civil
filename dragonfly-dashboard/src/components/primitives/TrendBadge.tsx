/**
 * TrendBadge Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Displays a trend indicator with percentage change and direction.
 * Bloomberg-style financial trend visualization.
 */

import * as React from 'react';
import { cn } from '../../lib/tokens';
import { TrendingUp, TrendingDown, Minus, ArrowUpRight, ArrowDownRight } from 'lucide-react';

export type TrendDirection = 'up' | 'down' | 'flat';

export interface TrendBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** The trend value (percentage) */
  value: number;
  /** Override automatic direction detection */
  direction?: TrendDirection;
  /** Show the actual value or just the direction */
  showValue?: boolean;
  /** Icon style */
  iconStyle?: 'trending' | 'arrow';
  /** Badge size */
  size?: 'sm' | 'md' | 'lg';
  /** Whether higher is better (default: true for positive = green) */
  positiveIsGood?: boolean;
}

const sizeClasses = {
  sm: {
    badge: 'text-xs gap-0.5',
    icon: 'h-3 w-3',
  },
  md: {
    badge: 'text-sm gap-1',
    icon: 'h-3.5 w-3.5',
  },
  lg: {
    badge: 'text-base gap-1',
    icon: 'h-4 w-4',
  },
};

export const TrendBadge = React.forwardRef<HTMLSpanElement, TrendBadgeProps>(
  ({ 
    value, 
    direction: directionOverride, 
    showValue = true, 
    iconStyle = 'trending',
    size = 'md',
    positiveIsGood = true,
    className, 
    ...props 
  }, ref) => {
    // Determine direction
    const direction: TrendDirection = directionOverride ?? (
      value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
    );

    // Color logic: if positiveIsGood, up = green, down = red; else inverse
    const isPositive = direction === 'up';
    const isGood = positiveIsGood ? isPositive : !isPositive;

    const colorClasses = direction === 'flat'
      ? 'text-slate-500'
      : isGood
      ? 'text-emerald-600'
      : 'text-red-600';

    // Icon selection
    const Icon = direction === 'flat'
      ? Minus
      : iconStyle === 'arrow'
      ? (direction === 'up' ? ArrowUpRight : ArrowDownRight)
      : (direction === 'up' ? TrendingUp : TrendingDown);

    const sizeConfig = sizeClasses[size];

    // Format value
    const displayValue = Math.abs(value).toFixed(1);
    const sign = value > 0 ? '+' : value < 0 ? '' : '';

    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center font-medium',
          colorClasses,
          sizeConfig.badge,
          className
        )}
        {...props}
      >
        <Icon className={sizeConfig.icon} />
        {showValue && (
          <span>
            {sign}{displayValue}%
          </span>
        )}
      </span>
    );
  }
);
TrendBadge.displayName = 'TrendBadge';

/**
 * TrendIndicator - Minimal trend arrow for data tables
 */
export interface TrendIndicatorProps extends React.HTMLAttributes<HTMLSpanElement> {
  direction: TrendDirection;
  size?: 'sm' | 'md';
}

export const TrendIndicator = React.forwardRef<HTMLSpanElement, TrendIndicatorProps>(
  ({ direction, size = 'sm', className, ...props }, ref) => {
    const Icon = direction === 'flat'
      ? Minus
      : direction === 'up'
      ? TrendingUp
      : TrendingDown;

    const colorClass = direction === 'flat'
      ? 'text-slate-400'
      : direction === 'up'
      ? 'text-emerald-500'
      : 'text-red-500';

    const iconSize = size === 'sm' ? 'h-3 w-3' : 'h-4 w-4';

    return (
      <span
        ref={ref}
        className={cn('inline-flex', colorClass, className)}
        {...props}
      >
        <Icon className={iconSize} />
      </span>
    );
  }
);
TrendIndicator.displayName = 'TrendIndicator';
