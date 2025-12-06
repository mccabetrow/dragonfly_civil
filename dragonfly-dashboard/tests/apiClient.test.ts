/**
 * Tests for API Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Tests the centralized API client's auth header behavior and URL resolution.
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

  // =========================================================================
  // URL Resolution Tests
  // =========================================================================

  describe('URL resolution', () => {
    it('uses dev default URL when VITE_API_BASE_URL is not set in dev mode', async () => {
      vi.stubEnv('VITE_API_BASE_URL', '');
      vi.stubEnv('PROD', false);
      vi.stubEnv('VITE_DRAGONFLY_API_KEY', '');
      
      const consoleSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
      
      const { API_BASE_URL } = await import('../src/lib/apiClient');
      
      expect(API_BASE_URL).toBe('http://127.0.0.1:8000/api');
      consoleSpy.mockRestore();
    });

    it('uses explicit VITE_API_BASE_URL when provided', async () => {
      vi.stubEnv('VITE_API_BASE_URL', 'https://custom-backend.example.com/api');
      vi.stubEnv('VITE_DRAGONFLY_API_KEY', '');
      
      const { API_BASE_URL } = await import('../src/lib/apiClient');
      
      expect(API_BASE_URL).toBe('https://custom-backend.example.com/api');
    });

    it('uses Railway production URL when set via env var', async () => {
      const railwayUrl = 'https://dragonflycivil-production-d57a.up.railway.app/api';
      vi.stubEnv('VITE_API_BASE_URL', railwayUrl);
      vi.stubEnv('VITE_DRAGONFLY_API_KEY', '');
      
      const { API_BASE_URL } = await import('../src/lib/apiClient');
      
      expect(API_BASE_URL).toBe(railwayUrl);
    });
  });

  // =========================================================================
  // Auth Header Tests - API Key Set
  // =========================================================================

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

    it('prevents caller from injecting fake X-API-KEY when no real key exists', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      const { apiRequest } = await import('../src/lib/apiClient');
      
      // Try to inject a fake API key
      await apiRequest('/api/v1/test', {
        headers: { 'X-API-KEY': 'fake-injected-key' },
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [, options] = mockFetch.mock.calls[0];
      // Injected key should be stripped when no real key is configured
      expect(options.headers['X-API-KEY']).toBeUndefined();
    });
  });
});
