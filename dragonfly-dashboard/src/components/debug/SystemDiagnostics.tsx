/**
 * SystemDiagnostics.tsx
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Comprehensive system diagnostics panel for validating environment variables
 * and testing full API surface area. Hidden behind a debug toggle.
 *
 * Features:
 * - Config display (masked API URL)
 * - Env var validation (whitespace/newline detection)
 * - Concurrent endpoint smoke tests
 * - Results matrix with status, latency, and response snippets
 * - Toast notifications for failures
 */

import { type FC, useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bug,
  X,
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Server,
  Shield,
  Wifi,
  Database,
  Activity,
  ExternalLink,
  Copy,
  Check,
} from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { useToast } from '../ui/Toast';
import { apiBaseUrl, dragonflyApiKey } from '../../config';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface EndpointResult {
  name: string;
  endpoint: string;
  status: 'pending' | 'success' | 'error' | 'warning';
  httpCode: number | null;
  latencyMs: number | null;
  responseSnippet: string | null;
  error: string | null;
}

interface EnvValidation {
  variable: string;
  value: string;
  masked: string;
  isValid: boolean;
  issues: string[];
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS (from centralized config)
// ═══════════════════════════════════════════════════════════════════════════

const VITE_API_BASE_URL = apiBaseUrl;
const VITE_DRAGONFLY_API_KEY = dragonflyApiKey;

/**
 * Critical endpoints to test - covers health, auth, and key services
 */
const ENDPOINTS_TO_TEST = [
  { name: 'Root Health', endpoint: '/health', requiresAuth: false },
  { name: 'API Health', endpoint: '/api/health', requiresAuth: false },
  { name: 'API Readiness', endpoint: '/api/health/readyz', requiresAuth: false },
  { name: 'API DB Health', endpoint: '/api/health/db', requiresAuth: false },
  { name: 'Platform Version', endpoint: '/api/version', requiresAuth: false },
  { name: 'Intake Service', endpoint: '/api/v1/intake/batches', requiresAuth: true },
  { name: 'Cases Service', endpoint: '/api/v1/cases', requiresAuth: true },
  { name: 'Analytics', endpoint: '/api/v1/analytics/overview', requiresAuth: true },
  { name: 'Portfolio', endpoint: '/api/v1/portfolio/summary', requiresAuth: true },
  { name: 'CEO Metrics', endpoint: '/api/v1/ceo/metrics', requiresAuth: true },
  { name: 'System Heartbeats', endpoint: '/api/v1/system/workers', requiresAuth: true },
];

/**
 * Keyboard shortcut: Ctrl+Shift+D to toggle diagnostics panel
 */
const KEYBOARD_SHORTCUT = { key: 'D', ctrlKey: true, shiftKey: true };

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Mask a URL for display - show protocol + host prefix + ellipsis + domain suffix
 */
function maskUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.host;
    if (host.length <= 45) {
      return `${parsed.protocol}//${host}`;
    }
    const prefix = host.slice(0, 30);
    const suffix = host.slice(-15);
    return `${parsed.protocol}//${prefix}…${suffix}`;
  } catch {
    return url.slice(0, 50) + (url.length > 50 ? '…' : '');
  }
}

/**
 * Mask an API key - show first 4 and last 4 chars
 */
