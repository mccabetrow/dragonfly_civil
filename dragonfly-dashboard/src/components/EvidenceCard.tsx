import { TimelineCard, type TimelineCardProps } from './TimelineCard';

interface EvidenceCardProps extends Omit<TimelineCardProps, 'description'> {
  description?: string | null;
  storagePath?: string | null;
  fileType?: string | null;
  uploadedBy?: string | null;
  metadata?: Record<string, unknown> | null;
}

export function EvidenceCard({
  description,
  storagePath,
  fileType,
  uploadedBy,
  metadata,
  ...rest
}: EvidenceCardProps) {
  const detailRows = [
    storagePath ? { label: 'Storage path', value: storagePath } : null,
    fileType ? { label: 'File type', value: fileType } : null,
    uploadedBy ? { label: 'Uploaded by', value: uploadedBy } : null,
  ].filter(Boolean) as Array<{ label: string; value: string }>;

  return (
    <TimelineCard description={description ?? null} accent="indigo" {...rest}>
      {detailRows.length > 0 ? (
        <dl className="grid gap-x-6 gap-y-2 text-xs text-slate-500 sm:grid-cols-2">
          {detailRows.map((row) => (
            <div key={`${row.label}-${row.value}`}>
              <dt className="font-semibold text-slate-600">{row.label}</dt>
              <dd className="mt-0.5 break-all font-mono text-slate-700">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {metadata ? (
        <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
          {formatMetadata(metadata)}
        </pre>
      ) : null}
    </TimelineCard>
  );
}

function formatMetadata(metadata: Record<string, unknown>): string {
  try {
    return JSON.stringify(metadata, null, 2);
  } catch (error) {
    return '[metadata unavailable]';
  }
}
