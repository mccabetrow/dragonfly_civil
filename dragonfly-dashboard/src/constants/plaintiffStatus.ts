import type { PlaintiffStatus } from '../utils/plaintiffStatusClient';

export const PLAINTIFF_STATUS_ORDER: PlaintiffStatus[] = [
  'new',
  'contacted',
  'qualified',
  'sent_agreement',
  'signed',
  'lost',
];

export const PLAINTIFF_STATUS_LABELS: Record<PlaintiffStatus, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  sent_agreement: 'Sent agreement',
  signed: 'Signed',
  lost: 'Lost',
};

export const PLAINTIFF_STATUS_DISPLAY = PLAINTIFF_STATUS_ORDER.map((code) => ({
  code,
  label: PLAINTIFF_STATUS_LABELS[code],
}));
