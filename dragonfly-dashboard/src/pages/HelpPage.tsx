import React from 'react';

const guidedSteps: Array<{
  title: string;
  summary: string;
  highlights: string[];
}> = [
  {
    title: '1. Data Pipeline: Simplicity → Supabase',
    summary:
      'Start by dropping a fresh Simplicity export into the watcher. Highlight how the CLI tasks (`make smoke`, Insert: Composite) push data into Supabase while logs stream in.',
    highlights: [
      'Reference docs/runbook_phase1.md for the pre-ingest checklist.',
      'Point out the watcher automation that processes files from data_in/.',
      'Open /overview to show the pipeline metrics and queue health counters updating.',
    ],
  },
  {
    title: '2. Collectability Overview & Tiers',
    summary:
      'Walk the Collectability page to explain how scoring blends dollar amount plus judgment age, giving operations a clear ranking.',
    highlights: [
      'Use the tier filter to demonstrate the instant A/B/C segmentation.',
      'Toggle the Judgment Amount sort to show prioritization controls.',
      'Call out the helper copy describing how each tier should be interpreted.',
    ],
  },
  {
    title: '3. Case-Level Drilldown',
    summary:
      'Navigate to the Cases page and open a row. Emphasize how the three-column drawer gives a full picture without leaving the screen.',
    highlights: [
      'Show the plaintiff/defendant context on the overview column.',
      'Demonstrate the enrichment history timeline with timestamps.',
      'Point to the FOIL activity list that keeps compliance conversations grounded in facts.',
    ],
  },
  {
    title: '4. FOIL & Enrichment Tracking',
    summary:
      'Explain how every FOIL disclosure and enrichment run is captured, making audit prep effortless.',
    highlights: [
      'Scroll through FOIL responses and note agency plus received date.',
      'Describe how enrichment history proves the scoring engine stays fresh.',
      'Loop back to /overview to reinforce portfolio-level totals.',
    ],
  },
  {
    title: '5. Scale-Up Vision & Next Steps',
    summary:
      'Close the tour with upcoming automation plans and the onboarding goal for new cases.',
    highlights: [
      'Mention live outreach (n8n) and enrichment vendor feeds on the roadmap.',
      'Describe how Supabase schema already supports enforcement workflows.',
      'Set expectations: ready to onboard 10–20 cases per week once outreach templates ship.',
    ],
  },
];

const HelpPage: React.FC = () => {
  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-900">Dragonfly Console Guide</h1>
        <p className="mt-2 text-sm text-slate-600">
          This walkthrough distills the highlights from <code>DEMO_DRAGONFLY_CONSOLE.md</code>. Use it as a cue card when
          demoing the console or onboarding teammates.
        </p>
        <p className="mt-3 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          Tip: Keep a terminal tab open with the VS Code tasks panel. Switching between CLI output and these dashboards
          brings the automation story to life.
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
        <h2 className="text-lg font-semibold text-slate-900">Demo Flow Recap</h2>
        <p className="mt-2 text-sm text-slate-600">
          Start in the docs, run an ingest, show the overview metrics reacting, drill into tiers, open a case, and finish
          with the roadmap. The console is ready for customer conversations today while the automation footprint
          continues to expand.
        </p>
      </section>
    </div>
  );
};

export default HelpPage;
