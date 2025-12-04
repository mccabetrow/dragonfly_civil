/**
 * OpsIntakeQueuePanel - New lead intake validation queue
 * 
 * Shows AI-validated leads awaiting ops review.
 * Supports approve/reject/flag actions.
 */
import { useState, type FC } from 'react';
import { 
  FileCheck, 
  CheckCircle, 
  XCircle, 
  AlertTriangle, 
  Flag,
  ChevronRight,
  Bot,
  User,
  Building2,
  DollarSign,
  MapPin
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { Button } from '../ui/Button';

export interface IntakeQueueItem {
  /** Judgment UUID */
  judgmentId: string;
  /** Validation result UUID */
  validationId: string;
  /** Court case/index number */
  caseIndexNumber: string;
  /** Debtor name */
  debtorName: string;
  /** Original creditor */
  originalCreditor: string | null;
  /** Judgment date */
  judgmentDate: string | null;
  /** Principal amount */
  principalAmount: number | null;
  /** County */
  county: string | null;
  /** Current status */
  status: string;
  /** When the record was imported */
  importedAt: string;
  /** Validation timestamp */
  validatedAt: string | null;
  /** AI validation result */
  validationResult: 'valid' | 'invalid' | 'needs_review' | null;
  /** Confidence score 0-100 */
  confidenceScore: number | null;
  /** Name check passed */
  nameCheckPassed: boolean | null;
  /** Name check note */
  nameCheckNote: string | null;
  /** Address check passed */
  addressCheckPassed: boolean | null;
  /** Address check note */
  addressCheckNote: string | null;
  /** Case number check passed */
  caseNumberCheckPassed: boolean | null;
  /** Case number check note */
  caseNumberCheckNote: string | null;
  /** Queue status for UI */
  queueStatus: 'pending_review' | 'auto_valid' | 'auto_invalid' | 'reviewed';
  /** Review priority */
  reviewPriority: number;
  /** Reviewer decision if reviewed */
  reviewDecision: string | null;
}

interface OpsIntakeQueuePanelProps {
  /** Queue items to display */
  items: IntakeQueueItem[];
  /** Currently selected item ID */
  selectedId?: string | null;
  /** Called when an item is selected */
  onSelect?: (item: IntakeQueueItem) => void;
  /** Called when review decision is submitted */
  onReviewSubmit?: (validationId: string, decision: 'approved' | 'rejected' | 'flagged', notes?: string) => void;
  /** Whether data is loading */
  isLoading?: boolean;
  /** Additional className */
  className?: string;
}

const VALIDATION_STYLES: Record<string, { bg: string; text: string; border: string; icon: typeof CheckCircle }> = {
  valid: { 
    bg: 'bg-emerald-50', 
    text: 'text-emerald-700', 
    border: 'border-emerald-200',
    icon: CheckCircle 
  },
  invalid: { 
    bg: 'bg-red-50', 
    text: 'text-red-700', 
    border: 'border-red-200',
    icon: XCircle 
  },
  needs_review: { 
    bg: 'bg-amber-50', 
    text: 'text-amber-700', 
    border: 'border-amber-200',
    icon: AlertTriangle 
  },
};

const OpsIntakeQueuePanel: FC<OpsIntakeQueuePanelProps> = ({
  items,
  selectedId,
  onReviewSubmit,
  isLoading,
  className,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState<string>('');

  if (isLoading) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-50">
            <FileCheck className="h-5 w-5 text-purple-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Intake Queue</h3>
            <p className="text-xs text-slate-500">Loading...</p>
          </div>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl bg-slate-100 h-24" />
          ))}
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className={cn('rounded-2xl border border-slate-200 bg-white p-6 shadow-sm', className)}>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100">
            <FileCheck className="h-5 w-5 text-slate-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Intake Queue</h3>
            <p className="text-xs text-slate-500">All clear!</p>
          </div>
        </div>
        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center">
          <CheckCircle className="mx-auto h-8 w-8 text-emerald-500 mb-2" />
          <p className="text-sm font-medium text-slate-600">No leads awaiting review</p>
          <p className="mt-1 text-xs text-slate-400">New leads will appear here after AI validation</p>
        </div>
      </div>
    );
  }

  const formatCurrency = (amount: number | null) => {
    if (amount == null) return '—';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const formatDate = (date: string | null) => {
    if (!date) return '—';
    return new Date(date).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const getValidationStyle = (result: string | null) => {
    return VALIDATION_STYLES[result ?? 'needs_review'] ?? VALIDATION_STYLES.needs_review;
  };

  const handleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
    setReviewNotes('');
  };

  const handleReview = (validationId: string, decision: 'approved' | 'rejected' | 'flagged') => {
    onReviewSubmit?.(validationId, decision, reviewNotes);
    setExpandedId(null);
    setReviewNotes('');
  };

  // Stats for header
  const needsReviewCount = items.filter(i => i.validationResult === 'needs_review' && !i.reviewDecision).length;
  const validCount = items.filter(i => i.validationResult === 'valid' && !i.reviewDecision).length;
  const invalidCount = items.filter(i => i.validationResult === 'invalid' && !i.reviewDecision).length;

  return (
    <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b border-slate-100">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-50">
            <FileCheck className="h-5 w-5 text-purple-600" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-slate-900">Intake Queue</h3>
            <p className="text-xs text-slate-500">{items.length} leads awaiting review</p>
          </div>
        </div>
        
        {/* Quick stats */}
        <div className="flex items-center gap-2">
          {needsReviewCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              <AlertTriangle className="h-3 w-3" />
              {needsReviewCount} needs review
            </span>
          )}
          {validCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
              <CheckCircle className="h-3 w-3" />
              {validCount} valid
            </span>
          )}
          {invalidCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
              <XCircle className="h-3 w-3" />
              {invalidCount} invalid
            </span>
          )}
        </div>
      </div>

      {/* List */}
      <div className="divide-y divide-slate-100">
        {items.map((item) => {
          const isExpanded = expandedId === item.validationId;
          const validationStyle = getValidationStyle(item.validationResult);
          const ValidationIcon = validationStyle.icon;

          return (
            <div
              key={item.validationId || item.judgmentId}
              className={cn(
                'transition-colors',
                isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50/50',
                selectedId === item.judgmentId && 'ring-2 ring-purple-500 ring-inset'
              )}
            >
              {/* Main row */}
              <button
                type="button"
                onClick={() => handleExpand(item.validationId)}
                className="w-full p-4 text-left"
              >
                <div className="flex items-start justify-between gap-4">
                  {/* Left: Main info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold text-slate-900 truncate">
                        {item.debtorName || 'Unknown Debtor'}
                      </span>
                      <span className={cn(
                        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
                        validationStyle.bg,
                        validationStyle.text
                      )}>
                        <ValidationIcon className="h-3 w-3" />
                        {item.validationResult?.replace('_', ' ') ?? 'pending'}
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-3 text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <FileCheck className="h-3 w-3" />
                        {item.caseIndexNumber}
                      </span>
                      {item.county && (
                        <span className="flex items-center gap-1">
                          <MapPin className="h-3 w-3" />
                          {item.county}
                        </span>
                      )}
                      {item.principalAmount && (
                        <span className="flex items-center gap-1 font-medium text-slate-700">
                          <DollarSign className="h-3 w-3" />
                          {formatCurrency(item.principalAmount)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Right: Confidence + expand */}
                  <div className="flex items-center gap-3">
                    {item.confidenceScore != null && (
                      <div className="text-right">
                        <div className="flex items-center gap-1 text-xs text-slate-500">
                          <Bot className="h-3 w-3" />
                          <span>{item.confidenceScore}%</span>
                        </div>
                        <div className="w-16 h-1.5 bg-slate-200 rounded-full mt-1">
                          <div 
                            className={cn(
                              'h-full rounded-full',
                              item.confidenceScore >= 80 ? 'bg-emerald-500' :
                              item.confidenceScore >= 50 ? 'bg-amber-500' : 'bg-red-500'
                            )}
                            style={{ width: `${item.confidenceScore}%` }}
                          />
                        </div>
                      </div>
                    )}
                    <ChevronRight 
                      className={cn(
                        'h-4 w-4 text-slate-400 transition-transform',
                        isExpanded && 'rotate-90'
                      )} 
                    />
                  </div>
                </div>
              </button>

              {/* Expanded details */}
              {isExpanded && (
                <div className="px-4 pb-4 space-y-4">
                  {/* Validation checks */}
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="text-xs font-medium text-slate-700 mb-2 flex items-center gap-1">
                      <Bot className="h-3 w-3" />
                      AI Validation Checks
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      {/* Name check */}
                      <div className={cn(
                        'rounded-lg p-2 text-xs',
                        item.nameCheckPassed === true ? 'bg-emerald-50' :
                        item.nameCheckPassed === false ? 'bg-red-50' : 'bg-slate-50'
                      )}>
                        <div className="flex items-center gap-1 font-medium mb-0.5">
                          <User className="h-3 w-3" />
                          Name
                          {item.nameCheckPassed === true && <CheckCircle className="h-3 w-3 text-emerald-600" />}
                          {item.nameCheckPassed === false && <XCircle className="h-3 w-3 text-red-600" />}
                        </div>
                        <p className="text-slate-600 line-clamp-2">{item.nameCheckNote || '—'}</p>
                      </div>
                      
                      {/* Address check */}
                      <div className={cn(
                        'rounded-lg p-2 text-xs',
                        item.addressCheckPassed === true ? 'bg-emerald-50' :
                        item.addressCheckPassed === false ? 'bg-red-50' : 'bg-slate-50'
                      )}>
                        <div className="flex items-center gap-1 font-medium mb-0.5">
                          <Building2 className="h-3 w-3" />
                          Address
                          {item.addressCheckPassed === true && <CheckCircle className="h-3 w-3 text-emerald-600" />}
                          {item.addressCheckPassed === false && <XCircle className="h-3 w-3 text-red-600" />}
                        </div>
                        <p className="text-slate-600 line-clamp-2">{item.addressCheckNote || '—'}</p>
                      </div>
                      
                      {/* Case number check */}
                      <div className={cn(
                        'rounded-lg p-2 text-xs',
                        item.caseNumberCheckPassed === true ? 'bg-emerald-50' :
                        item.caseNumberCheckPassed === false ? 'bg-red-50' : 'bg-slate-50'
                      )}>
                        <div className="flex items-center gap-1 font-medium mb-0.5">
                          <FileCheck className="h-3 w-3" />
                          Case #
                          {item.caseNumberCheckPassed === true && <CheckCircle className="h-3 w-3 text-emerald-600" />}
                          {item.caseNumberCheckPassed === false && <XCircle className="h-3 w-3 text-red-600" />}
                        </div>
                        <p className="text-slate-600 line-clamp-2">{item.caseNumberCheckNote || '—'}</p>
                      </div>
                    </div>
                  </div>

                  {/* Additional info */}
                  <div className="grid grid-cols-4 gap-4 text-xs">
                    <div>
                      <span className="text-slate-500">Original Creditor</span>
                      <p className="font-medium text-slate-900">{item.originalCreditor || '—'}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Judgment Date</span>
                      <p className="font-medium text-slate-900">{formatDate(item.judgmentDate)}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Imported</span>
                      <p className="font-medium text-slate-900">{formatDate(item.importedAt)}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Validated</span>
                      <p className="font-medium text-slate-900">{formatDate(item.validatedAt)}</p>
                    </div>
                  </div>

                  {/* Review notes */}
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      Review Notes (optional)
                    </label>
                    <textarea
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Add any notes about this lead..."
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                      rows={2}
                    />
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleReview(item.validationId, 'flagged')}
                      className="text-amber-600 border-amber-200 hover:bg-amber-50"
                    >
                      <Flag className="h-4 w-4 mr-1" />
                      Flag for Review
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleReview(item.validationId, 'rejected')}
                      className="text-red-600 border-red-200 hover:bg-red-50"
                    >
                      <XCircle className="h-4 w-4 mr-1" />
                      Reject
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleReview(item.validationId, 'approved')}
                      className="bg-emerald-600 hover:bg-emerald-700"
                    >
                      <CheckCircle className="h-4 w-4 mr-1" />
                      Approve
                    </Button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default OpsIntakeQueuePanel;
