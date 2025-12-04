/**
 * LitigationBudgetCard - CEO Dashboard Budget Allocation Panel
 * 
 * Displays daily litigation budget allocations computed from Tier A + B liquidity.
 * Shows skip tracing, litigation, marshal, and FOIL budgets with approval action.
 */
import React, { useState, type FC } from 'react';
import {
  DollarSign,
  TrendingUp,
  Zap,
  Search,
  Gavel,
  Shield,
  FileText,
  CheckCircle,
  AlertTriangle,
  Clock,
  Loader2,
} from 'lucide-react';
import { Button } from './ui/Button';
import { cn } from '../lib/design-tokens';
import { useLitigationBudget, useApproveBudget } from '../hooks/useLitigationBudget';

// ============================================================================
// Types
// ============================================================================

interface LitigationBudgetCardProps {
  className?: string;
  onApprovalComplete?: () => void;
}

// ============================================================================
// Formatters
// ============================================================================

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatCurrencyPrecise(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

// ============================================================================
// Sub-components
// ============================================================================

interface BudgetLineProps {
  icon: React.ReactNode;
  label: string;
  amount: number;
  description: string;
  highlight?: boolean;
}

const BudgetLine: FC<BudgetLineProps> = ({ icon, label, amount, description, highlight }) => (
  <div className={cn(
    'flex items-center justify-between py-3 border-b border-slate-100 last:border-0',
    highlight && 'bg-amber-50/50 -mx-4 px-4 rounded-lg border-amber-100'
  )}>
    <div className="flex items-center gap-3">
      <div className={cn(
        'flex h-8 w-8 items-center justify-center rounded-lg',
        highlight ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'
      )}>
        {icon}
      </div>
      <div>
        <p className="text-sm font-medium text-slate-900">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
    </div>
    <div className="text-right">
      <p className={cn(
        'text-lg font-semibold tabular-nums',
        highlight ? 'text-amber-700' : 'text-slate-900'
      )}>
        {formatCurrencyPrecise(amount)}
      </p>
    </div>
  </div>
);

interface MetricPillProps {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger';
}

const MetricPill: FC<MetricPillProps> = ({ label, value, icon, variant = 'default' }) => {
  const variantClasses = {
    default: 'bg-slate-100 text-slate-700',
    success: 'bg-emerald-100 text-emerald-700',
    warning: 'bg-amber-100 text-amber-700',
    danger: 'bg-red-100 text-red-700',
  };

  return (
    <div className={cn('flex items-center gap-2 rounded-full px-3 py-1.5', variantClasses[variant])}>
      {icon && <span className="h-3.5 w-3.5">{icon}</span>}
      <span className="text-xs font-medium">{label}:</span>
      <span className="text-xs font-bold tabular-nums">{value}</span>
    </div>
  );
};

// ============================================================================
// Loading State
// ============================================================================

const LoadingState: FC = () => (
  <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex items-center gap-3 mb-6">
      <div className="h-10 w-10 animate-pulse rounded-xl bg-slate-200" />
      <div>
        <div className="h-4 w-32 animate-pulse rounded bg-slate-200" />
        <div className="h-3 w-48 animate-pulse rounded bg-slate-100 mt-1" />
      </div>
    </div>
    <div className="space-y-4">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center justify-between py-3 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 animate-pulse rounded-lg bg-slate-100" />
            <div>
              <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
              <div className="h-3 w-32 animate-pulse rounded bg-slate-100 mt-1" />
            </div>
          </div>
          <div className="h-6 w-20 animate-pulse rounded bg-slate-200" />
        </div>
      ))}
    </div>
  </div>
);

// ============================================================================
// Error State
// ============================================================================

interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

const ErrorState: FC<ErrorStateProps> = ({ message, onRetry }) => (
  <div className="rounded-2xl border border-red-200 bg-red-50/50 p-6 shadow-sm">
    <div className="flex items-start gap-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-100">
        <AlertTriangle className="h-5 w-5 text-red-600" />
      </div>
      <div className="flex-1">
        <h3 className="text-sm font-semibold text-red-800">Budget Calculation Error</h3>
        <p className="text-sm text-red-700 mt-1">{message}</p>
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-3">
          Retry
        </Button>
      </div>
    </div>
  </div>
);

// ============================================================================
// Demo Locked State
// ============================================================================

interface DemoLockedStateProps {
  message: string;
}

const DemoLockedState: FC<DemoLockedStateProps> = ({ message }) => (
  <div className="rounded-2xl border border-purple-200 bg-purple-50/50 p-6 shadow-sm">
    <div className="flex items-start gap-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-100">
        <Shield className="h-5 w-5 text-purple-600" />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-purple-800">Budget Data Locked</h3>
        <p className="text-sm text-purple-700 mt-1">{message}</p>
      </div>
    </div>
  </div>
);

// ============================================================================
// Main Component
// ============================================================================

