import React from 'react';

const SettingsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Team Preferences</h2>
        <p className="mt-2 text-sm text-slate-600">
          Configure integrations, notifications, and secure access as the enforcement program scales. These controls will
          align with compliance and outreach execution requirements.
        </p>
        <dl className="mt-4 grid gap-3 text-sm text-slate-500 md:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <dt className="font-semibold text-slate-600">Access controls</dt>
            <dd className="mt-1 text-xs text-slate-500">Role-based permissions tied to Supabase auth.
            </dd>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <dt className="font-semibold text-slate-600">Notifications</dt>
            <dd className="mt-1 text-xs text-slate-500">Email and in-app alerts for task deadlines.
            </dd>
          </div>
        </dl>
      </section>
      <section className="rounded-2xl border border-dashed border-slate-200 bg-white/70 p-10 text-center">
        <p className="text-sm font-medium uppercase tracking-wide text-slate-400">Configuration coming soon</p>
        <p className="mt-3 text-xl font-semibold text-slate-500">Connect outreach, scheduling, and compliance services here.</p>
      </section>
    </div>
  );
};

export default SettingsPage;
