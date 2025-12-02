import React, { useMemo } from 'react';
import { IS_DEMO_MODE } from '../lib/supabaseClient';

export interface EnforcementFlowPoint {
  bucketLabel: string;
  casesOpened: number;
  casesClosed: number;
  activeJudgmentAmount: number;
  timelineStages?: EnforcementTimelineStage[];
}

type StageStatus = 'complete' | 'pending' | 'blocked' | 'next';

export interface EnforcementTimelineStage {
  id?: string;
  stage?: string;
  occurredAt?: string | null;
  status?: StageStatus;
  details?: string | null;
  metadata?: Record<string, unknown> | null;
  title?: string | null;
  isNextAction?: boolean;
}

interface EnforcementFlowChartProps {
  data: EnforcementFlowPoint[];
}

const CHART_HEIGHT = 320;
const MIN_COLUMN_WIDTH = 88;
const MARGIN = { top: 16, right: 56, bottom: 48, left: 56 };
const OPENED_COLOR = '#2563eb';
const CLOSED_COLOR = '#94a3b8';
const LINE_COLOR = '#ea580c';
const TIMELINE_SOURCE = 'v_enforcement_timeline';

const ENFORCEMENT_STAGE_DESCRIPTORS = [
  { key: 'pre_enforcement', label: 'Pre-enforcement', description: 'Outbound calls, locating assets, and FOIL artifacts.' },
  { key: 'paperwork_filed', label: 'Paperwork filed', description: 'Stipulations, transcripts, and sheriff paperwork drafted.' },
  { key: 'levy_issued', label: 'Levy issued', description: 'Bank/income executions or other levies filed with marshals.' },
  { key: 'payment_plan', label: 'Payment plan', description: 'Defendant engaged with recurring payments on file.' },
  { key: 'waiting_payment', label: 'Awaiting payment', description: 'Collections team monitoring for promised or pending funds.' },
  { key: 'collected', label: 'Collected', description: 'Funds received and reconciled to ledger.' },
  { key: 'closed_no_recovery', label: 'Closed (no recovery)', description: 'Case retired — exhausted enforcement remedies.' },
];

const TIMELINE_TIMESTAMP = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

const numberFormatter = new Intl.NumberFormat('en-US');
const compactCurrency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
});
const weekFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const tooltipWeekFormatter = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
const fullCurrency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export const EnforcementFlowChart: React.FC<EnforcementFlowChartProps> = ({ data }) => {
  const chartModel = useMemo(() => buildChartModel(data), [data]);
  const stageNodes = useMemo(() => {
    const derived = buildStageNodes(data);
    if (derived.length > 0) {
      return derived;
    }
    return buildPlaceholderStages(IS_DEMO_MODE);
  }, [data]);

  if (!chartModel) {
    return <p className="text-sm text-slate-500">No enforcement metrics available.</p>;
  }

  const { width, innerHeight, barWidth, caseTicks, amountTicks, linePath } = chartModel;

  return (
    <div className="w-full overflow-x-auto">
      <svg
        role="img"
        aria-label="Weekly enforcement flow"
        width="100%"
        viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ minHeight: CHART_HEIGHT }}
      >
        {/* Axes */}
        <line
          x1={MARGIN.left}
          y1={MARGIN.top}
          x2={MARGIN.left}
          y2={CHART_HEIGHT - MARGIN.bottom}
          stroke="#cbd5f5"
        />
        <line
          x1={width - MARGIN.right}
          y1={MARGIN.top}
          x2={width - MARGIN.right}
          y2={CHART_HEIGHT - MARGIN.bottom}
          stroke="#cbd5f5"
        />
        <line
          x1={MARGIN.left}
          y1={CHART_HEIGHT - MARGIN.bottom}
          x2={width - MARGIN.right}
          y2={CHART_HEIGHT - MARGIN.bottom}
          stroke="#e2e8f0"
        />

        {/* Left axis ticks (cases) */}
        {caseTicks.map((tick) => (
          <g key={`case-tick-${tick}`}>
            <line
              x1={MARGIN.left - 6}
              x2={MARGIN.left}
              y1={tick.y}
              y2={tick.y}
              stroke="#cbd5f5"
            />
            <text x={MARGIN.left - 10} y={tick.y + 4} textAnchor="end" className="text-[10px] fill-slate-500">
              {tick.label}
            </text>
          </g>
        ))}

        {/* Right axis ticks (judgment amount) */}
        {amountTicks.map((tick) => (
          <g key={`amount-tick-${tick.y}`}>
            <line
              x1={width - MARGIN.right}
              x2={width - MARGIN.right + 6}
              y1={tick.y}
              y2={tick.y}
              stroke="#cbd5f5"
            />
            <text x={width - MARGIN.right + 10} y={tick.y + 4} textAnchor="start" className="text-[10px] fill-slate-500">
              {tick.label}
            </text>
          </g>
        ))}

        {/* Bars */}
        {chartModel.columns.map((col) => (
          <g key={col.key} role="listitem" aria-label={col.tooltip}>
            <title>{col.tooltip}</title>
            <rect
              x={col.x - barWidth - 2}
              y={col.openedY}
              width={barWidth}
              height={innerHeight - (col.openedY - MARGIN.top)}
              fill={OPENED_COLOR}
              rx={4}
            />
            <rect
              x={col.x + 2}
              y={col.closedY}
              width={barWidth}
              height={innerHeight - (col.closedY - MARGIN.top)}
              fill={CLOSED_COLOR}
              rx={4}
            />
            <text
              x={col.x}
              y={CHART_HEIGHT - MARGIN.bottom + 20}
              textAnchor="middle"
              className="text-[11px] fill-slate-600"
            >
              {col.label}
            </text>
          </g>
        ))}

        {/* Line */}
        <path d={linePath} fill="none" stroke={LINE_COLOR} strokeWidth={3} strokeLinecap="round" />
        {chartModel.columns.map((col) => (
          <circle key={`line-point-${col.key}`} cx={col.x} cy={col.activeY} r={4} fill={LINE_COLOR} stroke="#fff" strokeWidth={2}>
            <title>{col.tooltip}</title>
          </circle>
        ))}
      </svg>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <LegendSwatch color={OPENED_COLOR} label="Cases opened" />
        <LegendSwatch color={CLOSED_COLOR} label="Cases closed" />
        <LegendSwatch color={LINE_COLOR} label="Active judgment amount" variant="line" />
      </div>

      {stageNodes.length > 0 && (
        <div className="mt-8">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <span className="font-semibold uppercase tracking-[0.3em]">Enforcement stages</span>
            <span className="rounded-full border border-slate-200 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.25em] text-slate-500">
              {TIMELINE_SOURCE}
            </span>
          </div>
          <StageTimeline stages={stageNodes} />
        </div>
      )}
    </div>
  );
};

