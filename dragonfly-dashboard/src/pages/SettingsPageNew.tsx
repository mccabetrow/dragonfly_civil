/**
 * SettingsPageNew - Polished settings with integrations and team access
 * 
 * Layout: Integrations cards + Team Access + Preferences
 */
import type { FC } from 'react';
import { Link } from 'react-router-dom';
import {
  Plug,
  Users,
  Bell,
  Shield,
  CheckCircle,
  XCircle,
  ExternalLink,
  Upload,
  ChevronRight,
} from 'lucide-react';
import PageHeader from '../components/ui/PageHeader';
import { cn } from '../lib/design-tokens';

interface IntegrationCard {
  id: string;
  name: string;
  description: string;
  icon: typeof Plug;
  status: 'connected' | 'disconnected' | 'coming-soon';
  statusLabel: string;
}

const INTEGRATIONS: IntegrationCard[] = [
  {
    id: 'dialer',
    name: 'Outbound Dialer',
    description: 'One-click calling from the queue. Logs calls automatically.',
    icon: Plug,
    status: 'coming-soon',
    statusLabel: 'Coming soon',
  },
  {
    id: 'email',
    name: 'Email Service',
    description: 'Sends automated follow-up emails to plaintiffs.',
    icon: Bell,
    status: 'coming-soon',
    statusLabel: 'Coming soon',
  },
];

const TEAM_MEMBERS = [
  { name: 'Dawn C.', role: 'Owner', email: 'dawn@dragonflycivil.com', initials: 'DC' },
];

const SettingsPageNew: FC = () => {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Settings"
        description="View connected integrations and notification preferences. Most settings are managed by your administrator."
      />

      {/* Integrations Section */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Plug className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Integrations</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {INTEGRATIONS.map((integration) => {
            const Icon = integration.icon;
            const isConnected = integration.status === 'connected';
            const isComingSoon = integration.status === 'coming-soon';

            return (
              <div
                key={integration.id}
                className={cn(
                  'rounded-2xl border bg-white p-5 shadow-sm transition-all duration-200',
                  isComingSoon
                    ? 'border-slate-200 opacity-60'
                    : 'border-slate-200 hover:border-slate-300 hover:shadow-md'
                )}
              >
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl',
                      isConnected ? 'bg-emerald-50' : 'bg-slate-100'
                    )}
                  >
                    <Icon
                      className={cn(
                        'h-5 w-5',
                        isConnected ? 'text-emerald-600' : 'text-slate-400'
                      )}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-semibold text-slate-900">{integration.name}</h3>
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold',
                          isConnected && 'bg-emerald-50 text-emerald-700',
                          integration.status === 'disconnected' && 'bg-red-50 text-red-700',
                          isComingSoon && 'bg-slate-100 text-slate-500'
                        )}
                      >
                        {isConnected && <CheckCircle className="h-3 w-3" />}
                        {integration.status === 'disconnected' && <XCircle className="h-3 w-3" />}
                        {integration.statusLabel}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">{integration.description}</p>
                    {!isComingSoon && isConnected && (
                      <p className="mt-3 text-xs text-slate-400">
                        Managed by your administrator
                      </p>
                    )}
                    {!isComingSoon && !isConnected && (
                      <button
                        type="button"
                        className="mt-3 text-sm font-medium text-blue-600 hover:text-blue-700"
                        onClick={() => alert('Contact your administrator to connect this integration.')}
                      >
                        Connect →
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Data Management Section */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Upload className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Data Management</h2>
        </div>
        <div className="space-y-3">
          <Link
            to="/settings/ingestion"
            className="group flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:border-indigo-200 hover:shadow-md"
          >
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-50">
                <Upload className="h-5 w-5 text-indigo-600" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900">Data Ingestion</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Upload Simplicity CSV exports and monitor batch processing status
                </p>
              </div>
            </div>
            <ChevronRight className="h-5 w-5 text-slate-300 transition-colors group-hover:text-indigo-500" />
          </Link>
          <Link
            to="/settings/integrity"
            className="group flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:border-emerald-200 hover:shadow-md"
          >
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-50">
                <Shield className="h-5 w-5 text-emerald-600" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900">Data Integrity</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Vault status dashboard — verify ingested rows and resolve discrepancies
                </p>
              </div>
            </div>
            <ChevronRight className="h-5 w-5 text-slate-300 transition-colors group-hover:text-emerald-500" />
          </Link>
        </div>
      </section>

      {/* Team Access Section */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Users className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Team Access</h2>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-6 py-4">
            <p className="text-sm text-slate-600">
              Manage who has access to this enforcement console. Role-based permissions are tied to Supabase auth.
            </p>
          </div>
          <div className="divide-y divide-slate-100">
            {TEAM_MEMBERS.map((member) => (
              <div
                key={member.email}
                className="flex items-center justify-between px-6 py-4"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-indigo-600 text-sm font-semibold text-white shadow-sm">
                    {member.initials}
                  </div>
                  <div>
                    <p className="font-medium text-slate-900">{member.name}</p>
                    <p className="text-sm text-slate-500">{member.email}</p>
                  </div>
                </div>
                <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
                  {member.role}
                </span>
              </div>
            ))}
          </div>
          <div className="border-t border-slate-100 px-6 py-4">
            <button
              type="button"
              className="text-sm font-medium text-blue-600 hover:text-blue-700"
            >
              + Invite team member
            </button>
          </div>
        </div>
      </section>

      {/* Notifications Section */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Bell className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Notifications</h2>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="space-y-4">
            <label className="flex items-center justify-between">
              <div>
                <p className="font-medium text-slate-900">Daily summary email</p>
                <p className="text-sm text-slate-500">Receive a morning digest of key metrics</p>
              </div>
              <input
                type="checkbox"
                defaultChecked
                className="h-5 w-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
            </label>
            <label className="flex items-center justify-between">
              <div>
                <p className="font-medium text-slate-900">High-priority alerts</p>
                <p className="text-sm text-slate-500">Get notified about urgent items</p>
              </div>
              <input
                type="checkbox"
                defaultChecked
                className="h-5 w-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
            </label>
            <label className="flex items-center justify-between">
              <div>
                <p className="font-medium text-slate-900">Signature reminders</p>
                <p className="text-sm text-slate-500">Notify when documents need signing</p>
              </div>
              <input
                type="checkbox"
                defaultChecked
                className="h-5 w-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              />
            </label>
          </div>
        </div>
      </section>

      {/* Security Section */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Shield className="h-5 w-5 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-900">Security</h2>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-50">
              <Shield className="h-5 w-5 text-emerald-600" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900">Row-Level Security Enabled</h3>
              <p className="mt-1 text-sm text-slate-500">
                All data is protected by Supabase RLS policies. Only authorized team members can access sensitive plaintiff and judgment data.
              </p>
              <a
                href="https://supabase.com/docs/guides/auth/row-level-security"
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
              >
                Learn more about RLS
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default SettingsPageNew;
