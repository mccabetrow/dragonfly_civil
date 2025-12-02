import React, { useState } from 'react';
import { CheckCircle2, Circle } from 'lucide-react';

interface ChecklistItem {
  id: string;
  label: string;
  description: string;
}

const FIRST_WEEK_ITEMS: ChecklistItem[] = [
  {
    id: 'explore-overview',
    label: 'Explore the Overview page',
    description: 'Spend 5 minutes looking at your daily snapshot — see how judgments are organized into tiers.',
  },
  {
    id: 'review-tier-a',
    label: 'Review your Tier A cases',
    description: 'Go to Collectability and filter by Tier A. These are your highest-priority cases.',
  },
  {
    id: 'open-case-detail',
    label: 'Open a case to see full details',
    description: 'Click any case on the Cases page to see the plaintiff info, research history, and public records.',
  },
];

const STORAGE_KEY = 'dragonfly_first_week_checklist';

function loadCheckedItems(): Set<string> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return new Set(JSON.parse(stored) as string[]);
    }
  } catch {
    // Ignore parse errors
  }
  return new Set();
}

function saveCheckedItems(items: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...items]));
  } catch {
    // Ignore storage errors
  }
}

const FirstWeekChecklist: React.FC = () => {
  const [checkedItems, setCheckedItems] = useState<Set<string>>(() => loadCheckedItems());

  const toggleItem = (id: string) => {
    setCheckedItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      saveCheckedItems(next);
      return next;
    });
  };

  const completedCount = checkedItems.size;
  const totalCount = FIRST_WEEK_ITEMS.length;
  const allComplete = completedCount === totalCount;

  return (
    <section className="rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Your First Week Checklist</h2>
          <p className="mt-1 text-sm text-slate-600">
            Complete these 3 steps to get familiar with the console.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-500">
            {completedCount}/{totalCount}
          </span>
          <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${(completedCount / totalCount) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {allComplete && (
        <div className="mb-4 rounded-xl border border-emerald-300 bg-emerald-100 px-4 py-3 text-sm text-emerald-800">
          🎉 Great job! You've completed your first week onboarding.
        </div>
      )}

      <ul className="space-y-3">
        {FIRST_WEEK_ITEMS.map((item) => {
          const isChecked = checkedItems.has(item.id);
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => toggleItem(item.id)}
                className={[
                  'flex w-full items-start gap-3 rounded-xl border p-4 text-left transition',
                  isChecked
                    ? 'border-emerald-300 bg-emerald-50/50'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50',
                ].join(' ')}
              >
                <span className="mt-0.5 flex-shrink-0">
                  {isChecked ? (
                    <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                  ) : (
                    <Circle className="h-5 w-5 text-slate-400" />
                  )}
                </span>
                <div>
                  <p
                    className={[
                      'text-sm font-medium',
                      isChecked ? 'text-emerald-700 line-through' : 'text-slate-900',
                    ].join(' ')}
                  >
                    {item.label}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">{item.description}</p>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
};

export default FirstWeekChecklist;
