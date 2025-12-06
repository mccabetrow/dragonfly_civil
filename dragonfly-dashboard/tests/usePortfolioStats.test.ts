/**
 * Tests for usePortfolioStats Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the portfolio stats aggregation hook.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { usePortfolioStats } from '../src/hooks/usePortfolioStats';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockRadarData = [
  { id: 1, judgment_amount: 50000, collectability_score: 85, offer_strategy: 'BUY_CANDIDATE', county: 'Nassau County' },
  { id: 2, judgment_amount: 75000, collectability_score: 65, offer_strategy: 'CONTINGENCY', county: 'Nassau County' },
  { id: 3, judgment_amount: 30000, collectability_score: 45, offer_strategy: 'CONTINGENCY', county: 'Suffolk County' },
  { id: 4, judgment_amount: 25000, collectability_score: 35, offer_strategy: 'SKIP', county: 'Suffolk County' },
  { id: 5, judgment_amount: 100000, collectability_score: 90, offer_strategy: 'BUY_CANDIDATE', county: 'Westchester County' },
];

const mockOffersData = [
  { status: 'pending' },
  { status: 'negotiation' },
  { status: 'pending' },
];

vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: false,
  supabaseClient: {
    from: vi.fn((table: string) => {
      if (table === 'v_radar') {
        return {
          select: vi.fn().mockResolvedValue({
            data: mockRadarData,
            error: null,
          }),
        };
      }
      if (table === 'v_offer_stats') {
        return {
          select: vi.fn().mockReturnValue({
            in: vi.fn().mockResolvedValue({
              data: mockOffersData,
              error: null,
            }),
          }),
        };
      }
      return {
        select: vi.fn().mockResolvedValue({ data: [], error: null }),
      };
    }),
  },
}));

vi.mock('../src/context/RefreshContext', () => ({
  useOnRefresh: vi.fn(),
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('usePortfolioStats', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('returns loading state initially', () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    // Initially should be loading (before data arrives)
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBe(null);
    expect(result.current.error).toBe(null);
  });

  it('calculates totalAum as sum of all judgment amounts', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    // Total: 50000 + 75000 + 30000 + 25000 + 100000 = 280000
    expect(result.current.data?.totalAum).toBe(280000);
  });

  it('calculates actionableLiquidity for scores > 40', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    // Scores > 40: 85 (50k), 65 (75k), 45 (30k), 90 (100k) = 255000
    expect(result.current.data?.actionableLiquidity).toBe(255000);
    expect(result.current.data?.actionableCount).toBe(4);
  });

  it('calculates pipelineValue for BUY_CANDIDATE strategy', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    // BUY_CANDIDATE: 50000 + 100000 = 150000
    expect(result.current.data?.pipelineValue).toBe(150000);
  });

  it('counts offersOutstanding from pending/negotiation offers', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    expect(result.current.data?.offersOutstanding).toBe(3);
  });

  it('calculates tier allocation correctly', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    const tiers = result.current.data?.tierAllocation ?? [];
    
    // Tier A (80+): ids 1 (50k, 85), 5 (100k, 90) = 150000, 2 cases
    const tierA = tiers.find(t => t.tier === 'A');
    expect(tierA?.amount).toBe(150000);
    expect(tierA?.count).toBe(2);
    
    // Tier B (50-79): id 2 (75k, 65) = 75000, 1 case
    const tierB = tiers.find(t => t.tier === 'B');
    expect(tierB?.amount).toBe(75000);
    expect(tierB?.count).toBe(1);
    
    // Tier C (<50): ids 3 (30k, 45), 4 (25k, 35) = 55000, 2 cases
    const tierC = tiers.find(t => t.tier === 'C');
    expect(tierC?.amount).toBe(55000);
    expect(tierC?.count).toBe(2);
  });

  it('aggregates top counties correctly', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    const counties = result.current.data?.topCounties ?? [];
    
    // Nassau: 50k + 75k = 125k
    // Westchester: 100k
    // Suffolk: 30k + 25k = 55k
    expect(counties[0].county).toBe('Nassau County');
    expect(counties[0].amount).toBe(125000);
    expect(counties[0].count).toBe(2);
    
    expect(counties[1].county).toBe('Westchester County');
    expect(counties[1].amount).toBe(100000);
    expect(counties[1].count).toBe(1);
    
    expect(counties[2].county).toBe('Suffolk County');
    expect(counties[2].amount).toBe(55000);
    expect(counties[2].count).toBe(2);
  });

  it('provides refetch function', async () => {
    const { result } = renderHook(() => usePortfolioStats());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    expect(typeof result.current.refetch).toBe('function');
  });
});

describe('usePortfolioStats in demo mode', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.doMock('../src/lib/supabaseClient', () => ({
      IS_DEMO_MODE: true,
      supabaseClient: {},
    }));
    vi.mock('../src/context/RefreshContext', () => ({
      useOnRefresh: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('returns demo data when IS_DEMO_MODE is true', async () => {
    // Re-import after mock
    const { usePortfolioStats: usePortfolioStatsMocked } = await import('../src/hooks/usePortfolioStats');
    const { result } = renderHook(() => usePortfolioStatsMocked());
    
    await waitFor(() => expect(result.current.loading).toBe(false));
    
    // Demo data has specific values
    expect(result.current.data?.totalAum).toBe(48_750_000);
    expect(result.current.data?.offersOutstanding).toBe(54);
  });
});
