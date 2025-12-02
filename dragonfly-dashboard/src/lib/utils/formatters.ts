/**
 * Unified formatters for the Dragonfly Civil Operations Console.
 * Use these instead of creating local formatters in components.
 */

// ═══════════════════════════════════════════════════════════════════════════
// CURRENCY FORMATTING
// ═══════════════════════════════════════════════════════════════════════════

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

/**
 * Format a number as USD currency (no cents).
 * Returns '—' for null/undefined.
 */
export function formatCurrency(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return currencyFormatter.format(value);
}

/**
 * Format a number as USD currency with cents.
 */
export function formatCurrencyWithCents(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return currencyFormatterWithCents.format(value);
}

/**
 * Format a number as compact currency (e.g., "$1.2M").
 */
export function formatCurrencyCompact(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(0)}K`;
  }
  return currencyFormatter.format(value);
}

// ═══════════════════════════════════════════════════════════════════════════
// NUMBER FORMATTING
// ═══════════════════════════════════════════════════════════════════════════

const numberFormatter = new Intl.NumberFormat('en-US');

/**
 * Format a number with thousands separators.
 */
export function formatNumber(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  return numberFormatter.format(value);
}

/**
 * Format a number as compact (e.g., "1.2K").
 */
export function formatNumberCompact(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return numberFormatter.format(value);
}

/**
 * Format a percentage (0-100 or 0-1 depending on isDecimal).
 */
export function formatPercent(
  value: number | null | undefined,
  options?: { decimals?: number; isDecimal?: boolean }
): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  
  const { decimals = 0, isDecimal = false } = options ?? {};
  const percentage = isDecimal ? value * 100 : value;
  return `${percentage.toFixed(decimals)}%`;
}

// ═══════════════════════════════════════════════════════════════════════════
// DATE/TIME FORMATTING
// ═══════════════════════════════════════════════════════════════════════════

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

const shortDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
});

const timeFormatter = new Intl.DateTimeFormat('en-US', {
  timeStyle: 'short',
});

/**
 * Parse a date string or Date object into a Date.
 * Returns null if invalid.
 */
function parseDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Format as date only (e.g., "Jan 15, 2025").
 */
export function formatDate(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  return date ? dateFormatter.format(date) : '—';
}

/**
 * Format as date and time (e.g., "Jan 15, 2025, 3:30 PM").
 */
export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  return date ? dateTimeFormatter.format(date) : '—';
}

/**
 * Format as short date (e.g., "Jan 15").
 */
export function formatShortDate(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  return date ? shortDateFormatter.format(date) : '—';
}

/**
 * Format as time only (e.g., "3:30 PM").
 */
export function formatTime(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  return date ? timeFormatter.format(date) : '—';
}

/**
 * Format as relative time (e.g., "2 hours ago", "in 3 days").
 */
export function formatRelativeTime(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';

  const now = Date.now();
  const diff = now - date.getTime();
  const absDiff = Math.abs(diff);
  const isPast = diff > 0;

  const seconds = Math.floor(absDiff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);

  const format = (value: number, unit: string) => {
    const plural = value !== 1 ? 's' : '';
    return isPast
      ? `${value} ${unit}${plural} ago`
      : `in ${value} ${unit}${plural}`;
  };

  if (years > 0) return format(years, 'year');
  if (months > 0) return format(months, 'month');
  if (weeks > 0) return format(weeks, 'week');
  if (days > 0) return format(days, 'day');
  if (hours > 0) return format(hours, 'hour');
  if (minutes > 0) return format(minutes, 'minute');
  return 'just now';
}

/**
 * Format age in days.
 */
export function formatAgeDays(days: number | null | undefined): string {
  if (typeof days !== 'number' || !Number.isFinite(days)) {
    return '—';
  }
  
  if (days < 0) return '—';
  if (days === 0) return 'Today';
  if (days === 1) return '1 day';
  if (days < 7) return `${days} days`;
  if (days < 30) {
    const weeks = Math.floor(days / 7);
    return weeks === 1 ? '1 week' : `${weeks} weeks`;
  }
  if (days < 365) {
    const months = Math.floor(days / 30);
    return months === 1 ? '1 month' : `${months} months`;
  }
  const years = Math.floor(days / 365);
  return years === 1 ? '1 year' : `${years} years`;
}

// ═══════════════════════════════════════════════════════════════════════════
// TEXT FORMATTING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Truncate text to a maximum length with ellipsis.
 */
export function truncate(text: string | null | undefined, maxLength: number): string {
  if (!text) return '—';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}

/**
 * Title case a string (e.g., "hello world" → "Hello World").
 */
export function titleCase(text: string | null | undefined): string {
  if (!text) return '—';
  return text
    .toLowerCase()
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Format a case number for display.
 */
export function formatCaseNumber(caseNumber: string | null | undefined): string {
  return caseNumber?.trim() || '—';
}

/**
 * Format a phone number for display.
 */
export function formatPhone(phone: string | null | undefined): string {
  if (!phone) return '—';
  
  // Remove all non-digits
  const digits = phone.replace(/\D/g, '');
  
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 11 && digits.startsWith('1')) {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  
  return phone; // Return as-is if format is unknown
}

// ═══════════════════════════════════════════════════════════════════════════
// BOOLEAN/STATUS FORMATTING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Format a boolean as Yes/No.
 */
export function formatYesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value ? 'Yes' : 'No';
}

/**
 * Return a placeholder for null/undefined values.
 */
export function placeholder(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  return String(value);
}
