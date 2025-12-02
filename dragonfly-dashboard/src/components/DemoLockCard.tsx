import { Lock } from 'lucide-react';
import React from 'react';

export interface DemoLockCardProps {
  title?: string;
  description?: string;
  className?: string;
  ctaLabel?: string;
  ctaHref?: string;
  onCtaClick?: () => void;
}

const DEFAULT_TITLE = 'Metrics locked in this demo';
const DEFAULT_DESCRIPTION =
  'Detailed metrics stay hidden in the demo tenant. Sign into the production enforcement console to see plaintiff-level context and dollar exposure.';

const DemoLockCard: React.FC<DemoLockCardProps> = ({
  title = DEFAULT_TITLE,
  description = DEFAULT_DESCRIPTION,
  className = '',
  ctaLabel,
  ctaHref,
  onCtaClick,
}) => {
  const classes = [
    'flex flex-col gap-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50/90 p-5 text-slate-700 shadow-sm',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const cta = ctaLabel
    ? ctaHref
      ? (
          <a
            href={ctaHref}
            target="_blank"
            rel="noreferrer"
            className="inline-flex text-sm font-semibold text-indigo-600 transition hover:text-indigo-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            {ctaLabel}
          </a>
        )
      : (
          <button
            type="button"
            onClick={onCtaClick}
            className="inline-flex text-sm font-semibold text-indigo-600 transition hover:text-indigo-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
          >
            {ctaLabel}
          </button>
        )
    : null;

  return (
    <article className={classes}>
      <div className="flex items-start gap-4">
        <span className="rounded-2xl bg-slate-200/80 p-2 text-slate-700">
          <Lock className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="space-y-2">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-500">Demo safe</p>
            <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
          </div>
          <p className="text-sm leading-relaxed text-slate-600">{description}</p>
          {cta ? <span className="inline-flex">{cta}</span> : null}
        </div>
      </div>
    </article>
  );
};

export default DemoLockCard;
