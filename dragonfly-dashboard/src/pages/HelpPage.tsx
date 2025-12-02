import React from 'react';
import WelcomeCard from '../components/WelcomeCard';
import FirstWeekChecklist from '../components/FirstWeekChecklist';
import HelpTooltip from '../components/HelpTooltip';

const guidedSteps: Array<{
  title: string;
  summary: string;
  highlights: string[];
}> = [
  {
    title: '1. Start with the Overview',
    summary:
      'The Overview page is your daily dashboard. Check it each morning to see the big picture of all your judgments.',
    highlights: [
      'Look at "Total judgments" to see how many cases you\'re tracking.',
      'Check "Being researched" to see what\'s actively being worked on.',
      'The tier breakdown shows where your best collection opportunities are.',
    ],
  },
  {
    title: '2. Understand the Tiers',
    summary:
      'We automatically sort your judgments into three groups based on how likely they are to collect.',
    highlights: [
      'Tier A (green): Your best bets — recent, higher-dollar judgments. Focus here first.',
      'Tier B (yellow): Worth pursuing — good candidates for follow-up calls.',
      'Tier C (gray): Lower priority — older or smaller amounts. Check occasionally.',
    ],
  },
  {
    title: '3. Browse Your Cases',
    summary:
      'The Cases page lets you search and view every judgment. Click any row to see the full story.',
    highlights: [
      'Use the search box to find a specific case number.',
      'Click a case to see the plaintiff name, defendant, and judgment details.',
      'The "Research History" panel shows what information we\'ve gathered.',
    ],
  },
  {
    title: '4. Track Public Records',
    summary:
      'When government agencies respond to our information requests, those responses appear automatically.',
    highlights: [
      'Look for the "Public Records Responses" section on the Cases page.',
      'Each response shows which agency sent it and when.',
      'This information helps with enforcement decisions.',
    ],
  },
  {
    title: '5. Daily Workflow',
    summary:
      'Here\'s a simple routine to follow each day.',
    highlights: [
      'Morning: Check the Overview page to see the day\'s snapshot.',
      'Work your Tier A cases first — these have the best chance of success.',
      'Log your call outcomes so we can track progress.',
      'Check back at end of day to see updated numbers.',
    ],
  },
];

const HelpPage: React.FC = () => {
  return (
    <div className="space-y-8">
      <WelcomeCard />
      <FirstWeekChecklist />

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-900">How to Use This Console</h1>
        <p className="mt-2 text-sm text-slate-600">
          This guide walks you through everything you need to know. Take 5 minutes to read through it, then you'll be ready to go.
        </p>
        <p className="mt-3 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          💡 Tip: Bookmark this page so you can come back whenever you need a refresher.
        </p>
      </section>

      <section className="space-y-6">
        {guidedSteps.map((step) => (
          <article key={step.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">{step.title}</h2>
            <p className="mt-2 text-sm text-slate-600">{step.summary}</p>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-slate-600">
              {step.highlights.map((highlight) => (
                <li key={highlight}>{highlight}</li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900">Need Help?</h2>
          <HelpTooltip text="For urgent issues, call the main office first. For technical problems, email is fastest." />
        </div>
        <p className="mt-2 text-sm text-slate-600">
          If something doesn't look right or you have questions, reach out to the team. We're here to help you succeed.
        </p>
        <p className="mt-4">
          <a
            href="mailto:support@dragonflycivil.com?subject=Help%20Request%20from%20Operations%20Console"
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Email Support
          </a>
        </p>
      </section>
    </div>
  );
};

export default HelpPage;
