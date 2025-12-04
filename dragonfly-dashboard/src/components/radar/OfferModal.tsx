/**
 * OfferModal
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Modal for recording a new offer on a judgment.
 * Computes cents on the dollar in real-time.
 */
import React, { useState, useCallback, useEffect } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X, DollarSign, FileText, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { Button } from '../primitives';
import { useOffers, type CreateOfferPayload } from '../../hooks/useOffers';
import { cn } from '../../lib/tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface OfferModalProps {
  isOpen: boolean;
  onClose: () => void;
  judgmentId: number;
  judgmentAmount: number;
  onSuccess?: () => void;
}

type OfferType = 'purchase' | 'contingency';

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const OfferModal: React.FC<OfferModalProps> = ({
  isOpen,
  onClose,
  judgmentId,
  judgmentAmount,
  onSuccess,
}) => {
  const { createOffer } = useOffers(judgmentId);

  // Form state
  const [offerAmount, setOfferAmount] = useState<string>('');
  const [offerType, setOfferType] = useState<OfferType>('purchase');
  const [operatorNotes, setOperatorNotes] = useState<string>('');

  // UI state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setOfferAmount('');
      setOfferType('purchase');
      setOperatorNotes('');
      setError(null);
      setSuccess(false);
    }
  }, [isOpen]);

  // Compute cents on the dollar
  const numericAmount = parseFloat(offerAmount.replace(/[^0-9.]/g, '')) || 0;
  const centsOnDollar = judgmentAmount > 0
    ? ((numericAmount / judgmentAmount) * 100).toFixed(1)
    : '0.0';

  // Handle submit
  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (numericAmount <= 0) {
        setError('Please enter a valid offer amount');
        return;
      }

      setSubmitting(true);
      setError(null);

      const payload: CreateOfferPayload = {
        judgment_id: judgmentId,
        offer_amount: numericAmount,
        offer_type: offerType,
        operator_notes: operatorNotes.trim() || undefined,
      };

      const result = await createOffer(payload);

      setSubmitting(false);

      if (!result.ok) {
        setError(result.error);
        return;
      }

      setSuccess(true);
      setTimeout(() => {
        onSuccess?.();
        onClose();
      }, 1000);
    },
    [judgmentId, numericAmount, offerType, operatorNotes, createOffer, onSuccess, onClose]
  );

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        {/* Overlay */}
        <DialogPrimitive.Overlay
          className={cn(
            'fixed inset-0 z-50 bg-black/50 backdrop-blur-sm',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0'
          )}
        />

        {/* Content */}
        <DialogPrimitive.Content
          className={cn(
            'fixed left-[50%] top-[50%] z-50 w-full max-w-md translate-x-[-50%] translate-y-[-50%]',
            'bg-white dark:bg-gray-900 rounded-xl shadow-xl p-6',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]',
            'data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]'
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-6">
            <DialogPrimitive.Title className="text-lg font-semibold">
              Record Offer
            </DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <button
                className="h-8 w-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </DialogPrimitive.Close>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Judgment Context */}
            <div className="p-3 rounded-lg bg-muted/50 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Judgment Amount:</span>
                <span className="font-bold">{formatCurrency(judgmentAmount)}</span>
              </div>
            </div>

            {/* Offer Amount */}
            <div className="space-y-2">
              <label htmlFor="offer-amount" className="text-sm font-medium">
                Offer Amount
              </label>
              <div className="relative">
                <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  id="offer-amount"
                  type="text"
                  inputMode="decimal"
                  value={offerAmount}
                  onChange={(e) => setOfferAmount(e.target.value)}
                  placeholder="0.00"
                  className={cn(
                    'w-full pl-9 pr-4 py-2 rounded-lg border bg-background',
                    'text-lg font-medium tabular-nums',
                    'focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent',
                    'placeholder:text-muted-foreground/50'
                  )}
                  disabled={submitting}
                />
              </div>
            </div>

            {/* Cents on Dollar Display */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-primary/5 border border-primary/20">
              <span className="text-sm text-muted-foreground">Cents on the Dollar:</span>
              <span className="text-xl font-bold text-primary tabular-nums">
                {centsOnDollar}%
              </span>
            </div>

            {/* Offer Type */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Offer Type</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setOfferType('purchase')}
                  disabled={submitting}
                  className={cn(
                    'py-2 px-4 rounded-lg border text-sm font-medium transition-colors',
                    offerType === 'purchase'
                      ? 'bg-purple-100 border-purple-300 text-purple-700 dark:bg-purple-900/30 dark:border-purple-700 dark:text-purple-400'
                      : 'bg-background border-border hover:bg-muted'
                  )}
                >
                  Purchase
                </button>
                <button
                  type="button"
                  onClick={() => setOfferType('contingency')}
                  disabled={submitting}
                  className={cn(
                    'py-2 px-4 rounded-lg border text-sm font-medium transition-colors',
                    offerType === 'contingency'
                      ? 'bg-blue-100 border-blue-300 text-blue-700 dark:bg-blue-900/30 dark:border-blue-700 dark:text-blue-400'
                      : 'bg-background border-border hover:bg-muted'
                  )}
                >
                  Contingency
                </button>
              </div>
            </div>

            {/* Operator Notes */}
            <div className="space-y-2">
              <label htmlFor="operator-notes" className="text-sm font-medium flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted-foreground" />
                Operator Notes
                <span className="text-xs text-muted-foreground font-normal">(optional)</span>
              </label>
              <textarea
                id="operator-notes"
                value={operatorNotes}
                onChange={(e) => setOperatorNotes(e.target.value)}
                placeholder="Add notes about this offer..."
                rows={3}
                className={cn(
                  'w-full px-3 py-2 rounded-lg border bg-background resize-none',
                  'text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent',
                  'placeholder:text-muted-foreground/50'
                )}
                disabled={submitting}
              />
            </div>

            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 text-sm">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {error}
              </div>
            )}

            {/* Success Message */}
            {success && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 text-sm">
                <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                Offer recorded successfully!
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={onClose}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                className="flex-1 gap-2"
                disabled={submitting || numericAmount <= 0}
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  <>
                    <DollarSign className="h-4 w-4" />
                    Submit Offer
                  </>
                )}
              </Button>
            </div>
          </form>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};

export default OfferModal;
