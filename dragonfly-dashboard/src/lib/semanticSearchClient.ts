/**
 * Semantic Search API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Client wrapper for the /api/v1/search/semantic endpoint.
 * Used for finding similar judgments based on natural language queries.
 */

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface JudgmentSearchResult {
  id: number;
  plaintiff_name: string | null;
  defendant_name: string | null;
  judgment_amount: number | null;
  county: string | null;
  case_number: string | null;
  score: number;
}

export interface SemanticSearchResponse {
  query: string;
  results: JudgmentSearchResult[];
  count: number;
}

export interface SemanticSearchError {
  detail: string;
}

export type SemanticSearchResult =
  | { ok: true; data: SemanticSearchResponse }
  | { ok: false; error: string };

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Get the API base URL from environment or default to relative path.
 * In production, Vercel rewrites /api/* to the backend.
 * In development, we may need to proxy.
 */
function getApiBaseUrl(): string {
  // Check for explicit API URL in environment
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl) return envUrl;

  // Default: relative path (works with Vercel rewrites or same-origin)
  return '';
}

// ═══════════════════════════════════════════════════════════════════════════
// API FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Search for judgments semantically similar to the given query.
 *
 * @param query - Natural language search query
 * @param limit - Maximum number of results (1-50, default 5)
 * @returns Search results or error
 */
export async function searchSimilarJudgments(
  query: string,
  limit: number = 5
): Promise<SemanticSearchResult> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/search/semantic`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: query.trim(),
        limit: Math.min(Math.max(limit, 1), 50),
      }),
    });

    if (!response.ok) {
      // Try to parse error message from response
      try {
        const errorData = (await response.json()) as SemanticSearchError;
        return { ok: false, error: errorData.detail || `HTTP ${response.status}` };
      } catch {
        return { ok: false, error: `HTTP ${response.status}: ${response.statusText}` };
      }
    }

    const data = (await response.json()) as SemanticSearchResponse;
    return { ok: true, data };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return { ok: false, error: `Network error: ${message}` };
  }
}

/**
 * Build a context string for a judgment to use as a search query.
 * This creates a natural language description that will match similar cases.
 *
 * @param judgment - Judgment data to build context from
 * @returns Natural language context string
 */
export function buildJudgmentContext(judgment: {
  plaintiffName?: string | null;
  defendantName?: string | null;
  judgmentAmount?: number | null;
  court?: string | null;
  county?: string | null;
  caseNumber?: string | null;
}): string {
  const parts: string[] = [];

  if (judgment.plaintiffName) {
    parts.push(`Plaintiff: ${judgment.plaintiffName}`);
  }

  if (judgment.defendantName) {
    parts.push(`Defendant: ${judgment.defendantName}`);
  }

  if (judgment.judgmentAmount) {
    const formatted = new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
    }).format(judgment.judgmentAmount);
    parts.push(`Amount: ${formatted}`);
  }

  if (judgment.court) {
    parts.push(`Court: ${judgment.court}`);
  }

  if (judgment.county) {
    parts.push(`County: ${judgment.county}`);
  }

  return parts.join('. ') || 'judgment case';
}
