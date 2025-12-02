import React from 'react';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';

export type MetricTrend = 'up' | 'down' | 'flat';

export interface MetricDelta {
  value: string;
  trend?: MetricTrend;
  tone?: 'positive' | 'negative' | 'neutral';
}

export interface MetricCardProps {
  label: string;
  value?: string | number | React.ReactNode;
  loading?: boolean;
  delta?: MetricDelta;
  icon?: React.ReactNode;
  footer?: React.ReactNode;
  status?: 'default' | 'locked' | 'error';
  message?: string;
  className?: string;
}

const trendIconMap: Record<MetricTrend, React.ReactNode> = {
  up: <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />,
  down: <ArrowDownRight className="h-3.5 w-3.5" aria-hidden="true" />,
  flat: <Minus className="h-3.5 w-3.5" aria-hidden="true" />,
};

const toneClasses: Record<NonNullable<MetricDelta['tone']>, string> = {
  positive: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  negative: 'bg-rose-50 text-rose-700 ring-rose-200',
  neutral: 'bg-slate-100 text-slate-600 ring-slate-200',
};

const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  loading,
  delta,
  icon,
  footer,
  status = 'default',
  message,
  className = '',
}) => {
  const displayValue = loading ? '...' : value;
  const showMessage = status !== 'default' && message;
  const cardClasses = [
    'group relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white/90 p-5 shadow-sm shadow-slate-900/5 transition-all duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <article className={cardClasses}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">{label}</p>
          <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
            {showMessage ? (
              <span className="text-base font-semibold text-slate-500">{message}</span>
            ) : (
              <span>{displayValue}</span>
            )}
          </p>
          {delta ? (
            <span
              className={[
                'mt-3 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset',
                toneClasses[delta.tone ?? 'neutral'],
              ].join(' ')}
            >
              {trendIconMap[delta.trend ?? 'flat']}
              {delta.value}
            </span>
          ) : null}
        </div>
        {icon ? (
          <span className="rounded-2xl bg-slate-100 p-3 text-slate-600 transition group-hover:bg-slate-900/5 group-hover:text-slate-900">
            {icon}
          </span>
        ) : null}
      </div>
      {footer ? <div className="mt-4 text-sm text-slate-600">{footer}</div> : null}
    </article>
  );
};

export default MetricCard;
