/**
 * Tests for useCeoOverviewStats Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the CEO overview statistics hook with mocked Supabase data.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useCeoOverviewStats } from '../src/hooks/useCeoOverviewStats';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockRadarData = [
  { id: 1, offer_strategy: 'BUY_CANDIDATE', judgment_amount: 50000 },
  { id: 2, offer_strategy: 'BUY_CANDIDATE', judgment_amount: 75000 },
  { id: 3, offer_strategy: 'CONTINGENCY', judgment_amount: 30000 },
  { id: 4, offer_strategy: 'CONTINGENCY', judgment_amount: 45000 },
  { id: 5, offer_strategy: 'DEFER', judgment_amount: 10000 },
];

const mockOfferData = [
  { status: 'accepted', offered_amount: 25000, accepted_amount: 25000 },
  { status: 'accepted', offered_amount: 30000, accepted_amount: 30000 },
  { status: 'rejected', offered_amount: 20000, accepted_amount: 0 },
  { status: 'pending', offered_amount: 35000, accepted_amount: 0 },
];

const mockHealthData = {
  pending_jobs: 5,
  failed_jobs: 1,
  last_job_updated_at: '2024-01-15T10:30:00Z',
};

let mockIsDemo = false;

vi.mock('../src/lib/supabaseClient', () => ({
  get IS_DEMO_MODE() {
    return mockIsDemo;
  },
  supabaseClient: {
    from: vi.fn((table: string) => {
      if (table === 'v_radar') {
        return {
          select: vi.fn(() => Promise.resolve({ data: mockRadarData, error: null })),
        };
      }
      if (table === 'v_offer_stats') {
        return {
          select: vi.fn(() => Promise.resolve({ data: mockOfferData, error: null })),
        };
      }
      if (table === 'v_enrichment_health') {
        return {
          select: vi.fn(() => ({
            limit: vi.fn(() => ({
              single: vi.fn(() => Promise.resolve({ data: mockHealthData, error: null })),
            })),
          })),
        };
      }
      return {
        select: vi.fn(() => Promise.resolve({ data: [], error: null })),
      };
    }),
  },
}));

// Mock the RefreshContext
vi.mock('../src/context/RefreshContext', () => ({
  useOnRefresh: vi.fn(),
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('useCeoOverviewStats', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsDemo = false;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('returns demo data when in demo mode', async () => {
    mockIsDemo = true;

    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeDefined();
    expect(result.current.data?.totalJudgments).toBe(1247);
    expect(result.current.data?.buyCandidateCount).toBe(156);
    expect(result.current.error).toBeNull();
  });

  it('calculates total judgments correctly', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 5 total judgments in mockRadarData
    expect(result.current.data?.totalJudgments).toBe(5);
  });

  it('calculates buy candidate count and value correctly', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 2 BUY_CANDIDATE rows: 50000 + 75000 = 125000
    expect(result.current.data?.buyCandidateCount).toBe(2);
    expect(result.current.data?.buyCandidateValue).toBe(125000);
  });

  it('calculates contingency count and value correctly', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 2 CONTINGENCY rows: 30000 + 45000 = 75000
    expect(result.current.data?.contingencyCount).toBe(2);
    expect(result.current.data?.contingencyValue).toBe(75000);
  });

  it('calculates acceptance rate correctly', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // 2 accepted, 1 rejected = 2/3 = 66.67%
    const expectedRate = (2 / 3) * 100;
    expect(result.current.data?.acceptanceRate).toBeCloseTo(expectedRate, 1);
    expect(result.current.data?.offersAccepted).toBe(2);
    expect(result.current.data?.offersRejected).toBe(1);
    expect(result.current.data?.offersPending).toBe(1);
  });

  it('includes system health data', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data?.pendingJobs).toBe(5);
    expect(result.current.data?.failedJobs).toBe(1);
    expect(result.current.data?.systemHealthy).toBe(false); // failed_jobs > 0
  });

  it('provides a refetch function', async () => {
    const { result } = renderHook(() => useCeoOverviewStats());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(typeof result.current.refetch).toBe('function');
  });
});
