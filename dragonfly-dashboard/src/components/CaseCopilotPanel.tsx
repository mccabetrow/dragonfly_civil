import type { CaseCopilotInsight, CaseInfo } from '../hooks/useCaseCopilotInsight';
import { InlineSpinner } from './InlineSpinner';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import DemoLockCard from './DemoLockCard';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import SectionHeader from './SectionHeader';

interface CaseCopilotPanelProps {
  caseInputValue: string;
  onCaseInputChange: (value: string) => void;
  caseOptions: string[];
  quickPickOptions: string[];
  caseInfo: CaseInfo | null;
  insight: CaseCopilotInsight | null;
  isLoading: boolean;
  error: string | null;
  isRegenerating: boolean;
  statusMessage: string | null;
  onRegenerate: () => Promise<void> | void;
  onRefresh: () => Promise<void> | void;
  docsUrl: string;
  isLocked: boolean;
  lockMessage?: string | null;
}

export default function CaseCopilotPanel(props: CaseCopilotPanelProps) {
  const {
    caseInputValue,
    onCaseInputChange,
    caseOptions,
    quickPickOptions,
    caseInfo,
    insight,
    isLoading,
    error,
    isRegenerating,
    statusMessage,
    onRegenerate,
    onRefresh,
    docsUrl,
    isLocked,
    lockMessage,
  } = props;

  const headerActions = isLocked ? null : (
    <div className="flex items-center gap-2">
      <a
        href={docsUrl}
        target="_blank"
        rel="noreferrer"
        className="rounded-full border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
      >
        Docs
      </a>
      <button
        type="button"
        onClick={() => void onRefresh()}
        disabled={isLoading}
        className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? <InlineSpinner /> : null}
        <span>Refresh</span>
      </button>
    </div>
  );

  return (
    <section className="df-card">
      <div className="border-b border-slate-100 px-6 py-5">
        <SectionHeader
          eyebrow="AI assist"
          title="Case Copilot"
          description="Drop in a case number to see the latest summary and next actions."
          actions={headerActions}
        />
      </div>

      {isLocked ? (
        <div className="px-6 py-5">
          <DemoLockCard description={lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
        </div>
      ) : (
        <div className="space-y-4 px-6 py-5">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500" htmlFor="case-copilot-input">
              Case number
            </label>
            <input
              id="case-copilot-input"
              list="case-copilot-options"
              value={caseInputValue}
              onChange={(event) => onCaseInputChange(event.target.value)}
              placeholder="DEMO-0001"
              className="mt-2 w-full rounded-2xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
            />
            <datalist id="case-copilot-options">
              {caseOptions.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
            {quickPickOptions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {quickPickOptions.map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => onCaseInputChange(value)}
                    className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700"
                  >
                    {value}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          {caseInfo ? <CaseContextCard caseInfo={caseInfo} /> : <p className="text-sm text-slate-500">Select a case to load enforcement context.</p>}

          {statusMessage ? <p className="text-xs text-slate-500">{statusMessage}</p> : null}

          <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-4">
            {renderInsightContent({ insight, caseInfo, isLoading, error })}
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void onRegenerate()}
              disabled={!caseInfo || isRegenerating}
              className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isRegenerating ? <InlineSpinner /> : null}
              <span>Regenerate</span>
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function renderInsightContent(props: {
  insight: CaseCopilotInsight | null;
  caseInfo: CaseInfo | null;
  isLoading: boolean;
  error: string | null;
}) {
  const { insight, caseInfo, isLoading, error } = props;

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-600">
        <InlineSpinner label="Loading Case Copilot" />
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-rose-600">{error}</p>;
  }

  if (!caseInfo) {
    return <p className="text-sm text-slate-500">No case selected.</p>;
  }

  if (!insight) {
    return <p className="text-sm text-slate-500">No Case Copilot run recorded yet. Click Regenerate to queue one.</p>;
  }

  if (insight.invocationStatus && insight.invocationStatus !== 'ok') {
    return (
      <div className="space-y-2 text-sm text-slate-600">
        <p className="font-semibold text-slate-800">Last run reported an error.</p>
        {insight.errorMessage ? <p className="text-rose-600">{insight.errorMessage}</p> : null}
        <p className="text-xs text-slate-500">Generated: {formatDateTime(insight.generatedAt)}</p>
      </div>
    );
  }

  const suggestionList =
    insight.enforcementSuggestions.length > 0
      ? insight.enforcementSuggestions
      : insight.recommendedActions.map((title) => ({ title, rationale: null, nextStep: null }));

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</p>
        {insight.invocationStatus ? <StatusBadge status={insight.invocationStatus} /> : null}
      </div>
      {insight.summary ? <p className="text-sm text-slate-800">{insight.summary}</p> : <p className="text-sm text-slate-500">No summary text returned.</p>}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Risk / collectability</p>
        {typeof insight.riskValue === 'number' ? (
          <p className="mt-1 text-sm font-semibold text-slate-800">
            {insight.riskValue}/100{insight.riskLabel ? ` · ${insight.riskLabel}` : ''}
          </p>
        ) : (
          <p className="mt-1 text-sm text-slate-500">No risk rating returned.</p>
        )}
        <p className="mt-1 text-xs text-slate-500">
          {insight.riskDrivers.length > 0 ? `Drivers: ${insight.riskDrivers.join(', ')}` : 'No drivers supplied.'}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Enforcement suggestions</p>
        {suggestionList.length > 0 ? (
          <ol className="mt-2 space-y-2 text-sm text-slate-700">
            {suggestionList.map((suggestion, index) => (
              <li key={`${suggestion.title}-${index}`} className="rounded-xl border border-slate-100 bg-white px-3 py-2">
                <div className="flex items-start gap-2">
                  <span className="text-slate-400">{index + 1}.</span>
                  <div>
                    <p className="font-semibold text-slate-800">{suggestion.title}</p>
                    {suggestion.rationale ? <p className="text-xs text-slate-500">{suggestion.rationale}</p> : null}
                    {suggestion.nextStep ? (
                      <p className="text-xs font-semibold text-indigo-600">Next: {suggestion.nextStep}</p>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-sm text-slate-500">No suggestions returned.</p>
        )}
      </div>
      {insight.draftDocuments.length > 0 ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Draft documents</p>
          <div className="mt-2 space-y-3">
            {insight.draftDocuments.map((doc) => (
              <div key={doc.title} className="rounded-xl border border-slate-100 bg-white px-3 py-2 text-sm text-slate-700">
                <p className="font-semibold text-slate-800">{doc.title}</p>
                {doc.objective ? <p className="text-xs text-slate-500">{doc.objective}</p> : null}
                {doc.keyPoints.length > 0 ? (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
                    {doc.keyPoints.map((point, index) => (
                      <li key={`${doc.title}-point-${index}`}>{point}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {insight.timelineAnalysis.length > 0 ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Timeline insights</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            {insight.timelineAnalysis.map((item, index) => (
              <li key={`${item.observation}-${index}`} className="rounded-xl border border-slate-100 bg-white px-3 py-2">
                <p className="font-semibold text-slate-800">{item.observation}</p>
                <p className="text-xs text-slate-500">
                  {item.impact ? `Impact: ${item.impact}` : 'Impact: n/a'} · {item.urgency ? `Urgency: ${item.urgency}` : 'Urgency: n/a'}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {insight.contactStrategy.length > 0 ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Contact strategy</p>
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            {insight.contactStrategy.map((play, index) => (
              <li key={`${play.channel}-${play.action}-${index}`} className="rounded-xl border border-slate-100 bg-white px-3 py-2">
                <p className="font-semibold text-slate-800">
                  [{play.channel}] {play.action}
                </p>
                <p className="text-xs text-slate-500">
                  {play.cadence ? `Cadence: ${play.cadence}` : 'Cadence: ad hoc'}
                  {play.notes ? ` · ${play.notes}` : ''}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="text-xs text-slate-500">
        <p>Generated: {formatDateTime(insight.generatedAt)}</p>
        <p>
          Model: {insight.model ?? 'unknown'} · Env: {insight.env ?? 'n/a'}
        </p>
      </div>
    </div>
  );
}

function CaseContextCard({ caseInfo }: { caseInfo: CaseInfo }) {
  return (
    <div className="grid gap-3 rounded-2xl border border-slate-100 bg-white px-4 py-3 text-sm text-slate-600 md:grid-cols-2">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stage</p>
        <p className="mt-1 font-semibold text-slate-800">{caseInfo.currentStage ?? '—'}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</p>
        <p className="mt-1 font-semibold text-slate-800">{caseInfo.status ?? '—'}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Assigned to</p>
        <p className="mt-1 font-semibold text-slate-800">{caseInfo.assignedTo ?? '—'}</p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Judgment</p>
        <p className="mt-1 font-semibold text-slate-800">{formatCurrency(caseInfo.judgmentAmount)}</p>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    ok: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    error: 'bg-rose-100 text-rose-700 border-rose-200',
    pending: 'bg-amber-100 text-amber-700 border-amber-200',
    default: 'bg-slate-100 text-slate-700 border-slate-200',
  };
  const normalized = status.trim().toLowerCase();
  const classes = palette[normalized] ?? palette.default;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${classes}`}>
      {status}
    </span>
  );
}
