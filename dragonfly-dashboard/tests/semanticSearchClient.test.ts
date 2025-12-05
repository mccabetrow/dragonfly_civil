/**
 * Tests for Semantic Search Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Lightweight tests for the semantic search API wrapper.
 * Uses mocked fetch to avoid hitting real API.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  searchSimilarJudgments,
  buildJudgmentContext,
  type SemanticSearchResponse,
} from '../src/lib/semanticSearchClient';

// ═══════════════════════════════════════════════════════════════════════════
// MOCKS
// ═══════════════════════════════════════════════════════════════════════════

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  mockFetch.mockReset();
});

// ═══════════════════════════════════════════════════════════════════════════
// searchSimilarJudgments Tests
// ═══════════════════════════════════════════════════════════════════════════

describe('searchSimilarJudgments', () => {
  const mockResponse: SemanticSearchResponse = {
    query: 'construction company Queens',
    results: [
      {
        id: 1,
        plaintiff_name: 'ABC Construction LLC',
        defendant_name: 'John Smith',
        judgment_amount: 50000,
        county: 'Queens',
        case_number: 'QN-2024-001',
        score: 0.92,
      },
      {
        id: 2,
        plaintiff_name: 'XYZ Builders Inc',
        defendant_name: 'Jane Doe',
        judgment_amount: 35000,
        county: 'Queens',
        case_number: 'QN-2024-002',
        score: 0.87,
      },
    ],
    count: 2,
  };

  it('should return results on successful search', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    const result = await searchSimilarJudgments('construction company Queens', 5);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.count).toBe(2);
      expect(result.data.results).toHaveLength(2);
      expect(result.data.results[0].plaintiff_name).toBe('ABC Construction LLC');
      expect(result.data.results[0].score).toBe(0.92);
    }
  });

  it('should send correct request body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    await searchSimilarJudgments('test query', 10);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/search/semantic'),
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: 'test query', limit: 10 }),
      })
    );
  });

  it('should trim query and clamp limit', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    await searchSimilarJudgments('  spaced query  ', 100);

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({ query: 'spaced query', limit: 50 }),
      })
    );
  });

  it('should handle HTTP error with detail message', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ detail: 'Database connection failed' }),
    });

    const result = await searchSimilarJudgments('test', 5);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe('Database connection failed');
    }
  });

  it('should handle HTTP error without parseable body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => {
        throw new Error('Invalid JSON');
      },
    });

    const result = await searchSimilarJudgments('test', 5);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe('HTTP 502: Bad Gateway');
    }
  });

  it('should handle network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Failed to fetch'));

    const result = await searchSimilarJudgments('test', 5);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain('Network error');
      expect(result.error).toContain('Failed to fetch');
    }
  });

  it('should handle non-Error thrown', async () => {
    mockFetch.mockRejectedValueOnce('string error');

    const result = await searchSimilarJudgments('test', 5);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain('Unknown error');
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// buildJudgmentContext Tests
// ═══════════════════════════════════════════════════════════════════════════

describe('buildJudgmentContext', () => {
  it('should build full context string with all fields', () => {
    const context = buildJudgmentContext({
      plaintiffName: 'ABC Corp',
      defendantName: 'John Doe',
      judgmentAmount: 50000,
      court: 'Supreme Court',
      county: 'Queens',
    });

    expect(context).toContain('Plaintiff: ABC Corp');
    expect(context).toContain('Defendant: John Doe');
    expect(context).toContain('Amount: $50,000');
    expect(context).toContain('Court: Supreme Court');
    expect(context).toContain('County: Queens');
  });

  it('should handle missing fields gracefully', () => {
    const context = buildJudgmentContext({
      plaintiffName: 'ABC Corp',
      defendantName: null,
      judgmentAmount: undefined,
    });

    expect(context).toContain('Plaintiff: ABC Corp');
    expect(context).not.toContain('Defendant');
    expect(context).not.toContain('Amount');
  });

  it('should return fallback for empty object', () => {
    const context = buildJudgmentContext({});

    expect(context).toBe('judgment case');
  });

  it('should format currency correctly', () => {
    const context = buildJudgmentContext({
      judgmentAmount: 1234567.89,
    });

    expect(context).toContain('Amount: $1,234,567.89');
  });
});
