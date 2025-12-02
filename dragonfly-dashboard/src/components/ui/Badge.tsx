import { type FC, type ReactNode } from 'react';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// BADGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'tier-a' | 'tier-b' | 'tier-c';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-slate-100 text-slate-700 border-slate-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  error: 'bg-rose-50 text-rose-700 border-rose-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
  'tier-a': 'bg-emerald-50 text-emerald-700 border-emerald-200',
  'tier-b': 'bg-amber-50 text-amber-700 border-amber-200',
  'tier-c': 'bg-slate-100 text-slate-600 border-slate-200',
};

const dotColors: Record<BadgeVariant, string> = {
  default: 'bg-slate-400',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  error: 'bg-rose-500',
  info: 'bg-blue-500',
  'tier-a': 'bg-emerald-500',
  'tier-b': 'bg-amber-500',
  'tier-c': 'bg-slate-400',
};

const sizeClasses: Record<BadgeSize, string> = {
  sm: 'text-[10px] px-2 py-0.5',
  md: 'text-xs px-2.5 py-0.5',
};

export const Badge: FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'md',
  dot = false,
  className,
}) => {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-semibold',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
    >
      {dot && (
        <span
          className={cn('h-1.5 w-1.5 rounded-full', dotColors[variant])}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// TIER BADGE (Convenience component)
// ═══════════════════════════════════════════════════════════════════════════

export interface TierBadgeProps {
  tier: 'A' | 'B' | 'C' | string;
  showDot?: boolean;
  size?: BadgeSize;
  className?: string;
}

export const TierBadge: FC<TierBadgeProps> = ({
  tier,
  showDot = true,
  size = 'md',
  className,
}) => {
  const normalized = tier.toUpperCase();
  const variant: BadgeVariant =
    normalized === 'A' ? 'tier-a' : normalized === 'B' ? 'tier-b' : 'tier-c';

  return (
    <Badge variant={variant} size={size} dot={showDot} className={className}>
      Tier {normalized}
    </Badge>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// STATUS BADGE
// ═══════════════════════════════════════════════════════════════════════════

export interface StatusBadgeProps {
  status: 'active' | 'pending' | 'completed' | 'failed' | 'idle';
  label?: string;
  size?: BadgeSize;
  className?: string;
}

const statusVariants: Record<StatusBadgeProps['status'], BadgeVariant> = {
  active: 'info',
  pending: 'warning',
  completed: 'success',
  failed: 'error',
  idle: 'default',
};

const statusLabels: Record<StatusBadgeProps['status'], string> = {
  active: 'Active',
  pending: 'Pending',
  completed: 'Completed',
  failed: 'Failed',
  idle: 'Idle',
};

export const StatusBadge: FC<StatusBadgeProps> = ({
  status,
  label,
  size = 'md',
  className,
}) => {
  return (
    <Badge variant={statusVariants[status]} size={size} dot className={className}>
      {label ?? statusLabels[status]}
    </Badge>
  );
};

export default Badge;
