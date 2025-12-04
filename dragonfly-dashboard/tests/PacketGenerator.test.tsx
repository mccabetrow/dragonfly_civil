/**
 * Tests for PacketGenerator Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the legal packet generation UI.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PacketGenerator } from '../src/components/radar/PacketGenerator';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockFetch = vi.fn();
const mockWindowOpen = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('open', mockWindowOpen);
  mockFetch.mockReset();
  mockWindowOpen.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('PacketGenerator', () => {
  it('renders the component with title', () => {
    render(<PacketGenerator judgmentId={123} />);

    expect(screen.getByText('Legal Packets')).toBeInTheDocument();
    expect(screen.getByText('Generate Packet')).toBeInTheDocument();
  });

  it('renders packet type selector with default option', () => {
    render(<PacketGenerator judgmentId={123} />);

    expect(screen.getByText('Document Type')).toBeInTheDocument();
    // Check for the description text which is unique
    expect(screen.getByText('Wage garnishment order for employers')).toBeInTheDocument();
  });

  it('uses defaultPacketType prop', () => {
    render(<PacketGenerator judgmentId={123} defaultPacketType="info_subpoena_ny" />);

    // Check for the description text which is unique
    expect(screen.getByText('Discovery document for financial info')).toBeInTheDocument();
  });

  it('shows loading state when generating', async () => {
    // Mock a slow response
    mockFetch.mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () =>
              resolve({
                ok: true,
                json: () =>
                  Promise.resolve({
                    packet_url: 'https://example.com/packet.docx',
                    packet_type: 'income_execution_ny',
                    judgment_id: 123,
                  }),
              }),
            100,
          ),
        ),
    );

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    // Should show loading state
    await waitFor(() => {
      expect(screen.getByText('Generating...')).toBeInTheDocument();
    });
  });

  it('shows success message on successful generation', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          packet_url: 'https://example.com/packet.docx',
          packet_type: 'income_execution_ny',
          judgment_id: 123,
        }),
    });

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(screen.getByText('Packet Ready')).toBeInTheDocument();
    });

    // Should have download button
    expect(screen.getByRole('button', { name: /Download/i })).toBeInTheDocument();
  });

  it('calls window.open on success', async () => {
    const packetUrl = 'https://example.com/packet.docx';
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          packet_url: packetUrl,
          packet_type: 'income_execution_ny',
          judgment_id: 123,
        }),
    });

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    // Wait for success state
    await waitFor(() => {
      expect(screen.getByText('Packet Ready')).toBeInTheDocument();
    });

    // window.open should have been called
    expect(mockWindowOpen).toHaveBeenCalledWith(packetUrl, '_blank');
  });

  it('shows error message on API failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: 'Judgment not found' }),
    });

    render(<PacketGenerator judgmentId={999} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(screen.getByText('Generation Failed')).toBeInTheDocument();
      expect(screen.getByText('Judgment not found')).toBeInTheDocument();
    });
  });

  it('shows error message on network failure', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(screen.getByText('Generation Failed')).toBeInTheDocument();
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('sends correct request payload', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          packet_url: 'https://example.com/packet.docx',
          packet_type: 'income_execution_ny',
          judgment_id: 123,
        }),
    });

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/packets/generate'),
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            judgment_id: 123,
            type: 'income_execution_ny',
          }),
        }),
      );
    });
  });
});

describe('PacketGenerator - Button States', () => {
  it('disables button while loading', async () => {
    mockFetch.mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () =>
              resolve({
                ok: true,
                json: () =>
                  Promise.resolve({
                    packet_url: 'https://example.com/packet.docx',
                    packet_type: 'income_execution_ny',
                    judgment_id: 123,
                  }),
              }),
            500,
          ),
        ),
    );

    render(<PacketGenerator judgmentId={123} />);

    const generateButton = screen.getByRole('button', { name: /Generate Packet/i });
    fireEvent.click(generateButton);

    await waitFor(() => {
      const loadingButton = screen.getByRole('button', { name: /Generating/i });
      expect(loadingButton).toBeDisabled();
    });
  });
});
