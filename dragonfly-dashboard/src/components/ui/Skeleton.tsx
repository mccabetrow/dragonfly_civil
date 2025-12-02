import { type FC } from 'react';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// SKELETON PRIMITIVES
// ═══════════════════════════════════════════════════════════════════════════

export interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
}

export const Skeleton: FC<SkeletonProps> = ({ className, width, height }) => {
  return (
    <div
      className={cn('animate-pulse rounded-lg bg-slate-200', className)}
      style={{
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height,
      }}
    />
  );
};

export const SkeletonText: FC<{ lines?: number; className?: string }> = ({
  lines = 3,
  className,
}) => {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-4"
          width={i === lines - 1 ? '60%' : '100%'}
        />
      ))}
    </div>
  );
};

export const SkeletonCircle: FC<{ size?: number; className?: string }> = ({
  size = 40,
  className,
}) => {
  return (
    <Skeleton
      className={cn('rounded-full', className)}
      width={size}
      height={size}
    />
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// PAGE SKELETON LAYOUTS
// ═══════════════════════════════════════════════════════════════════════════

export const MetricCardSkeleton: FC = () => (
  <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <Skeleton className="h-3 w-24 mb-3" />
    <Skeleton className="h-4 w-full mb-2" />
    <Skeleton className="h-4 w-3/4 mb-6" />
    <Skeleton className="h-8 w-20" />
  </div>
);

export const TableRowSkeleton: FC<{ columns?: number }> = ({ columns = 5 }) => (
  <tr className="border-t border-slate-100">
    {Array.from({ length: columns }).map((_, i) => (
      <td key={i} className="px-4 py-3">
        <Skeleton className="h-4" width={i === 0 ? '80%' : '60%'} />
      </td>
    ))}
  </tr>
);

export const TableSkeleton: FC<{ rows?: number; columns?: number }> = ({
  rows = 5,
  columns = 5,
}) => (
  <div className="overflow-hidden rounded-xl border border-slate-200">
    <table className="min-w-full">
      <thead className="bg-slate-50">
        <tr>
          {Array.from({ length: columns }).map((_, i) => (
            <th key={i} className="px-4 py-3">
              <Skeleton className="h-3 w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }).map((_, i) => (
          <TableRowSkeleton key={i} columns={columns} />
        ))}
      </tbody>
    </table>
  </div>
);

export const CardSkeleton: FC<{ className?: string }> = ({ className }) => (
  <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
    <Skeleton className="h-5 w-32 mb-3" />
    <SkeletonText lines={2} />
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// FULL PAGE SKELETONS
// ═══════════════════════════════════════════════════════════════════════════

export const OverviewPageSkeleton: FC = () => (
  <div className="space-y-6">
    {/* Header section */}
    <CardSkeleton />

    {/* Metric cards */}
    <div className="grid gap-4 md:grid-cols-3">
      <MetricCardSkeleton />
      <MetricCardSkeleton />
      <MetricCardSkeleton />
    </div>

    {/* Tier distribution */}
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <Skeleton className="h-4 w-28 mb-4" />
      <div className="grid gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
            <Skeleton className="h-3 w-16 mb-3" />
            <Skeleton className="h-7 w-12 mb-2" />
            <Skeleton className="h-3 w-full" />
          </div>
        ))}
      </div>
    </div>

    {/* Actions table */}
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <Skeleton className="h-4 w-24 mb-2" />
      <Skeleton className="h-3 w-48 mb-4" />
      <TableSkeleton rows={5} columns={5} />
    </div>
  </div>
);

export const CollectabilityPageSkeleton: FC = () => (
  <div className="space-y-8">
    <Skeleton className="h-4 w-3/4" />

    {/* Tier summary cards */}
    <div className="grid gap-6 md:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3 mb-4">
            <Skeleton className="h-8 w-8 rounded-lg" />
            <div>
              <Skeleton className="h-4 w-24 mb-1" />
              <Skeleton className="h-6 w-12" />
            </div>
          </div>
          <SkeletonText lines={2} />
        </div>
      ))}
    </div>

    {/* Table section */}
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-6 py-5">
        <Skeleton className="h-5 w-32 mb-2" />
        <Skeleton className="h-4 w-64" />
      </div>
      <div className="p-6">
        <TableSkeleton rows={10} columns={6} />
      </div>
    </div>
  </div>
);

export const CasesPageSkeleton: FC = () => (
  <div className="space-y-6">
    <CardSkeleton />

    {/* Cases table section */}
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-4 border-b border-slate-200 px-6 py-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <Skeleton className="h-5 w-40 mb-2" />
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="flex gap-4">
          <div className="w-48">
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </div>
          <div className="w-48">
            <Skeleton className="h-3 w-12 mb-2" />
            <Skeleton className="h-10 w-full rounded-xl" />
          </div>
        </div>
      </div>
      <div className="px-6 pb-4">
        <Skeleton className="h-3 w-32" />
      </div>
      <TableSkeleton rows={8} columns={5} />
    </div>

    {/* FOIL section */}
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-6 py-5">
        <Skeleton className="h-5 w-48 mb-2" />
        <Skeleton className="h-4 w-80" />
      </div>
      <TableSkeleton rows={5} columns={4} />
    </div>
  </div>
);

export default Skeleton;
