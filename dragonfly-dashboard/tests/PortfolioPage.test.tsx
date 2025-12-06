/**
 * Tests for Portfolio Page
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the Portfolio page rendering with mocked hook data.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import PortfolioPage from '../src/pages/finance/Portfolio';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockPortfolioData = {
  totalAum: 48_750_000,
  actionableLiquidity: 22_340_000,
  pipelineValue: 8_920_000,
  offersOutstanding: 54,
  totalJudgments: 1247,
  actionableCount: 523,
  tierAllocation: [
    { tier: 'A' as const, label: 'Tier A (80+)', amount: 12_500_000, count: 187, color: '#10b981' },
    { tier: 'B' as const, label: 'Tier B (50-79)', amount: 18_750_000, count: 412, color: '#3b82f6' },
    { tier: 'C' as const, label: 'Tier C (<50)', amount: 17_500_000, count: 648, color: '#6b7280' },
  ],
  topCounties: [
    { county: 'Nassau County', amount: 8_200_000, count: 156 },
    { county: 'Suffolk County', amount: 6_850_000, count: 134 },
    { county: 'Westchester County', amount: 5_420_000, count: 98 },
    { county: 'Kings County', amount: 4_980_000, count: 112 },
    { county: 'Queens County', amount: 4_150_000, count: 89 },
  ],
};

vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: true,
}));

vi.mock('../src/hooks/usePortfolioStats', () => ({
  usePortfolioStats: vi.fn(() => ({
    data: mockPortfolioData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

vi.mock('../src/context/RefreshContext', () => ({
  useOnRefresh: vi.fn(),
}));

// ═══════════════════════════════════════════════════════════════════════════
// HELPER
// ═══════════════════════════════════════════════════════════════════════════

const renderPage = () => {
  return render(
    <BrowserRouter>
      <PortfolioPage />
    </BrowserRouter>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('PortfolioPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Page Header', () => {
    it('renders the page title', () => {
      renderPage();
      expect(screen.getByText('Portfolio')).toBeInTheDocument();
    });

    it('renders the page subtitle', () => {
      renderPage();
      expect(screen.getByText('Assets Under Management & Financial Metrics')).toBeInTheDocument();
    });
  });

  describe('KPI Cards', () => {
    it('renders Total AUM KPI', () => {
      renderPage();
      expect(screen.getByText('Total AUM')).toBeInTheDocument();
      expect(screen.getByText('$48.8M')).toBeInTheDocument();
    });

    it('renders Actionable Liquidity KPI', () => {
      renderPage();
      expect(screen.getByText('Actionable Liquidity')).toBeInTheDocument();
      expect(screen.getByText('$22.3M')).toBeInTheDocument();
    });

    it('renders Pipeline Value KPI', () => {
      renderPage();
      expect(screen.getByText('Pipeline Value')).toBeInTheDocument();
      expect(screen.getByText('$8.9M')).toBeInTheDocument();
    });

    it('renders Offers Outstanding KPI', () => {
      renderPage();
      expect(screen.getByText('Offers Outstanding')).toBeInTheDocument();
      expect(screen.getByText('54')).toBeInTheDocument();
    });

    it('renders judgment count subtitle', () => {
      renderPage();
      expect(screen.getByText('1,247 judgments')).toBeInTheDocument();
    });

    it('renders actionable count subtitle', () => {
      renderPage();
      expect(screen.getByText('523 cases (score > 40)')).toBeInTheDocument();
    });
  });

  describe('Score Tier Allocation Chart', () => {
    it('renders chart title', () => {
      renderPage();
      expect(screen.getByText('Score Tier Allocation')).toBeInTheDocument();
    });

    it('renders chart description', () => {
      renderPage();
      expect(screen.getByText('Portfolio breakdown by collectability tier')).toBeInTheDocument();
    });

    it('renders tier labels in legend or chart', () => {
      renderPage();
      // Tremor Legend should render these
      expect(screen.getByText('Tier A (80+)')).toBeInTheDocument();
      expect(screen.getByText('Tier B (50-79)')).toBeInTheDocument();
      expect(screen.getByText('Tier C (<50)')).toBeInTheDocument();
    });

    it('renders tier case counts', () => {
      renderPage();
      expect(screen.getByText('187 cases')).toBeInTheDocument();
      expect(screen.getByText('412 cases')).toBeInTheDocument();
      expect(screen.getByText('648 cases')).toBeInTheDocument();
    });
  });

  describe('Top Counties Chart', () => {
    it('renders chart title', () => {
      renderPage();
      expect(screen.getByText('Top 5 Counties')).toBeInTheDocument();
    });

    it('renders chart description', () => {
      renderPage();
      expect(screen.getByText('By total judgment amount')).toBeInTheDocument();
    });

    it('renders top 3 counties in detail list', () => {
      renderPage();
      expect(screen.getByText('1. Nassau County')).toBeInTheDocument();
      expect(screen.getByText('2. Suffolk County')).toBeInTheDocument();
      expect(screen.getByText('3. Westchester County')).toBeInTheDocument();
    });
  });

  describe('Portfolio Summary', () => {
    it('renders portfolio summary card', () => {
      renderPage();
      expect(screen.getByText('Portfolio Summary')).toBeInTheDocument();
    });

    it('renders actionable ratio', () => {
      renderPage();
      expect(screen.getByText('Actionable Ratio')).toBeInTheDocument();
      // 22.34M / 48.75M ≈ 45.8%
      expect(screen.getByText('45.8%')).toBeInTheDocument();
    });
  });
});

describe('PortfolioPage Loading State', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('renders loading skeleton when data is loading', async () => {
    vi.doMock('../src/hooks/usePortfolioStats', () => ({
      usePortfolioStats: vi.fn(() => ({
        data: null,
        loading: true,
        error: null,
        refetch: vi.fn(),
      })),
    }));

    // Re-import after mock
    const { default: PortfolioPageMocked } = await import('../src/pages/finance/Portfolio');
    
    render(
      <BrowserRouter>
        <PortfolioPageMocked />
      </BrowserRouter>
    );

    // Should render page header even in loading state
    expect(screen.getByText('Portfolio')).toBeInTheDocument();
    // Should not render KPI values
    expect(screen.queryByText('$48.8M')).not.toBeInTheDocument();
  });
});

describe('PortfolioPage Error State', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('renders error message and retry button', async () => {
    const mockRefetch = vi.fn();
    vi.doMock('../src/hooks/usePortfolioStats', () => ({
      usePortfolioStats: vi.fn(() => ({
        data: null,
        loading: false,
        error: 'Failed to load portfolio stats',
        refetch: mockRefetch,
      })),
    }));

    const { default: PortfolioPageMocked } = await import('../src/pages/finance/Portfolio');
    
    render(
      <BrowserRouter>
        <PortfolioPageMocked />
      </BrowserRouter>
    );

    expect(screen.getByText('Failed to load portfolio stats')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });
});

describe('PortfolioPage Route', () => {
  it('renders at /finance/portfolio path', () => {
    // This test verifies the component itself renders
    // Route wiring is tested by navigation or e2e tests
    renderPage();
    expect(screen.getByText('Portfolio')).toBeInTheDocument();
  });
});
