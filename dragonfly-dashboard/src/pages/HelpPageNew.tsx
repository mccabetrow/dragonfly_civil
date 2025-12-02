/**
 * HelpPageNew - Polished help page with runbook and keyboard shortcuts
 * 
 * Layout: Quick Start → Keyboard Shortcuts → Runbook → Contact
 */
import React from 'react';
import type { FC } from 'react';
import {
  BookOpen,
  Keyboard,
  Phone,
  Mail,
  ExternalLink,
  ChevronRight,
  HelpCircle,
  Zap,
} from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';

interface KeyboardShortcut {
  keys: string[];
  description: string;
}

const SHORTCUTS: KeyboardShortcut[] = [
  { keys: ['Ctrl/⌘', 'K'], description: 'Open command palette' },
  { keys: ['Ctrl/⌘', 'R'], description: 'Refresh data' },
  { keys: ['↑', '↓'], description: 'Navigate table rows' },
  { keys: ['Enter'], description: 'Open selected item' },
  { keys: ['Esc'], description: 'Close drawer or dialog' },
];

interface RunbookSection {
  id: string;
  title: string;
  description: string;
  steps: string[];
}

const RUNBOOK_SECTIONS: RunbookSection[] = [
  {
    id: 'daily',
    title: 'Daily Workflow',
    description: 'Start each day with these steps:',
    steps: [
      'Check the Overview page for your daily snapshot',
      'Navigate to Ops Console to see your call queue',
      'Work through calls, logging outcomes with quick actions',
      'Review Enforcement Pipeline for items needing attention',
      'Check for alerts about signatures or high-priority items',
    ],
  },
  {
    id: 'calls',
    title: 'Making Calls',
    description: 'Best practices for outreach:',
    steps: [
      'Start with the top item in your queue (highlighted)',
      'Review plaintiff profile before calling',
      'Use quick action buttons to log outcomes immediately',
      'Add notes for any important details',
      'Set follow-up dates when needed',
    ],
  },
  {
    id: 'tiers',
    title: 'Understanding Tiers',
    description: 'Prioritize by collectability tier:',
    steps: [
      'Tier A (green): Best opportunities — focus here first',
      'Tier B (yellow): Good candidates for follow-up',
      'Tier C (gray): Lower priority — check occasionally',
      'Click tier cards on Collectability page to filter',
      'Use filters to find specific case types',
    ],
  },
  {
    id: 'enforcement',
    title: 'Enforcement Actions',
    description: 'Track progress through the pipeline:',
    steps: [
      'Monitor "Awaiting Signature" items for bottlenecks',
      'Check "Actions in Progress" for active enforcement',
      'Review completed actions for follow-up opportunities',
      'Use the pipeline view to identify stalled cases',
    ],
  },
  {
    id: 'stuck',
    title: 'What If I\'m Stuck?',
    description: 'Try these steps if something isn\'t working:',
    steps: [
      'Click the Refresh button in the top-right corner',
      'If data looks stale, wait 30 seconds and refresh again',
      'Check your internet connection',
      'Try closing the drawer and reopening the case',
      'If all else fails, reload the browser (F5 or Ctrl+R)',
      'Still stuck? Email support@dragonflycivil.com',
    ],
  },
];

const HelpPageNew: FC = () => {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Help & Documentation"
        description="Everything you need to use the enforcement console effectively."
      />

      {/* Quick Start Card */}
      <section className="rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 to-white p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-100">
            <Zap className="h-6 w-6 text-blue-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Quick Start</h2>
            <p className="mt-1 text-sm text-slate-600">
              New to the console? Here's the 30-second overview:
            </p>
            <ol className="mt-4 space-y-2 text-sm text-slate-700">
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">1</span>
                <span><strong>Overview</strong> shows your daily metrics and priorities</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">2</span>
                <span><strong>Ops Console</strong> is where you make calls and log outcomes</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">3</span>
                <span><strong>Collectability</strong> helps you focus on the best opportunities</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">4</span>
                <span><strong>Cases</strong> lets you search and browse all judgments</span>
              </li>
            </ol>
            <p className="mt-4 text-sm text-slate-500">
              💡 Tip: Press <kbd className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-medium">⌘K</kbd> anytime to quickly navigate between pages.
            </p>
          </div>
        </div>
      </section>

      {/* Keyboard Shortcuts */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Keyboard className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Keyboard Shortcuts</h2>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="mb-4 text-sm text-slate-600">
            Use these shortcuts to work faster. On Windows, use Ctrl instead of ⌘.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SHORTCUTS.map((shortcut, index) => (
              <div
                key={index}
                className="flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-3"
              >
                <span className="text-sm text-slate-600">{shortcut.description}</span>
                <div className="flex items-center gap-1">
                  {shortcut.keys.map((key, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="text-slate-300">+</span>}
                      <kbd className="inline-flex h-7 min-w-[28px] items-center justify-center rounded-lg border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 shadow-sm">
                        {key}
                      </kbd>
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Runbook */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Operations Runbook</h2>
        </div>
        <div className="space-y-4">
          {RUNBOOK_SECTIONS.map((section) => (
            <details
              key={section.id}
              className="group rounded-2xl border border-slate-200 bg-white shadow-sm"
            >
              <summary className="flex cursor-pointer items-center justify-between px-6 py-4 hover:bg-slate-50">
                <div>
                  <h3 className="font-semibold text-slate-900">{section.title}</h3>
                  <p className="mt-0.5 text-sm text-slate-500">{section.description}</p>
                </div>
                <ChevronRight className="h-5 w-5 text-slate-400 transition-transform group-open:rotate-90" />
              </summary>
              <div className="border-t border-slate-100 px-6 py-4">
                <ol className="space-y-2">
                  {section.steps.map((step, index) => (
                    <li
                      key={index}
                      className="flex items-start gap-3 text-sm text-slate-600"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600">
                        {index + 1}
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </details>
          ))}
        </div>
      </section>

      {/* Contact Support */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <HelpCircle className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Need More Help?</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <a
            href="mailto:support@dragonflycivil.com"
            className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md"
          >
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50">
              <Mail className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900">Email Support</h3>
              <p className="mt-0.5 text-sm text-slate-500">support@dragonflycivil.com</p>
            </div>
            <ExternalLink className="ml-auto h-4 w-4 text-slate-400" />
          </a>
          <a
            href="tel:+1234567890"
            className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md"
          >
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-50">
              <Phone className="h-5 w-5 text-emerald-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900">Call the Office</h3>
              <p className="mt-0.5 text-sm text-slate-500">For urgent issues</p>
            </div>
            <ExternalLink className="ml-auto h-4 w-4 text-slate-400" />
          </a>
        </div>
      </section>
    </div>
  );
};

export default HelpPageNew;
