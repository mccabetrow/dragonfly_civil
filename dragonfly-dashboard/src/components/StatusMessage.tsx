import React from 'react';
import { AlertTriangle, CheckCircle2, Info, OctagonAlert } from 'lucide-react';

type StatusTone = 'info' | 'success' | 'warning' | 'error';

export interface StatusMessageProps {
  tone?: StatusTone;
  children: React.ReactNode;
  className?: string;
  iconOnly?: boolean;
}

const PALETTE: Record<StatusTone, string> = {
  info: 'border-slate-200 bg-slate-50 text-slate-600',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  error: 'border-rose-200 bg-rose-50 text-rose-700',
};

const ICONS: Record<StatusTone, React.ReactNode> = {
  info: <Info className="h-4 w-4" aria-hidden="true" />,
  success: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
  warning: <AlertTriangle className="h-4 w-4" aria-hidden="true" />,
  error: <OctagonAlert className="h-4 w-4" aria-hidden="true" />,
};

const StatusMessage: React.FC<StatusMessageProps> = ({ tone = 'info', children, className = '' }) => {
  return (
    <div
      className={[
        'inline-flex w-full items-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium',
        PALETTE[tone],
        className,
      ].join(' ')}
    >
      <span className="flex-shrink-0 text-current">{ICONS[tone]}</span>
      <span className="text-left leading-snug">{children}</span>
    </div>
  );
};

export default StatusMessage;
