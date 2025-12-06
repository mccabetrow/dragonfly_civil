import React, { useState, useEffect } from 'react';
import { X, Sparkles } from 'lucide-react';

interface ReleaseNote {
  version: string;
  date: string;
  title: string;
  highlights: string[];
}

const RELEASE_NOTES: ReleaseNote[] = [
  {
    version: '1.5.0',
    date: 'Dec 6, 2025',
    title: 'Securitization Engine',
    highlights: [
      'Pool management for grouping judgments into funds',
      'NAV calculation and performance tracking',
      'Gig economy garnishment detection (Uber, DoorDash, Lyft)',
      'Proof.com integration for process server dispatch',
    ],
  },
  {
    version: '1.4.0',
    date: 'Dec 1, 2025',
    title: 'First-time user experience',
    highlights: [
      'Added "First Week" checklist to help new users get started',
      'Empty state cards now guide you when there are no judgments yet',
      'New "What changed?" link shows recent updates',
    ],
  },
  {
    version: '1.3.0',
    date: 'Nov 28, 2025',
    title: 'Mom-friendly UX copy',
    highlights: [
      'Rewrote all labels and descriptions for clarity',
      'Added helpful tooltips throughout the console',
      'Welcome card with daily workflow guidance',
    ],
  },
  {
    version: '1.2.0',
    date: 'Nov 25, 2025',
    title: 'Collectability tiers',
    highlights: [
      'Cases now sorted into Tier A, B, C by collection likelihood',
      'Overview shows tier distribution at a glance',
      'Filter by tier on the Collectability page',
    ],
  },
  {
    version: '1.1.0',
    date: 'Nov 20, 2025',
    title: 'Public records tracking',
    highlights: [
      'See agency responses directly in the case detail view',
      'FOIL activity summary on the Overview page',
      'Track when responses were received',
    ],
  },
  {
    version: '1.0.0',
    date: 'Nov 15, 2025',
    title: 'Initial release',
    highlights: [
      'Overview dashboard with key metrics',
      'Browse and search all judgments',
      'Case detail with plaintiff and defendant info',
    ],
  },
];

interface ReleaseNotesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const ReleaseNotesModal: React.FC<ReleaseNotesModalProps> = ({ isOpen, onClose }) => {
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="release-notes-title"
        className="relative mx-4 max-h-[80vh] w-full max-w-lg overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-blue-500" aria-hidden="true" />
            <h2 id="release-notes-title" className="text-lg font-semibold text-slate-900">
              What's New
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-4">
          <ul className="space-y-6">
            {RELEASE_NOTES.map((note, index) => (
              <li key={note.version}>
                <div className="flex items-center gap-3">
                  <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700">
                    v{note.version}
                  </span>
                  <span className="text-xs text-slate-500">{note.date}</span>
                  {index === 0 && (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                      Latest
                    </span>
                  )}
                </div>
                <h3 className="mt-2 text-sm font-semibold text-slate-900">{note.title}</h3>
                <ul className="mt-2 space-y-1">
                  {note.highlights.map((highlight) => (
                    <li key={highlight} className="flex gap-2 text-sm text-slate-600">
                      <span className="text-slate-400">•</span>
                      <span>{highlight}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>

        <footer className="border-t border-slate-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Got it
          </button>
        </footer>
      </div>
    </div>
  );
};

export function useReleaseNotesModal() {
  const [isOpen, setIsOpen] = useState(false);
  const open = () => setIsOpen(true);
  const close = () => setIsOpen(false);
  return { isOpen, open, close };
}

export default ReleaseNotesModal;
