import { useCallback, useEffect, useState } from 'react';
import { demoSafeRpc } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';

const RPC_NAME = 'get_enforcement_timeline' as const;

interface ActivityFeedRpcRow {
  case_id: string | null;
  source_id: string | null;
  item_kind: string | null;
  occurred_at: string | null;
  title: string | null;
  details: string | null;
  storage_path: string | null;
  file_type: string | null;
  uploaded_by: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

export type ActivityFeedKind = 'event' | 'evidence';

export interface ActivityFeedItem {
  caseId: string;
  sourceId: string;
  kind: ActivityFeedKind;
  occurredAt: string | null;
  title: string;
  details: string | null;
  storagePath: string | null;
  fileType: string | null;
  uploadedBy: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string | null;
}

export function useActivityFeed(caseId: string | null | undefined, limit: number = 40): MetricsHookResult<ActivityFeedItem[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<ActivityFeedItem[]>>(() =>
    buildInitialMetricsState<ActivityFeedItem[]>(),
  );

  const fetchTimeline = useCallback(async () => {
    if (!caseId || caseId.trim().length === 0) {
      setSnapshot(buildReadyMetricsState<ActivityFeedItem[]>([]));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const result = await demoSafeRpc<ActivityFeedRpcRow[]>(RPC_NAME, {
        case_id: caseId,
        limit_count: limit,
      });

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<ActivityFeedItem[]>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = Array.isArray(result.data) ? result.data : [];
      const normalized = rows
        .map((row) => normalizeRow(row))
        .filter((item): item is ActivityFeedItem => Boolean(item));

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (error) {
      const friendly = error instanceof Error ? error : new Error('Unable to load activity.');
      setSnapshot(buildErrorMetricsState<ActivityFeedItem[]>(friendly, { message: friendly.message }));
    }
  }, [caseId, limit]);

  useEffect(() => {
    void fetchTimeline();
  }, [fetchTimeline]);

  const refetch = useCallback(async () => {
    await fetchTimeline();
  }, [fetchTimeline]);

  return { ...snapshot, state: snapshot, refetch };
}

function normalizeRow(row: ActivityFeedRpcRow | null | undefined): ActivityFeedItem | null {
  if (!row) {
    return null;
  }

  const caseId = normalizeString(row.case_id);
  const sourceId = normalizeString(row.source_id);
  const kind = normalizeKind(row.item_kind);
  const title = normalizeString(row.title) || (kind === 'evidence' ? 'Evidence' : 'Event');

  if (!caseId || !sourceId) {
    return null;
  }

  return {
    caseId,
    sourceId,
    kind,
    occurredAt: normalizeString(row.occurred_at),
    title,
    details: normalizeString(row.details) || null,
    storagePath: normalizeString(row.storage_path) || null,
    fileType: normalizeString(row.file_type) || null,
    uploadedBy: normalizeString(row.uploaded_by) || null,
    metadata: normalizeMetadata(row.metadata),
    createdAt: normalizeString(row.created_at),
  } satisfies ActivityFeedItem;
}

function normalizeString(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  return null;
}

function normalizeKind(value: unknown): ActivityFeedKind {
  if (typeof value !== 'string') {
    return 'event';
  }
  const trimmed = value.trim().toLowerCase();
  return trimmed === 'evidence' ? 'evidence' : 'event';
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeMetadata(value: unknown): Record<string, unknown> | null {
  if (isPlainObject(value)) {
    return value;
  }
  return null;
}
