import React from 'react';
import { Link } from 'react-router-dom';
import { Inbox, ArrowRight } from 'lucide-react';

export interface ZeroStateCardProps {
  title: string;
  description: string;
  actionLabel?: string;
  actionLink?: string;
  icon?: React.ReactNode;
  className?: string;
}

/**
 * A friendly empty-state card shown when there are no judgments/cases to display.
 * Guides the first-time user on what to expect and how to proceed.
 */
const ZeroStateCard: React.FC<ZeroStateCardProps> = ({
  title,
  description,
  actionLabel,
  actionLink,
  icon,
  className = '',
}) => {
  return (
    <div
      className={[
        'flex flex-col items-center gap-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50/50 px-8 py-12 text-center',
        className,
      ].join(' ')}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        {icon ?? <Inbox className="h-7 w-7" aria-hidden="true" />}
      </div>
      <div className="max-w-sm">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">{description}</p>
      </div>
      {actionLabel && actionLink && (
        <Link
          to={actionLink}
          className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 hover:text-slate-900"
        >
          {actionLabel}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      )}
    </div>
  );
};

export default ZeroStateCard;