const LitigationBudgetCard: FC<LitigationBudgetCardProps> = ({ className, onApprovalComplete }) => {
  const { data: budget, status, errorMessage, refetch } = useLitigationBudget();
  const { approveBudget, isApproving } = useApproveBudget();
  const [approvalSuccess, setApprovalSuccess] = useState(false);

  // Handle approval
  const handleApprove = async () => {
    const result = await approveBudget(undefined, 'Daily budget approved via CEO Console');
    if (result) {
      setApprovalSuccess(true);
      onApprovalComplete?.();
      // Reset success message after 3 seconds
      setTimeout(() => setApprovalSuccess(false), 3000);
    }
  };

  // Loading state
  if (status === 'loading' || status === 'idle') {
    return <LoadingState />;
  }

  // Error state
  if (status === 'error') {
    return <ErrorState message={errorMessage ?? 'Unknown error'} onRetry={refetch} />;
  }

  // Demo locked state
  if (status === 'demo_locked') {
    return <DemoLockedState message={errorMessage ?? 'Data locked in demo mode'} />;
  }

  // No data
  if (!budget) {
    return <ErrorState message="No budget data available" onRetry={refetch} />;
  }

  return (
    <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="border-b border-slate-100 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              'flex h-10 w-10 items-center justify-center rounded-xl',
              budget.highAggressionMode 
                ? 'bg-amber-100 text-amber-600' 
                : 'bg-emerald-100 text-emerald-600'
            )}>
              {budget.highAggressionMode ? (
                <Zap className="h-5 w-5" />
              ) : (
                <DollarSign className="h-5 w-5" />
              )}
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Daily Litigation Budget</h2>
              <p className="text-sm text-slate-500">
                {budget.highAggressionMode ? (
                  <span className="text-amber-600 font-medium">⚡ High Aggression Mode Active</span>
                ) : (
                  'Standard allocation mode'
                )}
              </p>
            </div>
          </div>
          
          {/* Approve Button */}
          <Button
            variant={approvalSuccess ? 'primary' : 'secondary'}
            size="sm"
            onClick={handleApprove}
            disabled={isApproving || approvalSuccess}
            className="gap-2"
          >
            {isApproving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Approving...
              </>
            ) : approvalSuccess ? (
              <>
                <CheckCircle className="h-4 w-4" />
                Approved
              </>
            ) : (
              <>
                <CheckCircle className="h-4 w-4" />
                Approve Budget
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Liquidity Summary */}
      <div className="px-6 py-4 bg-slate-50/50 border-b border-slate-100">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Actionable Liquidity</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">
              {formatCurrency(budget.actionableLiquidity)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Tier A (Strategic)</p>
            <p className="text-lg font-semibold text-emerald-600 mt-1">
              {formatCurrency(budget.tierAPrincipal)}
              <span className="text-sm text-slate-500 ml-1">({budget.tierACount} cases)</span>
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Tier B (Active)</p>
            <p className="text-lg font-semibold text-blue-600 mt-1">
              {formatCurrency(budget.tierBPrincipal)}
              <span className="text-sm text-slate-500 ml-1">({budget.tierBCount} cases)</span>
            </p>
          </div>
        </div>
      </div>

      {/* Budget Lines */}
      <div className="px-6 py-4">
        <BudgetLine
          icon={<Search className="h-4 w-4" />}
          label="Skip Tracing"
          amount={budget.budgets.skiptracing}
          description="1% of actionable liquidity"
        />
        <BudgetLine
          icon={<Gavel className="h-4 w-4" />}
          label="Litigation"
          amount={budget.budgets.litigation}
          description="2% of actionable liquidity (garnishments + levies)"
        />
        <BudgetLine
          icon={<Shield className="h-4 w-4" />}
          label="Marshal Fees"
          amount={budget.budgets.marshal}
          description={`$35 × ${budget.activeEnforcementCount} active cases`}
        />
        <BudgetLine
          icon={<FileText className="h-4 w-4" />}
          label="FOIL Requests"
          amount={budget.budgets.foil}
          description={`$25 × ${budget.pendingFoilCount} pending requests`}
        />
        
        {/* Total */}
        <BudgetLine
          icon={<DollarSign className="h-4 w-4" />}
          label="Total Daily Budget"
          amount={budget.budgets.totalDaily}
          description="Sum of all allocations"
          highlight
        />
      </div>

      {/* Recovery Projection & Backlog */}
      <div className="px-6 py-4 bg-slate-50/50 border-t border-slate-100">
        <div className="flex flex-wrap items-center gap-3">
          <MetricPill
            label="Recovery Rate"
            value={formatPercent(budget.recovery.expectedRate)}
            icon={<TrendingUp className="h-3.5 w-3.5" />}
            variant="success"
          />
          <MetricPill
            label="30d Projection"
            value={formatCurrency(budget.recovery.projected30d)}
            icon={<DollarSign className="h-3.5 w-3.5" />}
            variant="success"
          />
          {budget.backlog.staleCaseCount > 0 && (
            <MetricPill
              label="Stale Cases"
              value={formatNumber(budget.backlog.staleCaseCount)}
              icon={<Clock className="h-3.5 w-3.5" />}
              variant={budget.backlog.staleCaseCount > 10 ? 'danger' : 'warning'}
            />
          )}
          {budget.backlog.avgDaysStale > 0 && (
            <MetricPill
              label="Avg Stale"
              value={`${Math.round(budget.backlog.avgDaysStale)}d`}
              icon={<AlertTriangle className="h-3.5 w-3.5" />}
              variant={budget.backlog.avgDaysStale > 45 ? 'danger' : 'warning'}
            />
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-6 py-3 border-t border-slate-100 text-xs text-slate-400">
        Computed {new Date(budget.computedAt).toLocaleString()}
      </div>
    </div>
  );
};

export default LitigationBudgetCard;
