/**
 * OpsIntakePage - Dedicated intake queue page for ops
 * 
 * Shows AI-validated leads awaiting human verification.
 * Accessible at /ops/intake
 */
import { useMemo, type FC } from 'react';
import { 
  FileCheck, 
  RefreshCw, 
  CheckCircle, 
  XCircle, 
  AlertTriangle,
  TrendingUp,
  Clock
} from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import { Button } from '../components/ui/Button';
import OpsIntakeQueuePanel from '../components/ops/OpsIntakeQueuePanel';
import type { IntakeQueueItem } from '../components/ops/OpsIntakeQueuePanel';
import { useIntakeQueue, useSubmitIntakeReview, useIntakeStats } from '../hooks/useIntakeQueue';
import { useOnRefresh, useRefreshBus } from '../context/RefreshContext';

const OpsIntakePage: FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  
  // Data hooks
  const queue = useIntakeQueue(100);
  const stats = useIntakeStats();
  const { submitReview } = useSubmitIntakeReview();

  // Refetch on global refresh
  useOnRefresh(() => {
    queue.refetch();
    stats.refetch();
  });

  // Transform queue data to component format
  const queueItems = useMemo<IntakeQueueItem[]>(() => {
    if (!queue.data) return [];
    
    return queue.data.map(row => ({
      judgmentId: row.judgmentId,
      validationId: row.validationId,
      caseIndexNumber: row.caseIndexNumber,
      debtorName: row.debtorName,
      originalCreditor: row.originalCreditor,
      judgmentDate: row.judgmentDate,
      principalAmount: row.principalAmount,
      county: row.county,
      status: row.status,
      importedAt: row.importedAt,
      validatedAt: row.validatedAt,
      validationResult: row.validationResult,
      confidenceScore: row.confidenceScore,
      nameCheckPassed: row.nameCheckPassed,
      nameCheckNote: row.nameCheckNote,
      addressCheckPassed: row.addressCheckPassed,
      addressCheckNote: row.addressCheckNote,
      caseNumberCheckPassed: row.caseNumberCheckPassed,
      caseNumberCheckNote: row.caseNumberCheckNote,
      queueStatus: row.queueStatus,
      reviewPriority: row.reviewPriority,
      reviewDecision: row.reviewDecision,
    }));
  }, [queue.data]);

  // Handle review submission
  const handleReviewSubmit = async (
    validationId: string,
    decision: 'approved' | 'rejected' | 'flagged',
    notes?: string
  ) => {
    const success = await submitReview(validationId, decision, notes);
    if (success) {
      // Refresh the queue after successful submission
      queue.refetch();
      stats.refetch();
    }
  };

  // Stats cards data
  const statsData = stats.data;

  return (
    <div className="min-h-screen bg-slate-50/50">
      {/* Header */}
      <PageHeader
        title="Intake Queue"
        description="Review AI-validated leads before they enter the pipeline"
        badge={<FileCheck className="h-5 w-5 text-purple-500" />}
        actions={
          <Button
            variant="secondary"
            size="sm"
            onClick={triggerRefresh}
            disabled={isRefreshing}
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        }
      />

      <div className="p-6 space-y-6">
        {/* Stats cards */}
        <div className="grid grid-cols-5 gap-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <Clock className="h-3.5 w-3.5" />
              Pending Review
            </div>
            <div className="text-2xl font-bold text-slate-900">
              {statsData?.pendingHumanReview ?? '—'}
            </div>
          </div>
          
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
              Needs Review (24h)
            </div>
            <div className="text-2xl font-bold text-amber-600">
              {statsData?.validationResults?.needsReview ?? '—'}
            </div>
          </div>
          
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />
              AI Valid (24h)
            </div>
            <div className="text-2xl font-bold text-emerald-600">
              {statsData?.validationResults?.valid ?? '—'}
            </div>
          </div>
          
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <TrendingUp className="h-3.5 w-3.5 text-blue-500" />
              Approved Today
            </div>
            <div className="text-2xl font-bold text-blue-600">
              {statsData?.approvedToday ?? '—'}
            </div>
          </div>
          
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <XCircle className="h-3.5 w-3.5 text-red-500" />
              Rejected Today
            </div>
            <div className="text-2xl font-bold text-red-600">
              {statsData?.rejectedToday ?? '—'}
            </div>
          </div>
        </div>

        {/* Queue panel */}
        <OpsIntakeQueuePanel
          items={queueItems}
          isLoading={queue.status === 'loading'}
          onReviewSubmit={handleReviewSubmit}
        />

        {/* Info section */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">How Intake Validation Works</h3>
          <div className="grid grid-cols-3 gap-6 text-sm text-slate-600">
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-purple-100 text-purple-600 text-xs font-bold">1</div>
                Import
              </div>
              <p>New leads are imported from CSV files or vendor feeds and marked as "new_candidate".</p>
            </div>
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-purple-100 text-purple-600 text-xs font-bold">2</div>
                AI Validation
              </div>
              <p>Every morning at 10 AM, our AI validates name, address, and case number format for each lead.</p>
            </div>
            <div>
              <div className="flex items-center gap-2 font-medium text-slate-800 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-purple-100 text-purple-600 text-xs font-bold">3</div>
                Human Review
              </div>
              <p>You review the AI's assessment and approve, reject, or flag leads for further investigation.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OpsIntakePage;
