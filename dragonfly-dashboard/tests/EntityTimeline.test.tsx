/**
 * EntityTimeline Component Tests
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests for the EntityTimeline component.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EntityTimeline } from '../src/components/radar/EntityTimeline';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Sample timeline data
const mockTimelineResponse = {
  events: [
    {
      id: '123e4567-e89b-12d3-a456-426614174000',
      event_type: 'new_judgment',
      created_at: '2025-01-15T10:30:00Z',
      payload: { amount: '5000', county: 'New York' },
      summary: 'Judgment created for $5000 in New York',
    },
    {
      id: '223e4567-e89b-12d3-a456-426614174001',
      event_type: 'job_found',
      created_at: '2025-01-16T14:00:00Z',
      payload: { employer_name: 'ACME Corp' },
      summary: 'Job found at ACME Corp',
    },
    {
      id: '323e4567-e89b-12d3-a456-426614174002',
      event_type: 'offer_made',
      created_at: '2025-01-17T09:15:00Z',
      payload: { amount: '2500', cents_on_dollar: 50 },
      summary: 'Offer made: $2500 (50¢ on the dollar)',
    },
    {
      id: '423e4567-e89b-12d3-a456-426614174003',
      event_type: 'offer_accepted',
      created_at: '2025-01-18T16:30:00Z',
      payload: { amount: '2500' },
      summary: 'Offer ACCEPTED for $2500',
    },
    {
      id: '523e4567-e89b-12d3-a456-426614174004',
      event_type: 'packet_sent',
      created_at: '2025-01-19T11:00:00Z',
      payload: { packet_type: 'income_execution_ny' },
      summary: 'Packet sent: Income Execution Ny',
    },
  ],
  total: 5,
};

describe('EntityTimeline', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // =========================================================================
  // Loading State Tests
  // =========================================================================

  it('shows loading state initially', () => {
    mockFetch.mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    render(<EntityTimeline judgmentId={123} />);

    expect(screen.getByText(/loading timeline/i)).toBeInTheDocument();
  });

  // =========================================================================
  // Empty State Tests
  // =========================================================================

  it('shows empty state when no events', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ events: [], total: 0 }),
    });

    render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(
        screen.getByText(/no events yet for this defendant/i)
      ).toBeInTheDocument();
    });
  });

  it('shows empty state when no entityId or judgmentId provided', async () => {
    render(<EntityTimeline />);

    await waitFor(() => {
      expect(
        screen.getByText(/no events yet for this defendant/i)
      ).toBeInTheDocument();
    });

    // Should not make any fetch calls
    expect(mockFetch).not.toHaveBeenCalled();
  });

  // =========================================================================
  // Error State Tests
  // =========================================================================

  it('shows error state on fetch failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      statusText: 'Internal Server Error',
    });

    render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(
        screen.getByText(/failed to fetch timeline/i)
      ).toBeInTheDocument();
    });
  });

  it('shows error state on network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });

  // =========================================================================
  // Timeline Rendering Tests
  // =========================================================================

  it('renders timeline events correctly', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockTimelineResponse,
    });

    render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(
        screen.getByText(/judgment created for \$5000 in new york/i)
      ).toBeInTheDocument();
    });

    expect(screen.getByText(/job found at acme corp/i)).toBeInTheDocument();
    expect(
      screen.getByText(/offer made: \$2500 \(50¢ on the dollar\)/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/offer accepted for \$2500/i)).toBeInTheDocument();
    expect(
      screen.getByText(/packet sent: income execution ny/i)
    ).toBeInTheDocument();
  });

  it('displays dates for each event', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockTimelineResponse,
    });

    render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(screen.getByText(/jan 15, 2025/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/jan 16, 2025/i)).toBeInTheDocument();
    expect(screen.getByText(/jan 17, 2025/i)).toBeInTheDocument();
  });

  // =========================================================================
  // API URL Tests
  // =========================================================================

  it('uses entityId URL when entityId provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ events: [], total: 0 }),
    });

    const entityId = '123e4567-e89b-12d3-a456-426614174000';
    render(<EntityTimeline entityId={entityId} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        `/api/v1/intelligence/entity/${entityId}/timeline?limit=100`
      );
    });
  });

  it('uses judgmentId URL when judgmentId provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ events: [], total: 0 }),
    });

    render(<EntityTimeline judgmentId={456} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/intelligence/judgment/456/timeline?limit=100'
      );
    });
  });

  it('prefers entityId over judgmentId when both provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ events: [], total: 0 }),
    });

    const entityId = '123e4567-e89b-12d3-a456-426614174000';
    render(<EntityTimeline entityId={entityId} judgmentId={456} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        `/api/v1/intelligence/entity/${entityId}/timeline?limit=100`
      );
    });
  });

  // =========================================================================
  // Event Type Icon Tests
  // =========================================================================

  it('renders different icons for different event types', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockTimelineResponse,
    });

    const { container } = render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      // Check that we have multiple icon containers (rounded-full elements)
      const iconContainers = container.querySelectorAll('.rounded-full');
      expect(iconContainers.length).toBeGreaterThanOrEqual(5);
    });
  });

  // =========================================================================
  // Refetch Tests
  // =========================================================================

  it('refetches when judgmentId changes', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ events: [], total: 0 }),
    });

    const { rerender } = render(<EntityTimeline judgmentId={123} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    rerender(<EntityTimeline judgmentId={456} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
