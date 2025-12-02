import React from 'react';
import { CheckCircle2, Phone, FileSignature, Users } from 'lucide-react';
import type { OpsDailySummary } from '../hooks/useOpsDailySummary';

interface TodayProgressCardProps {
  summary: OpsDailySummary | null;
  isLoading?: boolean;
}

interface ProgressMetric {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
}

export function TodayProgressCard({ summary, isLoading }: TodayProgressCardProps) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 h-4 w-32 animate-pulse rounded bg-slate-200" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-10 w-10 animate-pulse rounded-xl bg-slate-100" />
              <div className="space-y-1.5">
                <div className="h-3 w-16 animate-pulse rounded bg-slate-100" />
                <div className="h-6 w-10 animate-pulse rounded bg-slate-200" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-center text-sm text-slate-500">No activity logged yet today.</p>
      </div>
    );
  }

  const metrics: ProgressMetric[] = [
    {
      label: 'New plaintiffs',
      value: summary.newPlaintiffs,
      icon: <Users className="h-5 w-5" />,
      color: 'bg-blue-50 text-blue-600',
    },
    {
      label: 'Contacted',
      value: summary.plaintiffsContacted,
      icon: <CheckCircle2 className="h-5 w-5" />,
      color: 'bg-emerald-50 text-emerald-600',
    },
    {
      label: 'Calls made',
      value: summary.callsMade,
      icon: <Phone className="h-5 w-5" />,
      color: 'bg-violet-50 text-violet-600',
    },
    {
      label: 'Agreements sent',
      value: summary.agreementsSent,
      icon: <FileSignature className="h-5 w-5" />,
      color: 'bg-amber-50 text-amber-600',
    },
    {
      label: 'Signed',
      value: summary.agreementsSigned,
      icon: <CheckCircle2 className="h-5 w-5" />,
      color: 'bg-green-50 text-green-600',
    },
  ];

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Today's Progress
      </h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {metrics.map((metric) => (
          <div key={metric.label} className="flex items-center gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${metric.color}`}>
              {metric.icon}
            </div>
            <div>
              <p className="text-xs text-slate-500">{metric.label}</p>
              <p className="text-xl font-semibold text-slate-900">
                {metric.value.toLocaleString()}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default TodayProgressCard;
