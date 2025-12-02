/**
 * TierBadge Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Collectability tier badge with distinctive visual treatment per tier.
 * 
 * - Tier A: Emerald flame – high priority, hot
 * - Tier B: Amber clock – moderate priority, nurture
 * - Tier C: Slate minus – low priority, archive
 */

import * as React from 'react';
import { cn } from '../../lib/tokens';
import { Flame, Clock, Minus, AlertTriangle } from 'lucide-react';

export type TierLevel = 'A' | 'B' | 'C' | 'UNSCORED';

export interface TierBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tier: TierLevel;
  /** Show the tier icon */
  showIcon?: boolean;
  /** Badge size */
  size?: 'sm' | 'md' | 'lg';
  /** Show only the icon, no text */
  iconOnly?: boolean;
}

const tierConfig: Record<TierLevel, {
  label: string;
  icon: typeof Flame;
  bgClass: string;
  textClass: string;
  ringClass: string;
  description: string;
}> = {
  A: {
    label: 'Tier A',
    icon: Flame,
    bgClass: 'bg-emerald-50',
    textClass: 'text-emerald-700',
    ringClass: 'ring-emerald-500/20',
    description: 'High Priority',
  },
  B: {
    label: 'Tier B',
    icon: Clock,
    bgClass: 'bg-amber-50',
    textClass: 'text-amber-700',
    ringClass: 'ring-amber-500/20',
    description: 'Moderate Priority',
  },
  C: {
    label: 'Tier C',
    icon: Minus,
    bgClass: 'bg-slate-100',
    textClass: 'text-slate-600',
    ringClass: 'ring-slate-500/20',
    description: 'Low Priority',
  },
  UNSCORED: {
    label: 'Unscored',
    icon: AlertTriangle,
    bgClass: 'bg-slate-50',
    textClass: 'text-slate-500',
    ringClass: 'ring-slate-400/20',
    description: 'Pending Scoring',
  },
};

const sizeClasses = {
  sm: {
    badge: 'px-1.5 py-0.5 text-xs gap-0.5',
    icon: 'h-3 w-3',
  },
  md: {
    badge: 'px-2 py-1 text-xs gap-1',
    icon: 'h-3.5 w-3.5',
  },
  lg: {
    badge: 'px-2.5 py-1.5 text-sm gap-1.5',
    icon: 'h-4 w-4',
  },
};

export const TierBadge = React.forwardRef<HTMLSpanElement, TierBadgeProps>(
  ({ tier, showIcon = true, size = 'md', iconOnly = false, className, ...props }, ref) => {
    const config = tierConfig[tier];
    const sizeConfig = sizeClasses[size];
    const Icon = config.icon;

    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center font-medium rounded-md ring-1 ring-inset transition-colors',
          config.bgClass,
          config.textClass,
          config.ringClass,
          sizeConfig.badge,
          className
        )}
        title={config.description}
        {...props}
      >
        {showIcon && <Icon className={cn(sizeConfig.icon, tier === 'A' && 'animate-pulse')} />}
        {!iconOnly && <span>{config.label}</span>}
      </span>
    );
  }
);
TierBadge.displayName = 'TierBadge';

/**
 * TierDot - Minimal tier indicator for tight spaces
 */
export interface TierDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  tier: TierLevel;
  size?: 'sm' | 'md';
  pulse?: boolean;
}

const dotSizes = {
  sm: 'h-2 w-2',
  md: 'h-2.5 w-2.5',
};

const dotColors: Record<TierLevel, string> = {
  A: 'bg-emerald-500',
  B: 'bg-amber-500',
  C: 'bg-slate-400',
  UNSCORED: 'bg-slate-300',
};

export const TierDot = React.forwardRef<HTMLSpanElement, TierDotProps>(
  ({ tier, size = 'md', pulse = false, className, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={cn(
          'inline-block rounded-full',
          dotSizes[size],
          dotColors[tier],
          pulse && tier === 'A' && 'animate-pulse',
          className
        )}
        title={tierConfig[tier].description}
        {...props}
      />
    );
  }
);
TierDot.displayName = 'TierDot';
