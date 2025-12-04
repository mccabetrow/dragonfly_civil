/**
 * OffersTab
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tab content showing offer history and "Record Offer" button.
 */
import React from 'react';
import {
  AlertCircle,
  DollarSign,
  Plus,
  Clock,
  CheckCircle2,
  XCircle,
  MessageSquare,
  FileText,
} from 'lucide-react';
import { Button, Card, CardContent } from '../primitives';
import { useOffers, type Offer } from '../../hooks/useOffers';
import { cn } from '../../lib/tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface OffersTabProps {
  judgmentId: number;
  judgmentAmount: number;
  onRecordOffer: () => void;
}

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

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

const statusConfig: Record<
  Offer['status'],
  { icon: React.ElementType; label: string; color: string }
> = {
  offered: {
    icon: Clock,
    label: 'Pending',
    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  accepted: {
    icon: CheckCircle2,
    label: 'Accepted',
    color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
  rejected: {
    icon: XCircle,
    label: 'Rejected',
    color: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
  negotiation: {
    icon: MessageSquare,
    label: 'Negotiating',
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  expired: {
    icon: Clock,
    label: 'Expired',
    color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface StatusBadgeProps {
  status: Offer['status'];
}

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const config = statusConfig[status] || statusConfig.offered;
  const Icon = config.icon;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
        config.color
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

interface OfferCardProps {
  offer: Offer;
  judgmentAmount: number;
}

const OfferCard: React.FC<OfferCardProps> = ({ offer, judgmentAmount }) => {
  const centsOnDollar = judgmentAmount > 0
    ? ((offer.offerAmount / judgmentAmount) * 100).toFixed(1)
    : '0.0';

  return (
    <div className="p-3 rounded-lg border bg-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold tabular-nums">
              {formatCurrency(offer.offerAmount)}
            </span>
            <span className="text-xs text-muted-foreground">
              ({centsOnDollar}¢/$)
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <StatusBadge status={offer.status} />
            <span
              className={cn(
                'px-2 py-0.5 rounded text-xs font-medium',
                offer.offerType === 'purchase'
                  ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
                  : 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
              )}
            >
              {offer.offerType === 'purchase' ? 'Purchase' : 'Contingency'}
            </span>
          </div>
          {offer.operatorNotes && (
            <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
              {offer.operatorNotes}
            </p>
          )}
        </div>
        <div className="text-xs text-muted-foreground text-right">
          {formatDate(offer.createdAt)}
        </div>
      </div>
    </div>
  );
};

const LoadingState: React.FC = () => (
  <div className="space-y-3 animate-pulse">
    {[1, 2].map((i) => (
      <div key={i} className="p-3 rounded-lg border bg-gray-50 dark:bg-gray-800">
        <div className="h-5 w-24 bg-gray-200 dark:bg-gray-700 rounded mb-2" />
        <div className="h-4 w-32 bg-gray-200 dark:bg-gray-700 rounded" />
      </div>
    ))}
  </div>
);

const ErrorState: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex flex-col items-center justify-center py-6 text-center">
    <AlertCircle className="h-6 w-6 text-red-500 mb-2" />
    <p className="text-sm text-muted-foreground">{message}</p>
  </div>
);

const EmptyState: React.FC = () => (
  <div className="flex flex-col items-center justify-center py-6 text-center">
    <div className="h-10 w-10 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-2">
      <FileText className="h-5 w-5 text-gray-400" />
    </div>
    <p className="text-sm text-muted-foreground">No offers recorded yet</p>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const OffersTab: React.FC<OffersTabProps> = ({
  judgmentId,
  judgmentAmount,
  onRecordOffer,
}) => {
  const { offers, loading, error } = useOffers(judgmentId);

  // Summary stats
  const stats = React.useMemo(() => {
    const accepted = offers.filter((o) => o.status === 'accepted').length;
    const rejected = offers.filter((o) => o.status === 'rejected').length;
    const pending = offers.filter((o) => o.status === 'offered' || o.status === 'negotiation').length;
    return { total: offers.length, accepted, rejected, pending };
  }, [offers]);

  return (
    <div className="space-y-4">
      {/* Record Offer Button */}
      <Button
        onClick={onRecordOffer}
        className="w-full gap-2"
        size="lg"
      >
        <Plus className="h-4 w-4" />
        Record Offer
      </Button>

      {/* Summary Stats */}
      {stats.total > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-1">
                <DollarSign className="h-4 w-4 text-muted-foreground" />
                <span className="font-medium">{stats.total} Offers</span>
              </div>
              <div className="flex items-center gap-3 text-xs">
                {stats.accepted > 0 && (
                  <span className="text-green-600 dark:text-green-400">
                    {stats.accepted} accepted
                  </span>
                )}
                {stats.rejected > 0 && (
                  <span className="text-red-600 dark:text-red-400">
                    {stats.rejected} rejected
                  </span>
                )}
                {stats.pending > 0 && (
                  <span className="text-blue-600 dark:text-blue-400">
                    {stats.pending} pending
                  </span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Offers List */}
      <div className="space-y-2">
        <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Offer History
        </h4>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} />
        ) : offers.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-2">
            {offers.map((offer) => (
              <OfferCard key={offer.id} offer={offer} judgmentAmount={judgmentAmount} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default OffersTab;
