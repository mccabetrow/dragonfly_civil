/**
 * Semantic Search API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Client wrapper for the /api/v1/search/semantic endpoint.
 * Used for finding similar judgments based on natural language queries.
 */
import { apiClient, AuthError, NotFoundError } from './apiClient';

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

export type SemanticSearchResult =
  | { ok: true; data: SemanticSearchResponse }
  | { ok: false; error: string; isAuthError?: boolean };

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
  try {
    const data = await apiClient.post<SemanticSearchResponse>('/api/v1/search/semantic', {
      query: query.trim(),
      limit: Math.min(Math.max(limit, 1), 50),
    });
    return { ok: true, data };
  } catch (err) {
    if (err instanceof AuthError) {
      return { ok: false, error: 'Authentication failed – check your API key', isAuthError: true };
    }
    if (err instanceof NotFoundError) {
      return { ok: false, error: 'Search endpoint not available' };
    }
    const message = err instanceof Error ? err.message : 'Unknown error';
    return { ok: false, error: message };
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
