import type { ReactNode } from 'react';
import { formatDateTime } from '../utils/formatters';

export type TimelineAccent = 'slate' | 'indigo' | 'emerald' | 'rose';

export interface TimelineCardProps {
  title: string;
  timestamp?: string | null;
  subtitle?: string | null;
  description?: string | null;
  accent?: TimelineAccent;
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
}

const ACCENT_CLASSES: Record<TimelineAccent, string> = {
  slate: 'bg-slate-400',
  indigo: 'bg-indigo-500',
  emerald: 'bg-emerald-500',
  rose: 'bg-rose-500',
};

export function TimelineCard({
  title,
  timestamp,
  subtitle,
  description,
  accent = 'slate',
  footer,
  children,
  className,
}: TimelineCardProps) {
  const accentClass = ACCENT_CLASSES[accent] ?? ACCENT_CLASSES.slate;
  const composedClassName = `rounded-2xl border border-slate-200 bg-white p-4 shadow-sm ${className ?? ''}`.trim();
  const formattedTimestamp = timestamp ? formatDateTime(timestamp) : null;

  return (
    <article className={composedClassName}>
      <div className="flex items-start gap-3">
        <span className={`mt-1 h-2.5 w-2.5 rounded-full ${accentClass}`} aria-hidden />
        <div className="flex-1 space-y-1">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-slate-900">{title}</p>
            {formattedTimestamp ? <time className="text-xs text-slate-500">{formattedTimestamp}</time> : null}
          </header>
          {subtitle ? <p className="text-xs text-slate-500">{subtitle}</p> : null}
          {description ? <p className="text-sm text-slate-600">{description}</p> : null}
          {children ? <div className="pt-2 text-sm text-slate-600">{children}</div> : null}
        </div>
      </div>
      {footer ? <div className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">{footer}</div> : null}
    </article>
  );
}
