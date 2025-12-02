/**
 * ZeroState Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Empty state card for when there's no data to display.
 * Friendly, actionable, and on-brand.
 */

import * as React from 'react';
import { cn } from '../../lib/tokens';
import { 
  Inbox, 
  Search, 
  AlertCircle, 
  Loader2,
  CheckCircle2,
  FolderOpen
} from 'lucide-react';
import { Card } from './Card';
import { Button } from './Button';

export type ZeroStateVariant = 'empty' | 'search' | 'error' | 'loading' | 'success' | 'no-results';

export interface ZeroStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The type of empty state */
  variant?: ZeroStateVariant;
  /** Custom icon override */
  icon?: React.ReactNode;
  /** Title text */
  title: string;
  /** Description text */
  description?: string;
  /** Primary action */
  action?: {
    label: string;
    onClick: () => void;
  };
  /** Secondary action */
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };
  /** Size of the empty state */
  size?: 'sm' | 'md' | 'lg';
  /** Compact mode (inline) */
  compact?: boolean;
}

const variantIcons: Record<ZeroStateVariant, typeof Inbox> = {
  empty: Inbox,
  search: Search,
  error: AlertCircle,
  loading: Loader2,
  success: CheckCircle2,
  'no-results': FolderOpen,
};

const variantColors: Record<ZeroStateVariant, string> = {
  empty: 'text-slate-400 bg-slate-100',
  search: 'text-indigo-500 bg-indigo-50',
  error: 'text-red-500 bg-red-50',
  loading: 'text-indigo-500 bg-indigo-50',
  success: 'text-emerald-500 bg-emerald-50',
  'no-results': 'text-slate-400 bg-slate-100',
};

const sizeClasses = {
  sm: {
    container: 'py-8',
    icon: 'h-8 w-8',
    iconWrapper: 'h-14 w-14',
    title: 'text-sm',
    description: 'text-xs',
  },
  md: {
    container: 'py-12',
    icon: 'h-10 w-10',
    iconWrapper: 'h-16 w-16',
    title: 'text-base',
    description: 'text-sm',
  },
  lg: {
    container: 'py-16',
    icon: 'h-12 w-12',
    iconWrapper: 'h-20 w-20',
    title: 'text-lg',
    description: 'text-base',
  },
};

export const ZeroState = React.forwardRef<HTMLDivElement, ZeroStateProps>(
  ({ 
    variant = 'empty', 
    icon, 
    title, 
    description, 
    action, 
    secondaryAction,
    size = 'md',
    compact = false,
    className, 
    ...props 
  }, ref) => {
    const Icon = variantIcons[variant];
    const sizeConfig = sizeClasses[size];

    const content = (
      <div
        className={cn(
          'flex flex-col items-center justify-center text-center',
          !compact && sizeConfig.container,
          compact && 'py-4',
        )}
      >
        {/* Icon */}
        <div
          className={cn(
            'rounded-full flex items-center justify-center mb-4',
            variantColors[variant],
            sizeConfig.iconWrapper
          )}
        >
          {icon || (
            <Icon
              className={cn(
                sizeConfig.icon,
                variant === 'loading' && 'animate-spin'
              )}
            />
          )}
        </div>

        {/* Text */}
        <h3 className={cn('font-medium text-slate-900', sizeConfig.title)}>
          {title}
        </h3>
        {description && (
          <p className={cn('mt-1 text-slate-500 max-w-md', sizeConfig.description)}>
            {description}
          </p>
        )}

        {/* Actions */}
        {(action || secondaryAction) && (
          <div className="flex items-center gap-3 mt-5">
            {action && (
              <Button
                variant="primary"
                size={size === 'lg' ? 'md' : 'sm'}
                onClick={action.onClick}
              >
                {action.label}
              </Button>
            )}
            {secondaryAction && (
              <Button
                variant="ghost"
                size={size === 'lg' ? 'md' : 'sm'}
                onClick={secondaryAction.onClick}
              >
                {secondaryAction.label}
              </Button>
            )}
          </div>
        )}
      </div>
    );

    if (compact) {
      return (
        <div ref={ref} className={cn('', className)} {...props}>
          {content}
        </div>
      );
    }

    return (
      <Card ref={ref} variant="filled" className={cn('', className)} {...props}>
        {content}
      </Card>
    );
  }
);
ZeroState.displayName = 'ZeroState';

/**
 * LoadingState - Specialized loading indicator
 */
export interface LoadingStateProps extends React.HTMLAttributes<HTMLDivElement> {
  message?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const LoadingState = React.forwardRef<HTMLDivElement, LoadingStateProps>(
  ({ message = 'Loading...', size = 'md', className, ...props }, ref) => (
    <ZeroState
      ref={ref}
      variant="loading"
      title={message}
      size={size}
      compact
      className={className}
      {...props}
    />
  )
);
LoadingState.displayName = 'LoadingState';

/**
 * ErrorState - Specialized error display
 */
export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  message?: string;
  onRetry?: () => void;
  size?: 'sm' | 'md' | 'lg';
}

export const ErrorState = React.forwardRef<HTMLDivElement, ErrorStateProps>(
  ({ 
    title = 'Something went wrong', 
    message = 'An unexpected error occurred. Please try again.',
    onRetry,
    size = 'md',
    className, 
    ...props 
  }, ref) => (
    <ZeroState
      ref={ref}
      variant="error"
      title={title}
      description={message}
      action={onRetry ? { label: 'Try again', onClick: onRetry } : undefined}
      size={size}
      className={className}
      {...props}
    />
  )
);
ErrorState.displayName = 'ErrorState';
