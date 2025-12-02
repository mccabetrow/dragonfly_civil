import { useActivityFeed } from '../hooks/useActivityFeed';
import type { ActivityFeedItem } from '../hooks/useActivityFeed';
import { InlineSpinner } from './InlineSpinner';
import { TimelineCard } from './TimelineCard';
import { EvidenceCard } from './EvidenceCard';

interface ActivityFeedProps {
  caseId: string | null | undefined;
  limit?: number;
  emptyMessage?: string;
  className?: string;
}

export function ActivityFeed({ caseId, limit = 40, emptyMessage = 'No activity recorded yet.', className }: ActivityFeedProps) {
  if (!caseId || caseId.trim().length === 0) {
    return <p className="text-sm text-slate-500">Select a case to preview recent activity.</p>;
  }

  const { status, data, errorMessage, lockMessage, refetch } = useActivityFeed(caseId, limit);
  const items = data ?? [];

  if (status === 'demo_locked') {
    return <p className="text-sm text-slate-500">{lockMessage ?? 'Activity stream is hidden in demo environments.'}</p>;
  }

  if (status === 'loading' && items.length === 0) {
    return (
      <p className="inline-flex items-center gap-2 text-sm text-slate-500">
        <InlineSpinner />
        Loading activity…
      </p>
    );
  }

  if (status === 'error') {
    return (
      <div className="space-y-2 text-sm text-slate-600">
        <p>{errorMessage ?? 'Unable to load activity feed.'}</p>
        <button
          type="button"
          onClick={() => {
            void refetch();
          }}
          className="text-sm font-semibold text-indigo-600 hover:text-indigo-800"
        >
          Retry
        </button>
      </div>
    );
  }

  if (items.length === 0) {
    return <p className="text-sm text-slate-500">{emptyMessage}</p>;
  }

  return (
    <div className={`space-y-3 ${className ?? ''}`.trim()}>
      {items.map((item) =>
        item.kind === 'evidence' ? (
          <EvidenceCard
            key={item.sourceId}
            title={item.title}
            timestamp={item.occurredAt}
            description={item.details}
            storagePath={item.storagePath}
            fileType={item.fileType}
            uploadedBy={item.uploadedBy}
            metadata={item.metadata}
          />
        ) : (
          <TimelineCard
            key={item.sourceId}
            title={item.title}
            timestamp={item.occurredAt}
            description={item.details}
            accent="emerald"
          >
            {renderMetadataList(item)}
          </TimelineCard>
        ),
      )}
    </div>
  );
}

function renderMetadataList(item: ActivityFeedItem) {
  const entries = extractMetadataEntries(item.metadata);
  if (entries.length === 0) {
    return null;
  }

  return (
    <dl className="grid gap-x-6 gap-y-2 text-xs text-slate-500 sm:grid-cols-2">
      {entries.map((entry) => (
        <div key={entry.label}>
          <dt className="font-semibold text-slate-600">{entry.label}</dt>
          <dd className="mt-0.5 break-words text-slate-700">{entry.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function extractMetadataEntries(metadata: Record<string, unknown> | null): Array<{ label: string; value: string }> {
  if (!metadata) {
    return [];
  }

  const entries: Array<{ label: string; value: string }> = [];
  for (const [key, value] of Object.entries(metadata)) {
    if (entries.length >= 4) {
      break;
    }
    const label = key.replace(/[_-]+/g, ' ');
    entries.push({ label: capitalize(label), value: formatValue(value) });
  }
  return entries;
}

function formatValue(value: unknown): string {
  if (value == null) {
    return '—';
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : '—';
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch (error) {
    return '[unavailable]';
  }
}

function capitalize(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}
