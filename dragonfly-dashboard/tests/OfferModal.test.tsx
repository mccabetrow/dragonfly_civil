/**
 * Tests for OfferModal Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests form interactions and API submission.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OfferModal } from '../src/components/radar/OfferModal';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockCreateOffer = vi.fn();

vi.mock('../src/hooks/useOffers', () => ({
  useOffers: vi.fn(() => ({
    offers: [],
    loading: false,
    error: null,
    createOffer: mockCreateOffer,
    refetch: vi.fn(),
  })),
}));

vi.mock('../src/lib/supabaseClient', () => ({
  IS_DEMO_MODE: false,
}));

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('OfferModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    judgmentId: 123,
    judgmentAmount: 50000,
    onSuccess: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateOffer.mockResolvedValue({ ok: true, offer: { id: 'offer-1' } });
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders the modal when open', () => {
    render(<OfferModal {...defaultProps} />);

    expect(screen.getByText('Record Offer')).toBeInTheDocument();
    expect(screen.getByText('$50,000')).toBeInTheDocument(); // Judgment amount
  });

  it('computes cents on the dollar correctly', async () => {
    const user = userEvent.setup();
    render(<OfferModal {...defaultProps} />);

    const amountInput = screen.getByPlaceholderText('0.00');
    await user.type(amountInput, '15000');

    // 15000 / 50000 * 100 = 30%
    expect(screen.getByText('30.0%')).toBeInTheDocument();
  });

  it('allows selecting offer type', async () => {
    const user = userEvent.setup();
    render(<OfferModal {...defaultProps} />);

    // Should start with Purchase selected
    const purchaseBtn = screen.getByRole('button', { name: 'Purchase' });
    const contingencyBtn = screen.getByRole('button', { name: 'Contingency' });

    // Click contingency
    await user.click(contingencyBtn);

    // Contingency should now be selected (has different styling)
    expect(contingencyBtn).toHaveClass('bg-blue-100');
  });

  it('submits the form with correct payload', async () => {
    const user = userEvent.setup();
    render(<OfferModal {...defaultProps} />);

    // Fill in amount
    const amountInput = screen.getByPlaceholderText('0.00');
    await user.type(amountInput, '15000');

    // Add notes
    const notesInput = screen.getByPlaceholderText('Add notes about this offer...');
    await user.type(notesInput, 'Test offer notes');

    // Submit
    const submitButton = screen.getByRole('button', { name: /Submit Offer/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockCreateOffer).toHaveBeenCalledWith({
        judgment_id: 123,
        offer_amount: 15000,
        offer_type: 'purchase',
        operator_notes: 'Test offer notes',
      });
    });
  });

  it('shows error message on submission failure', async () => {
    mockCreateOffer.mockResolvedValue({ ok: false, error: 'Server error' });

    const user = userEvent.setup();
    render(<OfferModal {...defaultProps} />);

    // Fill in amount
    const amountInput = screen.getByPlaceholderText('0.00');
    await user.type(amountInput, '15000');

    // Submit
    const submitButton = screen.getByRole('button', { name: /Submit Offer/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
  });

  it('disables submit button when amount is zero', () => {
    render(<OfferModal {...defaultProps} />);

    const submitButton = screen.getByRole('button', { name: /Submit Offer/i });
    expect(submitButton).toBeDisabled();
  });

  it('calls onClose when cancel is clicked', async () => {
    const user = userEvent.setup();
    render(<OfferModal {...defaultProps} />);

    const cancelButton = screen.getByRole('button', { name: 'Cancel' });
    await user.click(cancelButton);

    expect(defaultProps.onClose).toHaveBeenCalled();
  });

  it('shows success message and closes after successful submission', async () => {
    render(<OfferModal {...defaultProps} />);

    // Fill in amount
    const amountInput = screen.getByPlaceholderText('0.00');
    fireEvent.change(amountInput, { target: { value: '15000' } });

    // Submit
    const submitButton = screen.getByRole('button', { name: /Submit Offer/i });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText('Offer recorded successfully!')).toBeInTheDocument();
    });

    // Wait for success callback
    await waitFor(() => {
      expect(defaultProps.onSuccess).toHaveBeenCalled();
    });
  });
});
