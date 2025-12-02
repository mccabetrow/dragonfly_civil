import React from 'react';

interface SkeletonLineProps {
  width?: string;
  height?: number;
  className?: string;
}

const SkeletonLine: React.FC<SkeletonLineProps> = ({ width = '100%', height = 16, className = '' }) => (
  <div
    className={['df-skeleton', className].filter(Boolean).join(' ')}
    style={{ width, height }}
  />
);

const SkeletonPill: React.FC<{ width?: string; className?: string }> = ({ width = '40%', className = '' }) => (
  <div className={['df-skeleton-pill', className].filter(Boolean).join(' ')} style={{ width }} />
);

export interface LoadingSkeletonsProps {
  sections?: number;
  rowsPerSection?: number;
}

const LoadingSkeletons: React.FC<LoadingSkeletonsProps> = ({ sections = 3, rowsPerSection = 4 }) => {
  return (
    <div className="space-y-6">
      {Array.from({ length: sections }).map((_, sectionIndex) => (
        <section key={`loading-section-${sectionIndex}`} className="df-card space-y-4">
          <SkeletonPill width="30%" />
          {Array.from({ length: rowsPerSection }).map((__, rowIndex) => (
            <SkeletonLine key={`loading-row-${sectionIndex}-${rowIndex}`} height={14} />
          ))}
        </section>
      ))}
    </div>
  );
};

export default LoadingSkeletons;

export const OverviewSkeleton: React.FC = () => (
  <div className="space-y-6">
    <section className="df-card space-y-4">
      <SkeletonLine width="24%" height={18} />
      <SkeletonLine width="75%" height={14} />
      <SkeletonLine width="52%" height={14} />
    </section>

    <section className="grid gap-4 md:grid-cols-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={`overview-metric-${index}`} className="df-card space-y-5">
          <SkeletonPill width="36%" />
          <SkeletonLine width="85%" height={14} />
          <SkeletonLine width="45%" height={36} />
        </div>
      ))}
    </section>

    <section className="df-card space-y-5">
      <SkeletonPill width="28%" />
      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={`overview-tier-${index}`} className="df-subcard space-y-3">
            <SkeletonPill width="30%" />
            <SkeletonLine width="40%" height={28} />
            <SkeletonLine width="90%" height={12} />
          </div>
        ))}
      </div>
    </section>

    <section className="df-card space-y-4">
      <SkeletonPill width="24%" />
      <SkeletonLine width="70%" height={14} />
      <SkeletonLine width="40%" height={14} />
      <SkeletonLine width="90%" height={90} />
    </section>

    <section className="df-card space-y-4">
      <SkeletonPill width="26%" />
      <SkeletonLine width="65%" height={14} />
      <div className="overflow-hidden rounded-xl border border-slate-200">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={`overview-table-${index}`} className="grid grid-cols-5 gap-4 border-b border-slate-100 px-4 py-4">
            {Array.from({ length: 5 }).map((__, cellIndex) => (
              <SkeletonLine key={`overview-table-${index}-${cellIndex}`} height={14} />
            ))}
          </div>
        ))}
      </div>
    </section>
  </div>
);

export const CollectabilitySkeleton: React.FC = () => (
  <div className="space-y-8">
    <div className="space-y-2">
      <SkeletonLine width="38%" height={18} />
      <SkeletonLine width="68%" height={14} />
    </div>

    <section className="grid gap-6 md:grid-cols-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={`collectability-summary-${index}`} className="df-card space-y-4">
          <SkeletonPill width="30%" />
          <SkeletonLine width="45%" height={40} />
          <SkeletonLine width="70%" height={16} />
          <SkeletonLine width="90%" height={14} />
        </div>
      ))}
    </section>

    <section className="df-panel">
      <div className="df-panel-header space-y-2">
        <SkeletonLine width="30%" height={18} />
        <SkeletonLine width="60%" height={14} />
      </div>
      <div className="df-panel-body space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={`collectability-filter-${index}`} className="df-subcard space-y-3">
              <SkeletonPill width="40%" />
              <SkeletonLine width="100%" height={40} />
              <SkeletonLine width="80%" height={12} />
            </div>
          ))}
        </div>
        <SkeletonLine width="40%" height={12} />
        <div className="overflow-hidden rounded-xl border border-slate-200">
          {Array.from({ length: 6 }).map((_, rowIndex) => (
            <div key={`collectability-table-${rowIndex}`} className="grid grid-cols-6 gap-4 border-b border-slate-100 px-4 py-4">
              {Array.from({ length: 6 }).map((__, cellIndex) => (
                <SkeletonLine key={`collectability-table-${rowIndex}-${cellIndex}`} height={14} />
              ))}
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <SkeletonLine width="24%" height={14} />
          <div className="flex gap-2">
            <SkeletonLine width="72px" height={36} />
            <SkeletonLine width="72px" height={36} />
          </div>
        </div>
      </div>
    </section>
  </div>
);

export const CasesSkeleton: React.FC = () => (
  <div className="space-y-6">
    <section className="df-card space-y-3">
      <SkeletonLine width="30%" height={18} />
      <SkeletonLine width="72%" height={14} />
      <SkeletonLine width="54%" height={14} />
    </section>

    <section className="df-panel">
      <div className="df-panel-header space-y-2">
        <SkeletonLine width="28%" height={18} />
        <SkeletonLine width="60%" height={14} />
      </div>
      <div className="df-panel-body space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 2 }).map((_, index) => (
            <div key={`cases-filter-${index}`} className="df-subcard space-y-3">
              <SkeletonPill width="32%" />
              <SkeletonLine width="100%" height={40} />
            </div>
          ))}
        </div>
        <SkeletonLine width="40%" height={12} />
        <div className="overflow-hidden rounded-xl border border-slate-200">
          {Array.from({ length: 6 }).map((_, rowIndex) => (
            <div key={`cases-table-${rowIndex}`} className="grid grid-cols-5 gap-4 border-b border-slate-100 px-4 py-4">
              {Array.from({ length: 5 }).map((__, cellIndex) => (
                <SkeletonLine key={`cases-table-${rowIndex}-${cellIndex}`} height={14} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>

    <section className="df-panel">
      <div className="df-panel-header space-y-2">
        <SkeletonLine width="32%" height={18} />
        <SkeletonLine width="55%" height={14} />
      </div>
      <div className="df-panel-body space-y-4">
        {Array.from({ length: 4 }).map((_, rowIndex) => (
          <div key={`cases-foil-${rowIndex}`} className="grid grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((__, cellIndex) => (
              <SkeletonLine key={`cases-foil-${rowIndex}-${cellIndex}`} height={14} />
            ))}
          </div>
        ))}
      </div>
    </section>
  </div>
);
