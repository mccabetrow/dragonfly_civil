
import { TrendingUp, TrendingDown, DollarSign, Briefcase, Users, FileCheck } from 'lucide-react';

export interface ScoreboardMetric {
  label: string;
  value: string | number;
  trend?: 'up' | 'down' | 'neutral';
  trendLabel?: string;
  icon?: 'dollar' | 'cases' | 'users' | 'signed';
}

interface ExecutiveScoreboardProps {
  metrics: ScoreboardMetric[];
  isLoading?: boolean;
  title?: string;
}

const iconMap = {
  dollar: <DollarSign className="h-5 w-5" />,
  cases: <Briefcase className="h-5 w-5" />,
  users: <Users className="h-5 w-5" />,
  signed: <FileCheck className="h-5 w-5" />,
};

export function ExecutiveScoreboard({
  metrics,
  isLoading,
  title = "Executive Scoreboard",
}: ExecutiveScoreboardProps) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <div className="h-5 w-40 animate-pulse rounded bg-slate-200" />
        </div>
        <div className="grid divide-y divide-slate-100 lg:grid-cols-2 lg:divide-x lg:divide-y-0 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="p-6">
              <div className="h-3 w-24 animate-pulse rounded bg-slate-100" />
              <div className="mt-3 h-8 w-20 animate-pulse rounded bg-slate-200" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-6 py-4">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      </div>
      <div className="grid divide-y divide-slate-100 lg:grid-cols-2 lg:divide-x lg:divide-y-0 xl:grid-cols-4">
        {metrics.map((metric, idx) => (
          <div key={metric.label ?? idx} className="p-6">
            <div className="flex items-center gap-2">
              {metric.icon && (
                <span className="text-slate-400">{iconMap[metric.icon]}</span>
              )}
              <p className="text-sm font-medium text-slate-500">{metric.label}</p>
            </div>
            <p className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">
              {typeof metric.value === 'number' ? metric.value.toLocaleString() : metric.value}
            </p>
            {metric.trend && metric.trend !== 'neutral' && (
              <div className="mt-2 flex items-center gap-1.5">
                {metric.trend === 'up' ? (
                  <TrendingUp className="h-4 w-4 text-emerald-500" />
                ) : (
                  <TrendingDown className="h-4 w-4 text-rose-500" />
                )}
                {metric.trendLabel && (
                  <span
                    className={`text-xs font-medium ${
                      metric.trend === 'up' ? 'text-emerald-600' : 'text-rose-600'
                    }`}
                  >
                    {metric.trendLabel}
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default ExecutiveScoreboard;
