/**
 * ConfigDebug - Debug page for viewing runtime configuration
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Only accessible in development mode. Shows resolved config values
 * with masked secrets for verification.
 *
 * Route: /debug/config (development only)
 */

import { runtimeConfig, isDev } from '../../config';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

function maskSecret(value: string): string {
  if (!value || value.length < 12) return '***';
  return `${value.slice(0, 4)}...${value.slice(-8)}`;
}

export function ConfigDebug() {
  const navigate = useNavigate();

  // Redirect to home in production
  useEffect(() => {
    if (!isDev) {
      console.warn('[ConfigDebug] Not available in production. Redirecting...');
      navigate('/');
    }
  }, [navigate]);

  if (!isDev) {
    return null;
  }

  const configItems = [
    { label: 'Mode', value: runtimeConfig.isProd ? 'PRODUCTION' : 'DEVELOPMENT' },
    { label: 'Demo Mode', value: runtimeConfig.isDemoMode ? 'ON' : 'OFF' },
    { label: 'API Base URL', value: runtimeConfig.apiBaseUrl },
    { label: 'Supabase URL', value: runtimeConfig.supabaseUrl },
    { label: 'API Key', value: maskSecret(runtimeConfig.dragonflyApiKey), secret: true },
    { label: 'Supabase Anon Key', value: maskSecret(runtimeConfig.supabaseAnonKey), secret: true },
  ];

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold text-amber-400 mb-2">
          🐉 Dragonfly Config Debug
        </h1>
        <p className="text-gray-400 mb-6">
          Development-only view of runtime configuration
        </p>

        <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-700">
              <tr>
                <th className="text-left px-4 py-2 text-gray-300">Variable</th>
                <th className="text-left px-4 py-2 text-gray-300">Value</th>
              </tr>
            </thead>
            <tbody>
              {configItems.map((item, i) => (
                <tr
                  key={item.label}
                  className={i % 2 === 0 ? 'bg-gray-800' : 'bg-gray-800/50'}
                >
                  <td className="px-4 py-2 font-mono text-gray-400">
                    {item.label}
                  </td>
                  <td className="px-4 py-2 font-mono">
                    {item.secret ? (
                      <span className="text-amber-300">{item.value}</span>
                    ) : (
                      <span className="text-green-400">{item.value}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6 p-4 bg-blue-900/30 border border-blue-700 rounded-lg">
          <h2 className="text-sm font-semibold text-blue-300 mb-2">
            Console Debug Output
          </h2>
          <p className="text-xs text-gray-400">
            Full config is logged to console on page load in dev mode.
            Check browser DevTools for <code>[Dragonfly Config]</code> messages.
          </p>
        </div>

        <div className="mt-6 text-xs text-gray-500">
          <p>
            ⚠️ This page is only visible in development mode.
            It will redirect to home in production builds.
          </p>
        </div>
      </div>
    </div>
  );
}

export default ConfigDebug;