function maskApiKey(key: string): string {
  if (!key || key.length < 12) return '****';
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

/**
 * Validate an environment variable for common issues
 */
function validateEnvVar(name: string, value: string | undefined): EnvValidation {
  const issues: string[] = [];

  if (!value) {
    return {
      variable: name,
      value: '',
      masked: '(not set)',
      isValid: false,
      issues: ['Variable is not set'],
    };
  }

  // Check for whitespace issues
  if (value !== value.trim()) {
    issues.push('Contains leading/trailing whitespace');
  }

  // Check for newlines (common copy-paste error)
  if (value.includes('\n') || value.includes('\r')) {
    issues.push('Contains newline characters');
  }

  // Check for tab characters
  if (value.includes('\t')) {
    issues.push('Contains tab characters');
  }

  // URL-specific validation
  if (name.includes('URL')) {
    try {
      new URL(value.trim());
    } catch {
      issues.push('Invalid URL format');
    }

    if (!value.startsWith('http://') && !value.startsWith('https://')) {
      issues.push('URL should start with http:// or https://');
    }

    if (value.endsWith('/')) {
      issues.push('URL has trailing slash (may cause double slashes)');
    }
  }

  const masked = name.includes('KEY') ? maskApiKey(value) : maskUrl(value);

  return {
    variable: name,
    value,
    masked,
    isValid: issues.length === 0,
    issues,
  };
}

/**
 * Truncate a string for display
 */
function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + '…';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT: SystemDiagnostics
// ═══════════════════════════════════════════════════════════════════════════

const SystemDiagnostics: FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState<EndpointResult[]>([]);
  const [envValidations, setEnvValidations] = useState<EnvValidation[]>([]);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const { addToast } = useToast();
  const panelRef = useRef<HTMLDivElement>(null);

  // ─────────────────────────────────────────────────────────────────────────
  // Keyboard shortcut handler
  // ─────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key.toUpperCase() === KEYBOARD_SHORTCUT.key &&
        e.ctrlKey === KEYBOARD_SHORTCUT.ctrlKey &&
        e.shiftKey === KEYBOARD_SHORTCUT.shiftKey
      ) {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Validate environment variables on mount
  // ─────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const validations = [
      validateEnvVar('VITE_API_BASE_URL', VITE_API_BASE_URL),
      validateEnvVar('VITE_DRAGONFLY_API_KEY', VITE_DRAGONFLY_API_KEY),
    ];
    setEnvValidations(validations);
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Close on escape key
  // ─────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isOpen]);

  // ─────────────────────────────────────────────────────────────────────────
  // Run smoke tests
  // ─────────────────────────────────────────────────────────────────────────
  const runSmokeTests = useCallback(async () => {
    if (!VITE_API_BASE_URL) {
      addToast({
        variant: 'error',
        title: 'Configuration Error',
        description: 'VITE_API_BASE_URL is not set',
      });
      return;
    }

    setIsRunning(true);
    setResults([]);

    // Initialize all endpoints as pending
    const initialResults: EndpointResult[] = ENDPOINTS_TO_TEST.map((ep) => ({
      name: ep.name,
      endpoint: ep.endpoint,
      status: 'pending',
      httpCode: null,
      latencyMs: null,
      responseSnippet: null,
      error: null,
    }));
    setResults(initialResults);

    // Test each endpoint concurrently
    const testPromises = ENDPOINTS_TO_TEST.map(async (ep, index) => {
      const startTime = performance.now();

      try {
        const url = new URL(ep.endpoint, VITE_API_BASE_URL).href;
        const headers: Record<string, string> = {
          Accept: 'application/json',
        };

        if (ep.requiresAuth && VITE_DRAGONFLY_API_KEY) {
          headers['X-DRAGONFLY-API-KEY'] = VITE_DRAGONFLY_API_KEY;
        }

        const response = await fetch(url, {
          method: 'GET',
          headers,
        });

        const latencyMs = Math.round(performance.now() - startTime);

        let responseSnippet = '';
        try {
          const text = await response.text();
          responseSnippet = truncate(text, 50);
        } catch {
          responseSnippet = '(unable to read body)';
        }

        const result: EndpointResult = {
          name: ep.name,
          endpoint: ep.endpoint,
          status: response.ok ? 'success' : response.status >= 500 ? 'error' : 'warning',
          httpCode: response.status,
          latencyMs,
          responseSnippet,
          error: response.ok ? null : `HTTP ${response.status}`,
        };

        // Update this specific result
        setResults((prev) => {
          const updated = [...prev];
          updated[index] = result;
          return updated;
        });

        if (!response.ok) {
          addToast({
            variant: response.status >= 500 ? 'error' : 'warning',
            title: `${ep.name} Failed`,
            description: `HTTP ${response.status} - ${ep.endpoint}`,
          });
        }

        return result;
      } catch (err) {
        const latencyMs = Math.round(performance.now() - startTime);
        const errorMessage = err instanceof Error ? err.message : 'Network error';

        const result: EndpointResult = {
          name: ep.name,
          endpoint: ep.endpoint,
          status: 'error',
          httpCode: null,
          latencyMs,
          responseSnippet: null,
          error: errorMessage,
        };

        setResults((prev) => {
          const updated = [...prev];
          updated[index] = result;
          return updated;
        });

        addToast({
          variant: 'error',
          title: `${ep.name} Error`,
          description: errorMessage,
        });

        return result;
      }
    });

    await Promise.all(testPromises);
    setIsRunning(false);
  }, [addToast]);

  // ─────────────────────────────────────────────────────────────────────────
  // Copy URL to clipboard
  // ─────────────────────────────────────────────────────────────────────────
  const copyUrlToClipboard = useCallback(async () => {
    if (VITE_API_BASE_URL) {
      await navigator.clipboard.writeText(VITE_API_BASE_URL);
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    }
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Status icon helper
  // ─────────────────────────────────────────────────────────────────────────
  const getStatusIcon = (status: EndpointResult['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
      case 'error':
        return <XCircle className="h-4 w-4 text-red-400" />;
      case 'warning':
        return <AlertTriangle className="h-4 w-4 text-amber-400" />;
      default:
        return <RefreshCw className="h-4 w-4 text-slate-400 animate-spin" />;
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Summary stats
  // ─────────────────────────────────────────────────────────────────────────
  const successCount = results.filter((r) => r.status === 'success').length;
  const errorCount = results.filter((r) => r.status === 'error').length;
  const warningCount = results.filter((r) => r.status === 'warning').length;
  const avgLatency =
    results.length > 0
      ? Math.round(
          results.filter((r) => r.latencyMs !== null).reduce((sum, r) => sum + (r.latencyMs ?? 0), 0) /
            results.filter((r) => r.latencyMs !== null).length
        )
      : 0;

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Hidden trigger button - small bug icon in corner */}
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          'fixed bottom-4 left-4 z-40 p-2 rounded-full transition-all duration-200',
          'bg-slate-800/80 hover:bg-slate-700 border border-slate-700/50',
          'text-slate-500 hover:text-cyan-400',
          'opacity-30 hover:opacity-100',
          'focus:outline-none focus:ring-2 focus:ring-cyan-500/50'
        )}
        title="System Diagnostics (Ctrl+Shift+D)"
        aria-label="Open system diagnostics"
      >
        <Bug className="h-4 w-4" />
      </button>

      {/* Modal/Panel */}
      <AnimatePresence>
        {isOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
              onClick={() => setIsOpen(false)}
            />

            {/* Panel */}
            <motion.div
              ref={panelRef}
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className={cn(
                'fixed inset-4 z-50 overflow-hidden rounded-2xl',
                'bg-dragonfly-navy-950 border border-slate-700/50',
                'shadow-2xl shadow-black/50',
                'flex flex-col',
                'md:inset-x-16 md:inset-y-8 lg:inset-x-32 lg:inset-y-12'
              )}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between border-b border-slate-700/50 px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/10">
                    <Bug className="h-5 w-5 text-cyan-400" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-white">System Diagnostics</h2>
                    <p className="text-xs text-slate-500">Environment validation & API smoke tests</p>
                  </div>
                </div>
                <button
                  onClick={() => setIsOpen(false)}
                  className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
                  aria-label="Close diagnostics"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Content - Scrollable */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {/* ═══════════════════════════════════════════════════════════ */}
                {/* ENV VAR CONFIGURATION */}
                {/* ═══════════════════════════════════════════════════════════ */}
                <section>
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-white mb-4">
                    <Shield className="h-4 w-4 text-cyan-400" />
                    Environment Configuration
                  </h3>

                  <div className="space-y-3">
                    {envValidations.map((validation) => (
                      <div
                        key={validation.variable}
                        className={cn(
                          'rounded-xl border p-4',
                          validation.isValid
                            ? 'border-slate-700/50 bg-slate-900/50'
                            : 'border-amber-500/30 bg-amber-500/5'
                        )}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              {validation.isValid ? (
                                <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                              ) : (
                                <AlertTriangle className="h-4 w-4 text-amber-400 flex-shrink-0" />
                              )}
                              <span className="font-mono text-xs text-slate-400">
                                {validation.variable}
                              </span>
                            </div>
                            <p className="mt-1 font-mono text-sm text-white break-all">
                              {validation.masked}
                            </p>
                            {validation.issues.length > 0 && (
                              <ul className="mt-2 space-y-1">
                                {validation.issues.map((issue, i) => (
                                  <li key={i} className="text-xs text-amber-400 flex items-center gap-1.5">
                                    <span className="h-1 w-1 rounded-full bg-amber-400" />
                                    {issue}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          {validation.variable.includes('URL') && validation.value && (
                            <button
                              onClick={copyUrlToClipboard}
                              className="flex-shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
                              title="Copy URL"
                            >
                              {copiedUrl ? (
                                <Check className="h-4 w-4 text-emerald-400" />
                              ) : (
                                <Copy className="h-4 w-4" />
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                {/* ═══════════════════════════════════════════════════════════ */}
                {/* SMOKE TEST RUNNER */}
                {/* ═══════════════════════════════════════════════════════════ */}
                <section>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                      <Activity className="h-4 w-4 text-cyan-400" />
                      API Surface Smoke Test
                    </h3>
                    <button
                      onClick={runSmokeTests}
                      disabled={isRunning}
                      className={cn(
                        'flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all',
                        'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30',
                        'hover:bg-cyan-500/20 hover:border-cyan-500/50',
                        'disabled:opacity-50 disabled:cursor-not-allowed',
                        'focus:outline-none focus:ring-2 focus:ring-cyan-500/50'
                      )}
                    >
                      {isRunning ? (
                        <>
                          <RefreshCw className="h-4 w-4 animate-spin" />
                          Running…
                        </>
                      ) : (
                        <>
                          <Play className="h-4 w-4" />
                          Run System Check
                        </>
                      )}
                    </button>
                  </div>

                  {/* Summary Stats */}
                  {results.length > 0 && (
                    <div className="grid grid-cols-4 gap-3 mb-4">
                      <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-3 text-center">
                        <div className="text-2xl font-bold text-emerald-400">{successCount}</div>
                        <div className="text-[10px] uppercase tracking-wider text-emerald-500/80">Passed</div>
                      </div>
                      <div className="rounded-xl bg-red-500/10 border border-red-500/20 p-3 text-center">
                        <div className="text-2xl font-bold text-red-400">{errorCount}</div>
                        <div className="text-[10px] uppercase tracking-wider text-red-500/80">Failed</div>
                      </div>
                      <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 p-3 text-center">
                        <div className="text-2xl font-bold text-amber-400">{warningCount}</div>
                        <div className="text-[10px] uppercase tracking-wider text-amber-500/80">Warnings</div>
                      </div>
                      <div className="rounded-xl bg-slate-500/10 border border-slate-500/20 p-3 text-center">
                        <div className="text-2xl font-bold text-slate-300">{avgLatency}ms</div>
                        <div className="text-[10px] uppercase tracking-wider text-slate-500">Avg Latency</div>
                      </div>
                    </div>
                  )}

                  {/* Results Table */}
                  {results.length > 0 && (
                    <div className="rounded-xl border border-slate-700/50 overflow-hidden">
                      <table className="w-full text-left">
                        <thead>
                          <tr className="border-b border-slate-700/50 bg-slate-900/50">
                            <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                              Endpoint
                            </th>
                            <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400 text-center">
                              Status
                            </th>
                            <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400 text-center">
                              HTTP
                            </th>
                            <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400 text-center">
                              Latency
                            </th>
                            <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                              Response / Error
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-700/30">
                          {results.map((result) => (
                            <tr
                              key={result.endpoint}
                              className={cn(
                                'transition-colors',
                                result.status === 'error' && 'bg-red-500/5',
                                result.status === 'warning' && 'bg-amber-500/5'
                              )}
                            >
                              <td className="px-4 py-3">
                                <div className="text-sm font-medium text-white">{result.name}</div>
                                <div className="text-xs font-mono text-slate-500">{result.endpoint}</div>
                              </td>
                              <td className="px-4 py-3 text-center">
                                {getStatusIcon(result.status)}
                              </td>
                              <td className="px-4 py-3 text-center">
                                <span
                                  className={cn(
                                    'font-mono text-sm',
                                    result.httpCode === null
                                      ? 'text-slate-500'
                                      : result.httpCode < 300
                                        ? 'text-emerald-400'
                                        : result.httpCode < 500
                                          ? 'text-amber-400'
                                          : 'text-red-400'
                                  )}
                                >
                                  {result.httpCode ?? '—'}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-center">
                                <span className="font-mono text-sm text-slate-300">
                                  {result.latencyMs !== null ? `${result.latencyMs}ms` : '—'}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                <span
                                  className={cn(
                                    'font-mono text-xs',
                                    result.error ? 'text-red-400' : 'text-slate-500'
                                  )}
                                >
                                  {result.error ?? result.responseSnippet ?? '—'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Empty state */}
                  {results.length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-700/50 p-8 text-center">
                      <Server className="mx-auto h-10 w-10 text-slate-600 mb-3" />
                      <p className="text-sm text-slate-400">
                        Click "Run System Check" to test all API endpoints
                      </p>
                      <p className="text-xs text-slate-500 mt-1">
                        Tests {ENDPOINTS_TO_TEST.length} critical endpoints concurrently
                      </p>
                    </div>
                  )}
                </section>

                {/* ═══════════════════════════════════════════════════════════ */}
                {/* QUICK LINKS */}
                {/* ═══════════════════════════════════════════════════════════ */}
                <section>
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-white mb-4">
                    <ExternalLink className="h-4 w-4 text-cyan-400" />
                    Quick Links
                  </h3>

                  <div className="flex flex-wrap gap-2">
                    {VITE_API_BASE_URL && (
                      <>
                        <a
                          href={`${VITE_API_BASE_URL}/docs`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
                            'bg-slate-800 text-slate-300 border border-slate-700/50',
                            'hover:bg-slate-700 hover:text-white transition-colors'
                          )}
                        >
                          <Database className="h-3 w-3" />
                          API Docs
                        </a>
                        <a
                          href={`${VITE_API_BASE_URL}/health`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
                            'bg-slate-800 text-slate-300 border border-slate-700/50',
                            'hover:bg-slate-700 hover:text-white transition-colors'
                          )}
                        >
                          <Wifi className="h-3 w-3" />
                          Health Endpoint
                        </a>
                        <a
                          href={`${VITE_API_BASE_URL}/api/health/db`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium',
                            'bg-slate-800 text-slate-300 border border-slate-700/50',
                            'hover:bg-slate-700 hover:text-white transition-colors'
                          )}
                        >
                          <Activity className="h-3 w-3" />
                          DB Health
                        </a>
                      </>
                    )}
                  </div>
                </section>
              </div>

              {/* Footer */}
              <div className="border-t border-slate-700/50 px-6 py-3 bg-slate-900/50">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>
                    Press <kbd className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">Ctrl+Shift+D</kbd> to
                    toggle • <kbd className="font-mono bg-slate-800 px-1.5 py-0.5 rounded">Esc</kbd> to close
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Clock className="h-3 w-3" />
                    {new Date().toLocaleTimeString()}
                  </span>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
};

export default SystemDiagnostics;
