/**
 * PageHeader Component
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Consistent page header with title, description, and actions.
 * Bloomberg/Palantir-style command center headers.
 */

import * as React from 'react';
import { cn } from '../../lib/tokens';

export interface PageHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Page title */
  title: string;
  /** Page description/subtitle */
  description?: string;
  /** Optional badge/indicator next to title */
  badge?: React.ReactNode;
  /** Actions slot (buttons, etc.) */
  actions?: React.ReactNode;
  /** Breadcrumb content */
  breadcrumb?: React.ReactNode;
  /** Optional icon */
  icon?: React.ReactNode;
}

export const PageHeader = React.forwardRef<HTMLDivElement, PageHeaderProps>(
  ({ title, description, badge, actions, breadcrumb, icon, className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn('flex flex-col gap-4 pb-6', className)}
        {...props}
      >
        {/* Breadcrumb row */}
        {breadcrumb && (
          <nav className="flex items-center text-sm text-slate-500">
            {breadcrumb}
          </nav>
        )}

        {/* Main header row */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            {/* Icon */}
            {icon && (
              <div className="flex-shrink-0 p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                {icon}
              </div>
            )}

            {/* Title block */}
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-semibold text-slate-900 tracking-tight truncate">
                  {title}
                </h1>
                {badge}
              </div>
              {description && (
                <p className="mt-1 text-sm text-slate-500 max-w-2xl">
                  {description}
                </p>
              )}
            </div>
          </div>

          {/* Actions */}
          {actions && (
            <div className="flex items-center gap-2 flex-shrink-0">
              {actions}
            </div>
          )}
        </div>
      </div>
    );
  }
);
PageHeader.displayName = 'PageHeader';

/**
 * Breadcrumb helper components
 */
export interface BreadcrumbProps extends React.HTMLAttributes<HTMLOListElement> {}

export const Breadcrumb = React.forwardRef<HTMLOListElement, BreadcrumbProps>(
  ({ className, ...props }, ref) => (
    <ol ref={ref} className={cn('flex items-center gap-1.5', className)} {...props} />
  )
);
Breadcrumb.displayName = 'Breadcrumb';

export interface BreadcrumbItemProps extends React.HTMLAttributes<HTMLLIElement> {
  href?: string;
  current?: boolean;
}

export const BreadcrumbItem = React.forwardRef<HTMLLIElement, BreadcrumbItemProps>(
  ({ href, current, className, children, ...props }, ref) => (
    <li ref={ref} className={cn('flex items-center gap-1.5', className)} {...props}>
      {href && !current ? (
        <a
          href={href}
          className="text-slate-500 hover:text-slate-700 transition-colors"
        >
          {children}
        </a>
      ) : (
        <span className={cn(current ? 'text-slate-900 font-medium' : 'text-slate-500')}>
          {children}
        </span>
      )}
    </li>
  )
);
BreadcrumbItem.displayName = 'BreadcrumbItem';

export const BreadcrumbSeparator = React.forwardRef<HTMLLIElement, React.HTMLAttributes<HTMLLIElement>>(
  ({ className, ...props }, ref) => (
    <li ref={ref} className={cn('text-slate-300', className)} {...props}>
      <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
        <path
          fillRule="evenodd"
          d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
          clipRule="evenodd"
        />
      </svg>
    </li>
  )
);
BreadcrumbSeparator.displayName = 'BreadcrumbSeparator';

/**
 * PageSection - For organizing page content into logical sections
 */
export interface PageSectionProps extends React.HTMLAttributes<HTMLElement> {
  title?: string;
  description?: string;
  actions?: React.ReactNode;
}

export const PageSection = React.forwardRef<HTMLElement, PageSectionProps>(
  ({ title, description, actions, className, children, ...props }, ref) => (
    <section ref={ref} className={cn('', className)} {...props}>
      {(title || description || actions) && (
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            {title && (
              <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
            )}
            {description && (
              <p className="text-sm text-slate-500 mt-0.5">{description}</p>
            )}
          </div>
          {actions && (
            <div className="flex items-center gap-2">{actions}</div>
          )}
        </div>
      )}
      {children}
    </section>
  )
);
PageSection.displayName = 'PageSection';