interface LegendSwatchProps {
  color: string;
  label: string;
  variant?: 'bar' | 'line';
}

function LegendSwatch({ color, label, variant = 'bar' }: LegendSwatchProps) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={variant === 'line' ? 'h-[2px] w-6 rounded-full'
          : 'h-3 w-3 rounded-[4px]'}
        style={{ backgroundColor: color }}
        aria-hidden
      />
      <span>{label}</span>
    </span>
  );
}

interface StageTimelineProps {
  stages: StageNode[];
}

interface StageNode {
  key: string;
  label: string;
  description: string;
  occurredAt: string | null;
  status: StageStatus;
  tooltip: string;
}

const STATUS_STYLES: Record<StageStatus, { container: string; dot: string; text: string; badge: string }> = {
  complete: {
    container: 'border-emerald-200 bg-emerald-50',
    dot: 'bg-emerald-500',
    text: 'text-emerald-700',
    badge: 'bg-emerald-600/10 text-emerald-700',
  },
  pending: {
    container: 'border-slate-200 bg-white',
    dot: 'bg-slate-300',
    text: 'text-slate-600',
    badge: 'bg-slate-100 text-slate-500',
  },
  next: {
    container: 'border-sky-200 bg-sky-50',
    dot: 'bg-sky-400',
    text: 'text-sky-800',
    badge: 'bg-sky-500/10 text-sky-700',
  },
  blocked: {
    container: 'border-rose-200 bg-rose-50',
    dot: 'bg-rose-500',
    text: 'text-rose-700',
    badge: 'bg-rose-600/10 text-rose-700',
  },
};

const STATUS_LABELS: Record<StageStatus, string> = {
  complete: 'Completed',
  pending: 'Pending',
  next: 'Next action',
  blocked: 'Blocked',
};

