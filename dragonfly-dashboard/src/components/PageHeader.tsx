import React from 'react';
import { FreshnessBadge } from './ui/FreshnessBadge';

export type PageHeaderVariant = 'default' | 'gradient';

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  variant?: PageHeaderVariant;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  /** ISO timestamp to display as "Snapshot as of: HH:MM:SS UTC" */
  snapshotTime?: string | Date | null;
}

const VARIANT_CLASSES: Record<PageHeaderVariant, string> = {
  default:
    'bg-white/90 text-slate-900 shadow-sm shadow-slate-900/5 backdrop-blur supports-[backdrop-filter]:bg-white/70',
  gradient:
    'bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 text-white shadow-lg shadow-indigo-900/30',
};

const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  eyebrow,
  variant = 'gradient',
  actions,
  children,
  snapshotTime,
}) => {
  return (
    <section
      className={[
        'relative overflow-hidden rounded-3xl border border-white/10 px-6 py-8 sm:px-8',
        VARIANT_CLASSES[variant],
      ].join(' ')}
    >
      {/* Snapshot freshness badge - top right */}
      {snapshotTime && (
        <div className="absolute right-4 top-4 sm:right-6 sm:top-6">
          <FreshnessBadge
            timestamp={snapshotTime}
            variant="full"
            staleThresholdSec={300}
          />
        </div>
      )}

      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-3">
          {eyebrow ? (
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-white/70">
              {eyebrow}
            </p>
          ) : null}
          <div>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-[2.5rem]">
              {title}
            </h1>
            {subtitle ? (
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-white/80">
                {subtitle}
              </p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex flex-shrink-0 items-center gap-3">{actions}</div> : null}
      </div>
      {children ? <div className="relative mt-6 text-white/80">{children}</div> : null}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.25),_transparent_55%)]" />
        <div className="absolute inset-y-0 right-0 w-1/3 bg-gradient-to-l from-indigo-500/10" />
      </div>
    </section>
  );
};

export default PageHeader;
