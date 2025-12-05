/**
 * Tests for API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the centralized API client's auth header behavior.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ═══════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════

describe('apiClient', () => {
  const mockFetch = vi.fn();
  
  beforeEach(() => {
    vi.resetModules();
    global.fetch = mockFetch;
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe('when VITE_DRAGONFLY_API_KEY is set', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_DRAGONFLY_API_KEY', 'test-api-key-123');
    });

    it('getAuthHeaders includes X-API-KEY header', async () => {
      const { getAuthHeaders } = await import('../src/lib/apiClient');
      
      const headers = getAuthHeaders();
      
      expect(headers['X-API-KEY']).toBe('test-api-key-123');
      expect(headers['Content-Type']).toBe('application/json');
    });

    it('getAuthHeaders skips Content-Type when requested', async () => {
      const { getAuthHeaders } = await import('../src/lib/apiClient');
      
      const headers = getAuthHeaders(true);
      
      expect(headers['X-API-KEY']).toBe('test-api-key-123');
      expect(headers['Content-Type']).toBeUndefined();
    });

    it('apiRequest includes X-API-KEY in fetch call', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiRequest } = await import('../src/lib/apiClient');
      
      await apiRequest('/api/v1/test');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.headers['X-API-KEY']).toBe('test-api-key-123');
    });

    it('apiRequest does not allow caller to override X-API-KEY', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiRequest } = await import('../src/lib/apiClient');
      
      await apiRequest('/api/v1/test', {
        headers: { 'X-API-KEY': 'malicious-override' },
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      // Auth header should NOT be overridden
      expect(options.headers['X-API-KEY']).toBe('test-api-key-123');
    });

    it('apiRequest allows caller to add custom headers', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiRequest } = await import('../src/lib/apiClient');
      
      await apiRequest('/api/v1/test', {
        headers: { 'X-Custom-Header': 'custom-value' },
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.headers['X-API-KEY']).toBe('test-api-key-123');
      expect(options.headers['X-Custom-Header']).toBe('custom-value');
    });

    it('apiUpload includes X-API-KEY for file uploads', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ batch_id: 'test-batch' }),
      });

      const { apiUpload } = await import('../src/lib/apiClient');
      const formData = new FormData();
      formData.append('file', new File(['test'], 'test.csv'));
      
      await apiUpload('/api/v1/intake/upload', formData);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.headers['X-API-KEY']).toBe('test-api-key-123');
      // Should NOT have Content-Type (let browser set it for FormData)
      expect(options.headers['Content-Type']).toBeUndefined();
    });
  });

  describe('when VITE_DRAGONFLY_API_KEY is not set', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_DRAGONFLY_API_KEY', '');
    });

    it('getAuthHeaders does NOT include X-API-KEY header', async () => {
      const { getAuthHeaders } = await import('../src/lib/apiClient');
      
      const headers = getAuthHeaders();
      
      expect(headers['X-API-KEY']).toBeUndefined();
      expect(headers['Content-Type']).toBe('application/json');
    });

    it('apiRequest still works without API key', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiRequest } = await import('../src/lib/apiClient');
      
      await apiRequest('/api/v1/test');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      expect(options.headers['X-API-KEY']).toBeUndefined();
    });

    it('does not throw or crash', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiJson } = await import('../src/lib/apiClient');
      
      // Should not throw
      const result = await apiJson('/api/v1/test');
      expect(result).toEqual({ success: true });
    });
  });
});