function StageTimeline({ stages }: StageTimelineProps) {
  if (!stages.length) {
    return null;
  }

  return (
    <div className="overflow-x-auto pb-2">
      <ol className="flex min-w-[620px] gap-4">
        {stages.map((stage) => {
          const theme = STATUS_STYLES[stage.status];
          const statusLabel = STATUS_LABELS[stage.status];
          const isNextAction = stage.status === 'next';
          return (
            <li key={stage.key} className="flex min-w-[170px] flex-col">
              <div
                className={classNames(
                  'relative mt-4 rounded-2xl border px-4 py-3 shadow-sm transition-all',
                  theme.container,
                  isNextAction && 'ring-2 ring-sky-300 ring-offset-2 ring-offset-white',
                )}
                title={stage.tooltip}
              >
                <div className="flex items-center gap-2">
                  <span className={classNames('h-2.5 w-2.5 rounded-full', theme.dot)} aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-[0.3em] text-slate-500">
                    {stage.label}
                  </span>
                </div>
                <p className={classNames('mt-2 text-sm font-semibold', theme.text)}>{statusLabel}</p>
                <p className="text-xs text-slate-500">
                  {stage.occurredAt ? formatStageTimestamp(stage.occurredAt) : 'Awaiting timeline entry'}
                </p>
                <span className={classNames('mt-3 inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em]', theme.badge)}>
                  {statusLabel}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

interface ChartModel {
  width: number;
  innerHeight: number;
  columnWidth: number;
  barWidth: number;
  columns: Array<{
    key: string;
    x: number;
    label: string;
    openedY: number;
    closedY: number;
    activeY: number;
    casesOpened: number;
    casesClosed: number;
    activeJudgmentAmount: number;
    tooltip: string;
  }>;
  caseTicks: Array<{ label: string; y: number }>;
  amountTicks: Array<{ label: string; y: number }>;
  linePath: string;
}

function buildChartModel(data: EnforcementFlowPoint[]): ChartModel | null {
  if (!Array.isArray(data) || data.length === 0) {
    return null;
  }

  const width = Math.max(data.length * MIN_COLUMN_WIDTH, 640);
  const innerHeight = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
  const columnWidth = (width - MARGIN.left - MARGIN.right) / data.length;
  const barWidth = Math.max(columnWidth * 0.25, 18);

  const maxCases = Math.max(
    ...data.map((row) => Math.max(row.casesOpened, row.casesClosed)),
    1,
  );
  const maxJudgment = Math.max(...data.map((row) => row.activeJudgmentAmount), 1);

  const columns = data.map((row, index) => {
    const x = MARGIN.left + columnWidth * index + columnWidth / 2;
    return {
      key: `${row.bucketLabel}-${index}`,
      x,
      label: formatWeek(row.bucketLabel),
      openedY: valueToY(row.casesOpened, maxCases, innerHeight) + MARGIN.top,
      closedY: valueToY(row.casesClosed, maxCases, innerHeight) + MARGIN.top,
      activeY: valueToY(row.activeJudgmentAmount, maxJudgment, innerHeight) + MARGIN.top,
      casesOpened: row.casesOpened,
      casesClosed: row.casesClosed,
      activeJudgmentAmount: row.activeJudgmentAmount,
      tooltip: buildTooltip(row),
    };
  });

  const caseTicks = buildTicks(maxCases).map((value) => ({
    label: numberFormatter.format(value),
    y: valueToY(value, maxCases, innerHeight) + MARGIN.top,
  }));

  const amountTicks = buildTicks(maxJudgment).map((value) => ({
    label: compactCurrency.format(value),
    y: valueToY(value, maxJudgment, innerHeight) + MARGIN.top,
  }));

  const linePath = columns
    .map((col, index) => `${index === 0 ? 'M' : 'L'} ${col.x} ${col.activeY}`)
    .join(' ');

  return {
    width,
    innerHeight,
    columnWidth,
    barWidth,
    columns,
    caseTicks,
    amountTicks,
    linePath,
  };
}

function buildStageNodes(points: EnforcementFlowPoint[]): StageNode[] {
  if (!Array.isArray(points) || points.length === 0) {
    return [];
  }
  const stageMap = new Map<string, { occurredAt: string | null; status: StageStatus | undefined; details: string; title: string }>();
  for (const point of points) {
    const candidates = point.timelineStages ?? [];
    for (const entry of candidates) {
      const key = normalizeStageKey(entry.stage ?? entry.id ?? '');
      if (!key) {
        continue;
      }
      const occurredAt = normalizeIso(entry.occurredAt ?? getMetadataString(entry.metadata, 'occurred_at'));
      const status = normalizeStageStatus(entry.status ?? getMetadataString(entry.metadata, 'status'));
      const note = getMetadataString(entry.metadata, 'notes') ?? getMetadataString(entry.metadata, 'details');
      const existing = stageMap.get(key);
      if (!existing || compareIso(occurredAt, existing.occurredAt) > 0) {
        stageMap.set(key, {
          occurredAt,
          status: entry.isNextAction ? 'next' : status,
          details:
            typeof entry.details === 'string' && entry.details.trim().length > 0
              ? entry.details
              : note ?? '',
          title: typeof entry.title === 'string' && entry.title.trim().length > 0 ? entry.title : '',
        });
      }
    }
  }

  let nextAssigned = false;
  return ENFORCEMENT_STAGE_DESCRIPTORS.map((descriptor) => {
    const entry = stageMap.get(descriptor.key);
    const hasTimestamp = Boolean(entry?.occurredAt);
    let status: StageStatus = entry?.status ?? (hasTimestamp ? 'complete' : 'pending');
    if (!hasTimestamp && !nextAssigned && status !== 'blocked') {
      status = 'next';
      nextAssigned = true;
    } else if (status === 'next') {
      nextAssigned = true;
    }
    return {
      key: descriptor.key,
      label: descriptor.label,
      description: descriptor.description,
      occurredAt: entry?.occurredAt ?? null,
      status,
      tooltip: buildStageTooltip(descriptor.label, entry?.occurredAt, entry?.details ?? entry?.title ?? descriptor.description),
    };
  });
}

function buildPlaceholderStages(isDemoMode: boolean): StageNode[] {
  let nextAssigned = false;
  return ENFORCEMENT_STAGE_DESCRIPTORS.map((descriptor, index) => {
    let status: StageStatus = index < 2 ? 'complete' : 'pending';
    if (!nextAssigned && status === 'pending') {
      status = 'next';
      nextAssigned = true;
    }
    return {
      key: descriptor.key,
      label: descriptor.label,
      description: descriptor.description,
      occurredAt: null,
      status,
      tooltip: `${descriptor.label}: ${isDemoMode ? 'Demo placeholder stage' : 'Awaiting timeline entry'}`,
    };
  });
}

function normalizeIso(value: unknown): string | null {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return null;
}

function normalizeStageKey(value: string): string {
  return value.trim().toLowerCase();
}

function normalizeStageStatus(value: unknown): StageStatus | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized === 'complete' || normalized === 'completed') {
    return 'complete';
  }
  if (normalized === 'pending' || normalized === 'waiting') {
    return 'pending';
  }
  if (normalized === 'blocked' || normalized === 'halted') {
    return 'blocked';
  }
  if (normalized === 'next') {
    return 'next';
  }
  return undefined;
}

function compareIso(a: string | null, b: string | null): number {
  if (a === b) {
    return 0;
  }
  if (!a) {
    return -1;
  }
  if (!b) {
    return 1;
  }
  const tsA = Date.parse(a);
  const tsB = Date.parse(b);
  if (Number.isNaN(tsA) || Number.isNaN(tsB)) {
    return 0;
  }
  return tsA === tsB ? 0 : tsA > tsB ? 1 : -1;
}

function buildStageTooltip(label: string, occurredAt: string | null | undefined, details?: string): string {
  const timestamp = occurredAt ? TIMELINE_TIMESTAMP.format(new Date(occurredAt)) : 'Awaiting timeline entry';
  return `${label}: ${timestamp}${details ? ` • ${details}` : ''}`;
}

function formatStageTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return TIMELINE_TIMESTAMP.format(date);
}

function getMetadataString(metadata: Record<string, unknown> | null | undefined, key: string): string | null {
  if (!metadata || typeof metadata !== 'object') {
    return null;
  }
  const bag = metadata as Record<string, unknown>;
  const value = bag[key];
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return null;
}

function classNames(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(' ');
}

function valueToY(value: number, max: number, height: number): number {
  if (max <= 0) {
    return height;
  }
  const ratio = Math.min(value / max, 1);
  return height - ratio * height;
}

function buildTicks(maxValue: number): number[] {
  if (!Number.isFinite(maxValue) || maxValue <= 0) {
    return [0];
  }
  const tickCount = 4;
  const rawStep = maxValue / tickCount;
  const step = Math.max(1, roundToNice(rawStep));
  const ticks: number[] = [];
  for (let value = 0; value <= maxValue; value += step) {
    ticks.push(Math.round(value));
  }
  if (ticks[ticks.length - 1] !== Math.round(maxValue)) {
    ticks.push(Math.round(maxValue));
  }
  return Array.from(new Set(ticks));
}

function roundToNice(value: number): number {
  if (value <= 1) {
    return 1;
  }
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const residual = value / magnitude;
  if (residual >= 5) {
    return 5 * magnitude;
  }
  if (residual >= 2) {
    return 2 * magnitude;
  }
  return magnitude;
}

function formatWeek(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return weekFormatter.format(date);
}

function buildTooltip(row: EnforcementFlowPoint): string {
  const formattedWeek = formatTooltipWeek(row.bucketLabel);
  const opened = numberFormatter.format(row.casesOpened);
  const closed = numberFormatter.format(row.casesClosed);
  const active = fullCurrency.format(row.activeJudgmentAmount);
  return `${formattedWeek}: ${opened} opened • ${closed} closed • Active ${active}`;
}

function formatTooltipWeek(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return tooltipWeekFormatter.format(date);
}

export default EnforcementFlowChart;
