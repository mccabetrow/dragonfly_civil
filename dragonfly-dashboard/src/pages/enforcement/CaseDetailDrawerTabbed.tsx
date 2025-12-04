/**
 * CaseDetailDrawerTabbed
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * CEO Cockpit drawer with Scorecard, Intelligence, and Offers tabs.
 */
import React, { useState, useCallback } from 'react';
import {
  DollarSign,
  Calendar,
  MapPin,
  Briefcase,
  User,
  Hash,
  TrendingUp,
  Network,
  Receipt,
} from 'lucide-react';
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from '../../components/primitives';
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '../../components/primitives/Tabs';
import { ScoreCardTab } from '../../components/radar/ScoreCardTab';
import { IntelligenceTab } from '../../components/radar/IntelligenceTab';
import { OffersTab } from '../../components/radar/OffersTab';
import { OfferModal } from '../../components/radar/OfferModal';
import type { RadarRow } from '../../hooks/useEnforcementRadar';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface CaseDetailDrawerTabbedProps {
  row: RadarRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  formatCurrency: (value: number) => string;
  formatDate: (dateStr: string | null) => string;
  onOfferCreated?: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface DetailFieldProps {
  icon: React.ElementType;
  label: string;
  value: React.ReactNode;
}

const DetailField: React.FC<DetailFieldProps> = ({ icon: Icon, label, value }) => (
  <div className="flex items-start gap-3 py-2">
    <Icon className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
    <div className="min-w-0 flex-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium break-words">{value ?? '—'}</p>
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const CaseDetailDrawerTabbed: React.FC<CaseDetailDrawerTabbedProps> = ({
  row,
  open,
  onOpenChange,
  formatCurrency,
  formatDate,
  onOfferCreated,
}) => {
  const [activeTab, setActiveTab] = useState('scorecard');
  const [offerModalOpen, setOfferModalOpen] = useState(false);

  // Parse judgment ID from row.id (might be string)
  const judgmentId = typeof row.id === 'string' ? parseInt(row.id, 10) : row.id;

  const handleRecordOffer = useCallback(() => {
    setOfferModalOpen(true);
  }, []);

  const handleOfferSuccess = useCallback(() => {
    onOfferCreated?.();
  }, [onOfferCreated]);

  return (
    <>
      <Drawer open={open} onOpenChange={onOpenChange}>
        <DrawerContent side="right" size="lg">
          <DrawerHeader>
            <DrawerTitle>Case Details</DrawerTitle>
            <DrawerDescription>{row.caseNumber}</DrawerDescription>
          </DrawerHeader>
          <DrawerBody className="p-0">
            {/* Case Summary Card */}
            <div className="px-6 py-4 border-b bg-muted/30">
              <div className="space-y-1 divide-y">
                <DetailField icon={Hash} label="Case Number" value={row.caseNumber} />
                <DetailField icon={User} label="Plaintiff" value={row.plaintiffName} />
                <DetailField icon={User} label="Defendant" value={row.defendantName} />
                <DetailField
                  icon={DollarSign}
                  label="Judgment Amount"
                  value={formatCurrency(row.judgmentAmount)}
                />
                <DetailField icon={Calendar} label="Judgment Date" value={formatDate(row.judgmentDate)} />
                <DetailField icon={Briefcase} label="Court" value={row.court} />
                <DetailField icon={MapPin} label="County" value={row.county} />
              </div>
            </div>

            {/* Tabs */}
            <div className="px-6 py-4 flex-1 overflow-y-auto">
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList className="w-full grid grid-cols-3">
                  <TabsTrigger value="scorecard" className="gap-1.5">
                    <TrendingUp className="h-3.5 w-3.5" />
                    Scorecard
                  </TabsTrigger>
                  <TabsTrigger value="intelligence" className="gap-1.5">
                    <Network className="h-3.5 w-3.5" />
                    Intelligence
                  </TabsTrigger>
                  <TabsTrigger value="offers" className="gap-1.5">
                    <Receipt className="h-3.5 w-3.5" />
                    Offers
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="scorecard">
                  <ScoreCardTab judgmentId={judgmentId} />
                </TabsContent>

                <TabsContent value="intelligence">
                  <IntelligenceTab judgmentId={judgmentId} />
                </TabsContent>

                <TabsContent value="offers">
                  <OffersTab
                    judgmentId={judgmentId}
                    judgmentAmount={row.judgmentAmount}
                    onRecordOffer={handleRecordOffer}
                  />
                </TabsContent>
              </Tabs>
            </div>
          </DrawerBody>
        </DrawerContent>
      </Drawer>

      {/* Offer Modal */}
      <OfferModal
        isOpen={offerModalOpen}
        onClose={() => setOfferModalOpen(false)}
        judgmentId={judgmentId}
        judgmentAmount={row.judgmentAmount}
        onSuccess={handleOfferSuccess}
      />
    </>
  );
};

export default CaseDetailDrawerTabbed;
