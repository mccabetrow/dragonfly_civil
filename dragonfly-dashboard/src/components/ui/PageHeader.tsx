/**
 * PageHeader - Consistent page header with title, description, and optional actions
 * 
 * Design tokens: typography.h1, colors.text.primary/secondary
 * Use across all pages for visual consistency.
 */
import type { FC, ReactNode } from 'react';
import { cn } from '../../lib/design-tokens';

interface PageHeaderProps {
  /** Page title (required) */
  title: string;
  /** Optional description below title */
  description?: string;
  /** Optional actions (buttons, etc.) on the right */
  actions?: ReactNode;
  /** Optional badge or status indicator next to title */
  badge?: ReactNode;
  /** Additional className for the container */
  className?: string;
}

const PageHeader: FC<PageHeaderProps> = ({
  title,
  description,
  actions,
  badge,
  className,
}) => {
  return (
    <div className={cn('mb-6', className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              {title}
            </h1>
            {badge}
          </div>
          {description && (
            <p className="mt-1.5 text-sm text-slate-600 max-w-2xl">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 items-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
};

export default PageHeader;
