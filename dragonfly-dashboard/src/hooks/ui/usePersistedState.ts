/**
 * usePersistedState - localStorage-backed state with type safety
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Persists state to localStorage so user preferences (filters, sort order)
 * survive page refreshes. Falls back gracefully if localStorage is unavailable.
 *
 * Usage:
 * ───────────────────────────────────────────────────────────────────────────
 * const [tier, setTier] = usePersistedState<TierFilter>('collectability_tier', 'All');
 * const [search, setSearch] = usePersistedState('collectability_search', '');
 * ───────────────────────────────────────────────────────────────────────────
 */

import { useCallback, useState } from 'react';

/** Storage key prefix for all Dragonfly persisted state */
const STORAGE_PREFIX = 'df_';

/**
 * Build the full localStorage key with prefix
 */
function buildStorageKey(key: string): string {
  return `${STORAGE_PREFIX}${key}`;
}

/**
 * Safely read from localStorage with JSON parsing
 */
function readFromStorage<T>(key: string): T | undefined {
  try {
    const fullKey = buildStorageKey(key);
    const raw = localStorage.getItem(fullKey);
    if (raw === null) {
      return undefined;
    }
    return JSON.parse(raw) as T;
  } catch {
    // localStorage unavailable or corrupted data
    return undefined;
  }
}

/**
 * Safely write to localStorage with JSON serialization
 */
function writeToStorage<T>(key: string, value: T): void {
  try {
    const fullKey = buildStorageKey(key);
    localStorage.setItem(fullKey, JSON.stringify(value));
  } catch {
    // localStorage unavailable or quota exceeded - fail silently
  }
}

/**
 * Remove a key from localStorage
 */
function removeFromStorage(key: string): void {
  try {
    const fullKey = buildStorageKey(key);
    localStorage.removeItem(fullKey);
  } catch {
    // Ignore errors
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export interface UsePersistedStateReturn<T> {
  /** Current value */
  value: T;
  /** Update the value (persists to localStorage) */
  setValue: (newValue: T | ((prev: T) => T)) => void;
  /** Reset to default value and clear localStorage */
  reset: () => void;
}

/**
 * useState-like hook that persists value to localStorage
 *
 * @param key - Unique key (will be prefixed with 'df_')
 * @param defaultValue - Initial value if nothing is stored
 * @returns Tuple of [value, setValue] like useState, plus reset method
 *
 * @example
 * // Simple usage
 * const [tier, setTier] = usePersistedState<'A' | 'B' | 'C' | 'All'>('tier', 'All');
 *
 * // With object shape
 * const [filters, setFilters] = usePersistedState('filters', { tier: 'All', search: '' });
 */
export function usePersistedState<T>(
  key: string,
  defaultValue: T
): [T, (newValue: T | ((prev: T) => T)) => void, () => void] {
  // Initialize from localStorage or use default
  const [value, setValueInternal] = useState<T>(() => {
    const stored = readFromStorage<T>(key);
    return stored !== undefined ? stored : defaultValue;
  });

  // Wrapped setter that also persists to localStorage
  const setValue = useCallback(
    (newValue: T | ((prev: T) => T)) => {
      setValueInternal((prev) => {
        const resolved = typeof newValue === 'function' ? (newValue as (prev: T) => T)(prev) : newValue;
        writeToStorage(key, resolved);
        return resolved;
      });
    },
    [key]
  );

  // Reset to default and clear storage
  const reset = useCallback(() => {
    removeFromStorage(key);
    setValueInternal(defaultValue);
  }, [key, defaultValue]);

  return [value, setValue, reset];
}

// ═══════════════════════════════════════════════════════════════════════════
// CONVENIENCE EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Pre-built keys for common Dragonfly filter state
 * Use these to ensure consistent naming across components
 */
export const PERSISTED_KEYS = {
  /** Collectability page tier filter */
  COLLECTABILITY_TIER: 'collectability_tier',
  /** Collectability page search term */
  COLLECTABILITY_SEARCH: 'collectability_search',
  /** Collectability page sort column */
  COLLECTABILITY_SORT_KEY: 'collectability_sort_key',
  /** Collectability page sort direction */
  COLLECTABILITY_SORT_DIR: 'collectability_sort_dir',
  /** Cases page tier filter */
  CASES_TIER: 'cases_tier',
  /** Cases page search term */
  CASES_SEARCH: 'cases_search',
} as const;

export default usePersistedState;
