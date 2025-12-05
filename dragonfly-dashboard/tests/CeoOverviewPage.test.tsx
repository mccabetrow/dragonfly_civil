/**
 * Tests for CeoOverviewPage Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the CEO Overview page rendering with mocked hook data.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import CeoOverviewPage from '../src/pages/CeoOverviewPage';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockStatsData = {
  totalJudgments: 1247,
  totalJudgmentValue: 42850000,
  buyCandidateCount: 156,
  buyCandidateValue: 8920000,
  contingencyCount: 412,
  contingencyValue: 15600000,
  totalOffers: 127,
  offersAccepted: 42,
  offersRejected: 31,
  offersPending: 54,
  acceptanceRate: 57.5,
  totalOfferedAmount: 3200000,
  totalAcceptedAmount: 1850000,
  systemHealthy: true,
  pendingJobs: 3,
  failedJobs: 0,
  lastActivityAt: new Date().toISOString(),
};

const mockEventsData = [
  {
    id: 'evt-1',
    eventType: 'offer_accepted' as const,
    label: 'Offer Accepted',
    description: 'Offer accepted for $45,000',
    timestamp: new Date().toISOString(),
    metadata: { amount: 45000 },
    judgmentId: 123,
    entityId: null,
  },
  {
    id: 'evt-2',
    eventType: 'batch_ingested' as const,
    label: 'Batch Ingested',
    description: '127 records ingested from Simplicity',
    timestamp: new Date().toISOString(),
    metadata: { row_count: 127, source: 'Simplicity' },
    judgmentId: null,
    entityId: null,
  },
];

const mockOfferStats = {
  offersSubmitted: 127,
  offersAccepted: 42,
  offersRejected: 31,
  offersPending: 54,
  acceptanceRate: 57.5,
  totalOfferedAmount: 3200000,
  totalAcceptedAmount: 1850000,
};

vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: true,
}));

vi.mock('../src/hooks/useCeoOverviewStats', () => ({
  useCeoOverviewStats: vi.fn(() => ({
    data: mockStatsData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

vi.mock('../src/hooks/useRecentEvents', () => ({
  useRecentEvents: vi.fn(() => ({
    data: mockEventsData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

vi.mock('../src/hooks/useOfferStats', () => ({
  useOfferStats: vi.fn(() => ({
    data: mockOfferStats,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

vi.mock('../src/context/RefreshContext', () => ({
  useOnRefresh: vi.fn(),
  useRefreshBus: vi.fn(() => ({ trigger: vi.fn() })),
}));

// ═══════════════════════════════════════════════════════════════════════════
// HELPER
// ═══════════════════════════════════════════════════════════════════════════

const renderWithRouter = (component: React.ReactNode) => {
  return render(<BrowserRouter>{component}</BrowserRouter>);
};

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('CeoOverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders the page header', () => {
    renderWithRouter(<CeoOverviewPage />);

    expect(screen.getByText('CEO Overview')).toBeInTheDocument();
  });

  it('displays the total judgments KPI', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show total judgments count
    expect(screen.getByText('1,247')).toBeInTheDocument();
  });

  it('displays buy candidates section', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show buy candidates - may appear multiple times in KPI and legend
    const buyElements = screen.getAllByText(/Buy Candidates/i);
    expect(buyElements.length).toBeGreaterThan(0);
    expect(screen.getByText('156')).toBeInTheDocument();
  });

  it('displays the acceptance rate', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show acceptance rate
    expect(screen.getByText(/57\.5%/)).toBeInTheDocument();
  });

  it('shows system health status', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should indicate system is healthy
    expect(screen.getByText(/Healthy/i)).toBeInTheDocument();
  });

  it('renders the activity feed section', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show recent activity section
    expect(screen.getByText(/Recent Activity/i)).toBeInTheDocument();
  });

  it('displays recent events in the feed', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show event labels
    expect(screen.getByText('Offer Accepted')).toBeInTheDocument();
    expect(screen.getByText('Batch Ingested')).toBeInTheDocument();
  });

  it('displays event descriptions', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Should show event descriptions
    expect(screen.getByText(/\$45,000/)).toBeInTheDocument();
    expect(screen.getByText(/127 records/)).toBeInTheDocument();
  });

  it('renders currency values formatted correctly', () => {
    renderWithRouter(<CeoOverviewPage />);

    // Total portfolio value: $42.9M (shown in first KPI subtitle)
    expect(screen.getByText(/\$42\.9M/i)).toBeInTheDocument();
  });
});
