import React from 'react';
import { Link } from 'react-router-dom';
import { Sun, Coffee, Moon, ArrowRight } from 'lucide-react';

interface DailyPhase {
  icon: React.ReactNode;
  title: string;
  time: string;
  tasks: string[];
  link: { to: string; label: string };
  accentClass: string;
}

const dailyPhases: DailyPhase[] = [
  {
    icon: <Sun className="h-5 w-5" aria-hidden="true" />,
    title: 'Morning Checklist',
    time: '9:00 AM',
    tasks: [
      'Open the Overview page to see your daily snapshot.',
      'Check how many Tier A cases you have — these are your top priority.',
      'Review any new public records responses that came in overnight.',
    ],
    link: { to: '/', label: 'Go to Overview' },
    accentClass: 'bg-amber-50 border-amber-200 text-amber-700',
  },
  {
    icon: <Coffee className="h-5 w-5" aria-hidden="true" />,
    title: 'Midday Check-in',
    time: '12:00 PM',
    tasks: [
      'Head to the Collectability page to work through your call list.',
      'Start with Tier A, then move to Tier B if time allows.',
      'Log each call outcome so we can track your progress.',
    ],
    link: { to: '/collectability', label: 'Go to Collectability' },
    accentClass: 'bg-blue-50 border-blue-200 text-blue-700',
  },
  {
    icon: <Moon className="h-5 w-5" aria-hidden="true" />,
    title: 'End-of-Day Wrap-up',
    time: '4:30 PM',
    tasks: [
      'Check the Cases page for any updates on your active judgments.',
      'Note any cases that need follow-up tomorrow.',
      'Glance at the Overview to see how the numbers changed today.',
    ],
    link: { to: '/cases', label: 'Go to Cases' },
    accentClass: 'bg-indigo-50 border-indigo-200 text-indigo-700',
  },
];

const WelcomeCard: React.FC = () => {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-white p-6 shadow-sm">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Welcome to Your Daily Workflow</h2>
        <p className="mt-2 text-sm text-slate-600">
          Follow these three phases each day to stay on top of your cases. It takes about 15 minutes total to check in at each point.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {dailyPhases.map((phase) => (
          <article
            key={phase.title}
            className={['flex flex-col rounded-xl border p-4', phase.accentClass].join(' ')}
          >
            <div className="flex items-center gap-2">
              <span className="flex-shrink-0">{phase.icon}</span>
              <div>
                <h3 className="text-sm font-semibold">{phase.title}</h3>
                <p className="text-xs opacity-80">{phase.time}</p>
              </div>
            </div>
            <ul className="mt-3 flex-1 space-y-1.5 text-xs text-slate-700">
              {phase.tasks.map((task, index) => (
                <li key={index} className="flex gap-2">
                  <span className="flex-shrink-0 font-semibold text-slate-400">{index + 1}.</span>
                  <span>{task}</span>
                </li>
              ))}
            </ul>
            <Link
              to={phase.link.to}
              className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700 transition-colors hover:text-slate-900"
            >
              {phase.link.label}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </article>
        ))}
      </div>

      <div className="mt-6 rounded-xl border border-slate-200 bg-white/60 p-4">
        <h4 className="text-sm font-semibold text-slate-700">Quick Page Guide</h4>
        <ul className="mt-2 grid gap-2 text-sm text-slate-600 sm:grid-cols-3">
          <li>
            <Link to="/" className="hover:text-slate-900 hover:underline">
              <strong>Overview</strong>
            </Link>{' '}
            — Your daily dashboard with key numbers and priorities.
          </li>
          <li>
            <Link to="/collectability" className="hover:text-slate-900 hover:underline">
              <strong>Collectability</strong>
            </Link>{' '}
            — Browse cases by how likely they are to pay.
          </li>
          <li>
            <Link to="/cases" className="hover:text-slate-900 hover:underline">
              <strong>Cases</strong>
            </Link>{' '}
            — Search and view detailed info on every judgment.
          </li>
        </ul>
      </div>
    </section>
  );
};

export default WelcomeCard;
