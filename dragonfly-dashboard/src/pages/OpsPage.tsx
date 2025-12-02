/**
 * OpsPage - Mom's streamlined operations console
 * 
 * Layout: Call Queue (primary) | Enforcement Pipeline + Alerts (secondary)
 * Designed for single-operator workflow with minimal cognitive load.
 */
import { useMemo } from 'react';
import type { FC } from 'react';
import { Headphones, RefreshCw, Lightbulb, CheckCircle } from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import OpsCallQueuePanel from '../components/ops/OpsCallQueuePanel';
import OpsEnforcementPanel from '../components/ops/OpsEnforcementPanel';
import OpsAlertsPanel, { type OpsAlert } from '../components/ops/OpsAlertsPanel';
import { Button } from '../components/ui/Button';
import { usePlaintiffCallQueue, type PlaintiffCallQueueRow } from '../hooks/usePlaintiffCallQueue';
import { useEnforcementPipeline } from '../hooks/useEnforcementPipeline';
import { useOnRefresh } from '../context/RefreshContext';

const OpsPage: FC = () => {
  // Data hooks
  const callQueue = usePlaintiffCallQueue(20);
  const pipeline = useEnforcementPipeline();

  // Safe data accessors with empty array fallback
  const queueData = callQueue.data ?? [];
  const pipelineData = pipeline.data ?? [];

  // Refetch on global refresh
  useOnRefresh(() => {
    callQueue.refetch();
    pipeline.refetch();
  });

  // Generate alerts from data state
  const alerts = useMemo<OpsAlert[]>(() => {
    const result: OpsAlert[] = [];

    // Check for items awaiting signature (urgent)
    const awaitingSignature = pipelineData.filter(
      (item) => item.pipelineStage === 'awaiting_signature'
    );
    if (awaitingSignature.length > 0) {
      result.push({
        id: 'awaiting-signature',
        type: 'warning',
        title: 'Documents awaiting signature',
        message: `${awaitingSignature.length} judgment${awaitingSignature.length !== 1 ? 's' : ''} need signed documents to proceed.`,
        timestamp: new Date().toISOString(),
        actionLabel: 'View in pipeline',
      });
    }

    // Check for call queue being empty (info)
    if (callQueue.state.status === 'ready' && queueData.length === 0) {
      result.push({
        id: 'queue-empty',
        type: 'success',
        title: 'Call queue complete',
        message: "You've completed all scheduled calls for today. Great work!",
        timestamp: new Date().toISOString(),
        dismissible: true,
      });
    }

    // Check for high-value plaintiffs in queue
    const highValuePlaintiffs = queueData.filter(
      (p) => p.totalJudgmentAmount >= 50000
    );
    if (highValuePlaintiffs.length > 0) {
      result.push({
        id: 'high-value',
        type: 'info',
        title: 'High-value plaintiffs in queue',
        message: `${highValuePlaintiffs.length} plaintiff${highValuePlaintiffs.length !== 1 ? 's' : ''} with $50k+ in total judgments.`,
        timestamp: new Date().toISOString(),
      });
    }

    return result;
  }, [queueData, callQueue.state.status, pipelineData]);

  const handleQuickAction = (
    item: PlaintiffCallQueueRow,
    action: 'call' | 'skip' | 'voicemail'
  ) => {
    // TODO: Wire to RPC once backend is ready
    // For now, show user-friendly feedback
    const messages: Record<typeof action, string> = {
      call: `✓ Marked ${item.plaintiffName} as reached`,
      voicemail: `✓ Logged voicemail for ${item.plaintiffName}`,
      skip: `✓ Skipped ${item.plaintiffName} for now`,
    };
    alert(messages[action] + '\n\n(Backend integration coming soon)');
    console.log('Quick action:', action, 'for plaintiff:', item.plaintiffId);
  };

  const isLoading = callQueue.state.status === 'loading' || pipeline.state.status === 'loading';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ops Console"
        description="Your daily command center for calls, enforcement tracking, and alerts."
        badge={
          queueData.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-sm font-semibold text-blue-700">
              <Headphones className="h-4 w-4" />
              {queueData.length} calls
            </span>
          )
        }
        actions={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              callQueue.refetch();
              pipeline.refetch();
            }}
            disabled={isLoading}
            leftIcon={<RefreshCw className={isLoading ? 'animate-spin' : ''} />}
          >
            Refresh
          </Button>
        }
      />

      {/* Today's Plan — coaching card for morning orientation */}
      <div className="rounded-2xl bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 p-5">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-600">
            <Lightbulb className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              Today's Plan
              {queueData.length === 0 && pipelineData.length === 0 && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
                  <CheckCircle className="h-3.5 w-3.5" /> All clear
                </span>
              )}
            </h3>
            <p className="mt-1 text-sm text-gray-600">
              {queueData.length > 0 ? (
                <>
                  <span className="font-medium text-gray-900">Step 1:</span> Work through the{' '}
                  <span className="font-medium text-gray-900">{queueData.length} calls</span> below.
                  {pipelineData.length > 0 && (
                    <>
                      {' '}<span className="font-medium text-gray-900">Step 2:</span> Review{' '}
                      <span className="font-medium text-gray-900">{pipelineData.length} enforcement items</span>.
                    </>
                  )}
                </>
              ) : pipelineData.length > 0 ? (
                <>
                  No calls right now. Focus on the{' '}
                  <span className="font-medium text-gray-900">{pipelineData.length} enforcement items</span> in the right panel.
                </>
              ) : (
                <>
                  You're all caught up! Check back later or visit{' '}
                  <a href="/cases" className="font-medium text-blue-600 hover:underline">Cases</a> to review your portfolio.
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Main content grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left column: Call Queue (2/3 width on large screens) */}
        <div className="lg:col-span-2">
          <OpsCallQueuePanel
            items={queueData}
            isLoading={callQueue.state.status === 'loading'}
            onQuickAction={handleQuickAction}
          />
        </div>

        {/* Right column: Enforcement + Alerts (1/3 width) */}
        <div className="space-y-6">
          <OpsAlertsPanel
            alerts={alerts}
            isLoading={false}
          />

          <OpsEnforcementPanel
            items={pipelineData}
            isLoading={pipeline.state.status === 'loading'}
            maxItems={8}
          />
        </div>
      </div>

      {/* Quick stats footer */}
      <div className="rounded-2xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Today's Progress
        </h3>
        <div className="mt-4 grid grid-cols-2 gap-6 sm:grid-cols-4">
          <div>
            <p className="text-2xl font-semibold text-slate-900">
              {queueData.length}
            </p>
            <p className="text-sm text-slate-500">Calls remaining</p>
          </div>
          <div>
            <p className="text-2xl font-semibold text-slate-900">
              {pipelineData.filter((p) => p.pipelineStage === 'actions_in_progress').length}
            </p>
            <p className="text-sm text-slate-500">Actions in progress</p>
          </div>
          <div>
            <p className="text-2xl font-semibold text-slate-900">
              {pipelineData.filter((p) => p.pipelineStage === 'awaiting_signature').length}
            </p>
            <p className="text-sm text-slate-500">Awaiting signature</p>
          </div>
          <div>
            <p className="text-2xl font-semibold text-emerald-600">
              {pipelineData.filter((p) => p.pipelineStage === 'actions_complete').length}
            </p>
            <p className="text-sm text-slate-500">Actions complete</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OpsPage;
