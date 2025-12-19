/**
 * dataExport.ts - Utilities for exporting dashboard data as CSV/JSON
 *
 * Provides auditability and data portability for executive reporting.
 */

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type ExportFormat = 'csv' | 'json';

export interface ExportOptions {
  /** File name without extension */
  filename: string;
  /** Export format */
  format?: ExportFormat;
  /** Include metadata header (timestamp, source) */
  includeMetadata?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// CSV GENERATION
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Escapes a value for CSV (handles commas, quotes, newlines)
 */
function escapeCSVValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  const str = String(value);
  // If contains comma, quote, or newline, wrap in quotes and escape internal quotes
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * Converts an array of objects to CSV string
 */
export function toCSV<T extends Record<string, unknown>>(
  data: T[],
  options?: { columns?: (keyof T)[]; headers?: Record<string, string> }
): string {
  if (data.length === 0) return '';

  // Get columns from first row if not specified
  const columns = options?.columns ?? (Object.keys(data[0]) as (keyof T)[]);
  const headers = options?.headers ?? {};

  // Header row
  const headerRow = columns
    .map((col) => escapeCSVValue(headers[col as string] ?? String(col)))
    .join(',');

  // Data rows
  const dataRows = data.map((row) =>
    columns.map((col) => escapeCSVValue(row[col])).join(',')
  );

  return [headerRow, ...dataRows].join('\n');
}

// ═══════════════════════════════════════════════════════════════════════════
// FILE DOWNLOAD
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Triggers a browser download of the given content
 */
export function downloadFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Exports data as CSV file download
 */
export function exportAsCSV<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions & { columns?: (keyof T)[]; headers?: Record<string, string> }
): void {
  const { filename, includeMetadata = true, columns, headers } = options;

  let content = toCSV(data, { columns, headers });

  // Add metadata header if requested
  if (includeMetadata) {
    const metadata = [
      `# Dragonfly Civil - Data Export`,
      `# Generated: ${new Date().toISOString()}`,
      `# Records: ${data.length}`,
      ``,
    ].join('\n');
    content = metadata + content;
  }

  downloadFile(content, `${filename}.csv`, 'text/csv;charset=utf-8');
}

/**
 * Exports data as JSON file download
 */
export function exportAsJSON<T>(
  data: T[],
  options: ExportOptions
): void {
  const { filename, includeMetadata = true } = options;

  const payload = includeMetadata
    ? {
        _meta: {
          source: 'Dragonfly Civil',
          generatedAt: new Date().toISOString(),
          recordCount: data.length,
        },
        data,
      }
    : data;

  const content = JSON.stringify(payload, null, 2);
  downloadFile(content, `${filename}.json`, 'application/json;charset=utf-8');
}

/**
 * Unified export function
 */
export function exportData<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions & { columns?: (keyof T)[]; headers?: Record<string, string> }
): void {
  const format = options.format ?? 'csv';

  if (format === 'json') {
    exportAsJSON(data, options);
  } else {
    exportAsCSV(data, options);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// BATCH REPORT GENERATOR
// ═══════════════════════════════════════════════════════════════════════════

export interface BatchReportData {
  id: string;
  filename: string;
  source: string;
  status: string;
  totalRows: number;
  validRows: number;
  errorRows: number;
  successRate: number;
  createdAt: string;
  completedAt?: string | null;
}

/**
 * Exports batch intake report data
 */
export function exportBatchReport(batches: BatchReportData[], format: ExportFormat = 'csv'): void {
  const timestamp = new Date().toISOString().slice(0, 10);

  exportData(batches as unknown as Record<string, unknown>[], {
    filename: `dragonfly_batch_report_${timestamp}`,
    format,
    includeMetadata: true,
    headers: {
      id: 'Batch ID',
      filename: 'Filename',
      source: 'Source',
      status: 'Status',
      totalRows: 'Total Rows',
      validRows: 'Valid Rows',
      errorRows: 'Error Rows',
      successRate: 'Success Rate (%)',
      createdAt: 'Created At',
      completedAt: 'Completed At',
    },
  });
}
