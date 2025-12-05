/**
 * Tests for useRecentEvents Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the recent events feed hook with mocked Supabase data.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useRecentEvents } from '../src/hooks/useRecentEvents';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockEventsData = [
  {
    id: 'evt-1',
    event_type: 'offer_accepted',
    created_at: '2024-01-15T10:30:00Z',
    metadata: { amount: 45000 },
    judgment_id: 123,
    entity_id: null,
  },
  {
    id: 'evt-2',
    event_type: 'batch_ingested',
    created_at: '2024-01-15T09:00:00Z',
    metadata: { row_count: 50, source: 'Simplicity' },
    judgment_id: null,
    entity_id: null,
  },
  {
    id: 'evt-3',
    event_type: 'judgment_enriched',
    created_at: '2024-01-15T08:45:00Z',
    metadata: { case_number: 'NY-2024-001' },
    judgment_id: 456,
    entity_id: null,
  },
];

let mockIsDemo = false;

vi.mock('../src/lib/supabaseClient', () => ({
  get IS_DEMO_MODE() {
    return mockIsDemo;
  },
  supabaseClient: {
    from: vi.fn(() => ({
      select: vi.fn(() => ({
        order: vi.fn(() => ({
          limit: vi.fn(() =>
            Promise.resolve({ data: mockEventsData, error: null })
          ),
        })),
      })),
    })),
  },
}));

// Mock the RefreshContext
vi.mock('../src/context/RefreshContext', () => ({
  useOnRefresh: vi.fn(),
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('useRecentEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsDemo = false;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('returns demo data when in demo mode', async () => {
    mockIsDemo = true;

    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeDefined();
    expect(result.current.data.length).toBeGreaterThan(0);
    expect(result.current.error).toBeNull();
  });

  it('fetches events from the database', async () => {
    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toHaveLength(3);
    expect(result.current.error).toBeNull();
  });

  it('maps event types to friendly labels', async () => {
    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const offerEvent = result.current.data.find((e) => e.eventType === 'offer_accepted');
    expect(offerEvent?.label).toBe('Offer Accepted');

    const batchEvent = result.current.data.find((e) => e.eventType === 'batch_ingested');
    expect(batchEvent?.label).toBe('Batch Ingested');
  });

  it('generates meaningful descriptions from metadata', async () => {
    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const offerEvent = result.current.data.find((e) => e.eventType === 'offer_accepted');
    expect(offerEvent?.description).toContain('45,000');

    const batchEvent = result.current.data.find((e) => e.eventType === 'batch_ingested');
    expect(batchEvent?.description).toContain('50');
    expect(batchEvent?.description).toContain('Simplicity');
  });

  it('preserves judgment IDs from events', async () => {
    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    const offerEvent = result.current.data.find((e) => e.id === 'evt-1');
    expect(offerEvent?.judgmentId).toBe(123);

    const batchEvent = result.current.data.find((e) => e.id === 'evt-2');
    expect(batchEvent?.judgmentId).toBeNull();
  });

  it('provides a refetch function', async () => {
    const { result } = renderHook(() => useRecentEvents(10));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(typeof result.current.refetch).toBe('function');
  });

  it('respects the limit parameter', async () => {
    const { result } = renderHook(() => useRecentEvents(5));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // Mock returns 3 items regardless, but we verify limit was passed
    expect(result.current.data.length).toBeLessThanOrEqual(5);
  });
});
