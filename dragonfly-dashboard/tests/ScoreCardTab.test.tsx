/**
 * Tests for ScoreCardTab Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the scorecard display with mocked score data.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScoreCardTab } from '../src/components/radar/ScoreCardTab';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

// Mock the supabaseClient
vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: false,
  supabaseClient: {
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          single: vi.fn(),
        }),
      }),
    }),
  },
}));

// Mock the useScoreCard hook
const mockScoreData = {
  id: 123,
  caseNumber: 'TEST-2024-001',
  plaintiffName: 'Test Plaintiff',
  defendantName: 'Test Defendant',
  judgmentAmount: 50000,
  totalScore: 72,
  scoreEmployment: 32,
  scoreAssets: 22,
  scoreRecency: 12,
  scoreBanking: 6,
  breakdownSum: 72,
  breakdownMatchesTotal: true,
};

vi.mock('../src/hooks/useScoreCard', () => ({
  useScoreCard: vi.fn(() => ({
    data: mockScoreData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
  SCORE_LIMITS: {
    employment: 40,
    assets: 30,
    recency: 20,
    banking: 10,
  },
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('ScoreCardTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders the total score correctly', () => {
    render(<ScoreCardTab judgmentId={123} />);

    // Should display the total score
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('/100')).toBeInTheDocument();
  });

  it('renders all score breakdown bars', () => {
    render(<ScoreCardTab judgmentId={123} />);

    // Should display all component labels
    expect(screen.getByText('Employment')).toBeInTheDocument();
    expect(screen.getByText('Assets')).toBeInTheDocument();
    expect(screen.getByText('Recency')).toBeInTheDocument();
    expect(screen.getByText('Banking')).toBeInTheDocument();
  });

  it('renders score values in format score/max', () => {
    render(<ScoreCardTab judgmentId={123} />);

    // Should display component scores
    expect(screen.getByText('32/40')).toBeInTheDocument();
    expect(screen.getByText('22/30')).toBeInTheDocument();
    expect(screen.getByText('12/20')).toBeInTheDocument();
    expect(screen.getByText('6/10')).toBeInTheDocument();
  });

  it('shows breakdown mismatch warning when breakdown does not match total', async () => {
    // Override the mock for this test
    const { useScoreCard } = await import('../src/hooks/useScoreCard');
    vi.mocked(useScoreCard).mockReturnValue({
      data: {
        ...mockScoreData,
        breakdownMatchesTotal: false,
        breakdownSum: 70,
      },
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<ScoreCardTab judgmentId={123} />);

    // Should display warning about mismatch
    expect(screen.getByText(/differs from total/i)).toBeInTheDocument();
  });
});

describe('ScoreCardTab - Loading State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading skeleton when loading', async () => {
    const { useScoreCard } = await import('../src/hooks/useScoreCard');
    vi.mocked(useScoreCard).mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: vi.fn(),
    });

    const { container } = render(<ScoreCardTab judgmentId={123} />);

    // Should have animate-pulse class for loading state
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });
});

describe('ScoreCardTab - Error State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders error message when there is an error', async () => {
    const { useScoreCard } = await import('../src/hooks/useScoreCard');
    vi.mocked(useScoreCard).mockReturnValue({
      data: null,
      loading: false,
      error: 'Failed to fetch score card',
      refetch: vi.fn(),
    });

    render(<ScoreCardTab judgmentId={123} />);

    // Should display error message
    expect(screen.getByText('Failed to fetch score card')).toBeInTheDocument();
  });
});

describe('ScoreCardTab - Empty State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no data', async () => {
    const { useScoreCard } = await import('../src/hooks/useScoreCard');
    vi.mocked(useScoreCard).mockReturnValue({
      data: null,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<ScoreCardTab judgmentId={123} />);

    // Should display empty state message
    expect(screen.getByText('No Score Data')).toBeInTheDocument();
  });
});
