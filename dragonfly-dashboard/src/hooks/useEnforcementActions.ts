/**
 * useEnforcementActions
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for triggering enforcement actions from the Action Center.
 * Provides async methods for packet generation, status updates, etc.
 */
import { useCallback, useState } from 'react';
import { apiClient } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface GeneratePacketRequest {
  judgmentId: string;
  strategy?: 'wage_garnishment' | 'bank_levy' | 'asset_seizure';
}

export interface GeneratePacketResponse {
  status: 'queued' | 'processing' | 'completed' | 'error';
  packetId: string;
  message: string;
  estimatedCompletion?: string;
}

export interface ActionState {
  isLoading: boolean;
  error: string | null;
  lastResult: GeneratePacketResponse | null;
}

export interface UseEnforcementActionsResult {
  /** Generate an enforcement packet for a judgment */
  generatePacket: (request: GeneratePacketRequest) => Promise<GeneratePacketResponse>;
  /** Current state of the last action */
  state: ActionState;
  /** Set of judgment IDs currently being processed */
  processingIds: Set<string>;
  /** Check if a specific judgment is being processed */
  isProcessing: (judgmentId: string) => boolean;
  /** Clear any error state */
  clearError: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// API TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface ApiGeneratePacketResponse {
  status: string;
  packet_id: string;
  message: string;
  estimated_completion?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useEnforcementActions(): UseEnforcementActionsResult {
  const [state, setState] = useState<ActionState>({
    isLoading: false,
    error: null,
    lastResult: null,
  });
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());

  const generatePacket = useCallback(
    async (request: GeneratePacketRequest): Promise<GeneratePacketResponse> => {
      const { judgmentId, strategy } = request;

      // Add to processing set
      setProcessingIds((prev) => new Set(prev).add(judgmentId));
      setState((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        const response = await apiClient.post<ApiGeneratePacketResponse>(
          '/api/v1/enforcement/generate-packet',
          {
            judgment_id: judgmentId,
            strategy: strategy ?? 'wage_garnishment',
          }
        );

        const result: GeneratePacketResponse = {
          status: response.status as GeneratePacketResponse['status'],
          packetId: response.packet_id,
          message: response.message,
          estimatedCompletion: response.estimated_completion,
        };

        setState({
          isLoading: false,
          error: null,
          lastResult: result,
        });

        return result;
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : 'Failed to generate packet';

        setState({
          isLoading: false,
          error: errorMessage,
          lastResult: null,
        });

        throw err;
      } finally {
        // Remove from processing set
        setProcessingIds((prev) => {
          const next = new Set(prev);
          next.delete(judgmentId);
          return next;
        });
      }
    },
    []
  );

  const isProcessing = useCallback(
    (judgmentId: string): boolean => processingIds.has(judgmentId),
    [processingIds]
  );

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    generatePacket,
    state,
    processingIds,
    isProcessing,
    clearError,
  };
}
