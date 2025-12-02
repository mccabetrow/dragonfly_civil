import React from 'react';

export interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
}

const SectionHeader: React.FC<SectionHeaderProps> = ({ eyebrow, title, description, actions, className = '' }) => {
  return (
    <div
      className={[
        'flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between',
        className,
      ].join(' ')}
    >
      <div className="space-y-2">
        {eyebrow ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-slate-500">
            {eyebrow}
          </p>
        ) : null}
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
        {description ? <p className="text-sm text-slate-600">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-shrink-0 items-center gap-3">{actions}</div> : null}
    </div>
  );
};

export default SectionHeader;
