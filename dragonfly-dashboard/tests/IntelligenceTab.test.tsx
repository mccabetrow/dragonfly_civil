/**
 * Tests for IntelligenceTab Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the intelligence graph display with mocked entity data.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { IntelligenceTab } from '../src/components/radar/IntelligenceTab';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockIntelligenceData = {
  judgmentId: 123,
  entities: [
    {
      id: 'entity-1',
      type: 'person' as const,
      rawName: 'John Doe',
      normalizedName: 'john doe',
      metadata: {},
    },
    {
      id: 'entity-2',
      type: 'company' as const,
      rawName: 'ABC Corporation',
      normalizedName: 'abc corporation',
      metadata: {},
    },
    {
      id: 'entity-3',
      type: 'court' as const,
      rawName: 'New York Supreme Court',
      normalizedName: 'new york supreme court',
      metadata: { county: 'New York' },
    },
    {
      id: 'entity-4',
      type: 'address' as const,
      rawName: '123 Main Street, NY',
      normalizedName: '123 main street ny',
      metadata: {},
    },
  ],
  relationships: [
    {
      id: 'rel-1',
      sourceEntityId: 'entity-1',
      targetEntityId: 'entity-3',
      relation: 'plaintiff_in' as const,
      confidence: 1.0,
      sourceJudgmentId: 123,
    },
    {
      id: 'rel-2',
      sourceEntityId: 'entity-2',
      targetEntityId: 'entity-3',
      relation: 'defendant_in' as const,
      confidence: 1.0,
      sourceJudgmentId: 123,
    },
  ],
};

vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: false,
}));

vi.mock('../src/hooks/useIntelligence', () => ({
  useIntelligence: vi.fn(() => ({
    data: mockIntelligenceData,
    loading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

// Mock useTimeline to prevent fetch errors in EntityTimeline child component
vi.mock('../src/hooks/useTimeline', () => ({
  useTimeline: vi.fn(() => ({
    events: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useEntityTimeline: vi.fn(() => ({
    events: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useJudgmentTimeline: vi.fn(() => ({
    events: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('IntelligenceTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders entity and relationship counts', () => {
    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getByText('4')).toBeInTheDocument(); // entities count
    expect(screen.getByText('2')).toBeInTheDocument(); // relationships count
    expect(screen.getByText('entities')).toBeInTheDocument();
    expect(screen.getByText('relationships')).toBeInTheDocument();
  });

  it('renders entity names', () => {
    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('ABC Corporation')).toBeInTheDocument();
    expect(screen.getByText('New York Supreme Court')).toBeInTheDocument();
    expect(screen.getByText('123 Main Street, NY')).toBeInTheDocument();
  });

  it('renders entity type badges', () => {
    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getAllByText('Person').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Company').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Court').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Address').length).toBeGreaterThan(0);
  });

  it('groups entities by role', () => {
    render(<IntelligenceTab judgmentId={123} />);

    // Should have section headers
    expect(screen.getByText('Defendants')).toBeInTheDocument();
    expect(screen.getByText('Plaintiffs')).toBeInTheDocument();
    expect(screen.getByText('Courts')).toBeInTheDocument();
    expect(screen.getByText('Addresses')).toBeInTheDocument();
  });
});

describe('IntelligenceTab - Loading State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading skeleton when loading', async () => {
    const { useIntelligence } = await import('../src/hooks/useIntelligence');
    vi.mocked(useIntelligence).mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: vi.fn(),
    });

    const { container } = render(<IntelligenceTab judgmentId={123} />);

    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });
});

describe('IntelligenceTab - Error State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders error message when there is an error', async () => {
    const { useIntelligence } = await import('../src/hooks/useIntelligence');
    vi.mocked(useIntelligence).mockReturnValue({
      data: null,
      loading: false,
      error: 'Failed to fetch intelligence data',
      refetch: vi.fn(),
    });

    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getByText('Failed to fetch intelligence data')).toBeInTheDocument();
  });
});

describe('IntelligenceTab - Empty State', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state when no entities', async () => {
    const { useIntelligence } = await import('../src/hooks/useIntelligence');
    vi.mocked(useIntelligence).mockReturnValue({
      data: {
        judgmentId: 123,
        entities: [],
        relationships: [],
      },
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getByText('No Intelligence Data')).toBeInTheDocument();
  });

  it('renders empty state when data is null', async () => {
    const { useIntelligence } = await import('../src/hooks/useIntelligence');
    vi.mocked(useIntelligence).mockReturnValue({
      data: null,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<IntelligenceTab judgmentId={123} />);

    expect(screen.getByText('No Intelligence Data')).toBeInTheDocument();
  });
});
