/**
 * Financial Terminal Formatters
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Utilities for formatting currency, dates, and numbers in the dashboard.
 * Designed for monospace column alignment in financial terminal style UIs.
 */

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const currencyFormatterWithCents = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

/**
 * Format a value as USD currency (whole dollars).
 * Returns '—' for invalid/null values.
 */
export function formatCurrency(value: number | string | null | undefined): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      return '—';
    }
    return currencyFormatter.format(value);
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return currencyFormatter.format(parsed);
    }
  }
  return '—';
}

/**
 * Format a value as USD currency with cents (2 decimal places).
 * Suitable for precise financial displays.
 */
export function formatCurrencyPrecise(value: number | string | null | undefined): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      return '—';
    }
    return currencyFormatterWithCents.format(value);
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return currencyFormatterWithCents.format(parsed);
    }
  }
  return '—';
}

/**
 * Format currency in compact notation (K/M/B).
 * Useful for KPI cards and summary displays.
 */
export function formatCurrencyCompact(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  if (value >= 1_000_000_000) {
    return `$${(value / 1_000_000_000).toFixed(1)}B`;
  }
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `$${Math.round(value / 1_000)}K`;
  }
  return `$${value.toFixed(0)}`;
}

/**
 * Format a date/time value for display.
 * Returns '—' for invalid/null values.
 */
export function formatDateTime(value: string | null | undefined): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return '—';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  return dateTimeFormatter.format(parsed);
}

/**
 * Format a number with locale-aware thousand separators.
 */
export function formatNumber(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return new Intl.NumberFormat('en-US').format(value);
}

/**
 * Format a percentage value (0-100 scale).
 */
export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return `${value.toFixed(decimals)}%`;
}
