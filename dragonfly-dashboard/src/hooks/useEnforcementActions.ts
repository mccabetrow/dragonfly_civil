/**
 * useEnforcementActions
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hook for triggering enforcement actions from the Action Center.
 * Provides async methods for packet generation with polling, status updates, etc.
 * 
 * Features:
 *   - Async packet generation with job polling
 *   - Realtime subscriptions for instant status updates
 *   - Green flash animation on packet completion
 */
import { useCallback, useState, useRef, useEffect } from 'react';
import { apiClient } from '../lib/apiClient';
import { usePacketRealtime, useJobQueueRealtime } from './useRealtimeSubscription';
import { IS_DEMO_MODE } from '../lib/supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface GeneratePacketRequest {
  judgmentId: string;
  strategy?: 'wage_garnishment' | 'bank_levy' | 'asset_seizure';
}

export interface GeneratePacketResponse {
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'error';
  jobId: string | null;
  packetId: string | null;
  message: string;
  estimatedCompletion?: string;
}

export interface JobStatusResponse {
  jobId: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  packetId: string | null;
  errorMessage: string | null;
  createdAt: string | null;
  updatedAt: string | null;
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
  /** True when a realtime update just occurred (for flash animation) */
  isFlashing: boolean;
  /** Whether connected to realtime channels */
  isRealtimeConnected: boolean;
  /** Number of realtime events received */
  realtimeEventCount: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// API TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface ApiGeneratePacketResponse {
  status: string;
  job_id: string | null;
  packet_id: string | null;
  message: string;
  estimated_completion?: string;
}

interface ApiJobStatusResponse {
  job_id: string;
  status: string;
  packet_id: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 60; // 2 minutes max polling
const FLASH_DURATION_MS = 1500; // Duration of green flash animation

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
  const [isFlashing, setIsFlashing] = useState(false);
  const pollingRef = useRef<Map<string, boolean>>(new Map());
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Flash animation handler
  const triggerFlash = useCallback(() => {
    setIsFlashing(true);
    
    if (flashTimeoutRef.current) {
      clearTimeout(flashTimeoutRef.current);
    }
    
    flashTimeoutRef.current = setTimeout(() => {
      setIsFlashing(false);
    }, FLASH_DURATION_MS);
  }, []);

  // Cleanup flash timeout on unmount
  useEffect(() => {
    return () => {
      if (flashTimeoutRef.current) {
        clearTimeout(flashTimeoutRef.current);
      }
    };
  }, []);

  // ═══════════════════════════════════════════════════════════════════════════
  // REALTIME SUBSCRIPTIONS
  // ═══════════════════════════════════════════════════════════════════════════

  // Subscribe to packet creation events
  const packetRealtime = usePacketRealtime({
    onPacketCreated: (_packetId, strategy) => {
      console.log(`[Realtime] Packet created with strategy: ${strategy}`);
    },
    onFlash: triggerFlash,
    enabled: !IS_DEMO_MODE,
  });

  // Subscribe to job completions
  const jobRealtime = useJobQueueRealtime({
    onJobComplete: (_jobId, status) => {
      if (status === 'completed') {
        triggerFlash();
      }
    },
    enabled: !IS_DEMO_MODE,
  });

  /**
   * Poll job status until complete or failed
   */
  const pollJobStatus = useCallback(
    async (jobId: string, judgmentId: string): Promise<JobStatusResponse> => {
      pollingRef.current.set(judgmentId, true);
      let attempts = 0;

      while (attempts < MAX_POLL_ATTEMPTS) {
        // Check if polling was cancelled
        if (!pollingRef.current.get(judgmentId)) {
          throw new Error('Polling cancelled');
        }

        try {
          const response = await apiClient.get<ApiJobStatusResponse>(
            `/api/v1/enforcement/job-status/${jobId}`
          );

          const status = response.status as JobStatusResponse['status'];

          // Update state with current status
          setState((prev) => ({
            ...prev,
            lastResult: {
              status: status === 'pending' ? 'queued' : status,
              jobId,
              packetId: response.packet_id,
              message: `Job ${status}`,
            },
          }));

          // Check for terminal states
          if (status === 'completed' || status === 'failed') {
            pollingRef.current.delete(judgmentId);
            return {
              jobId: response.job_id,
              status,
              packetId: response.packet_id,
              errorMessage: response.error_message,
              createdAt: response.created_at,
              updatedAt: response.updated_at,
            };
          }
        } catch (err) {
          console.error('Polling error:', err);
          // Continue polling on transient errors
        }

        // Wait before next poll
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        attempts++;
      }

      pollingRef.current.delete(judgmentId);
      throw new Error('Job timed out waiting for completion');
    },
    []
  );

  const generatePacket = useCallback(
    async (request: GeneratePacketRequest): Promise<GeneratePacketResponse> => {
      const { judgmentId, strategy } = request;

      // Add to processing set
      setProcessingIds((prev) => new Set(prev).add(judgmentId));
      setState((prev) => ({ ...prev, isLoading: true, error: null }));

      try {
        // 1. Queue the job
        const response = await apiClient.post<ApiGeneratePacketResponse>(
          '/api/v1/enforcement/generate-packet',
          {
            judgment_id: judgmentId,
            strategy: strategy ?? 'wage_garnishment',
          }
        );

        const jobId = response.job_id;

        // Initial queued state
        let result: GeneratePacketResponse = {
          status: response.status as GeneratePacketResponse['status'],
          jobId,
          packetId: response.packet_id,
          message: response.message,
          estimatedCompletion: response.estimated_completion,
        };

        setState({
          isLoading: true,
          error: null,
          lastResult: result,
        });

        // 2. If we have a job_id, poll for completion
        if (jobId) {
          const finalStatus = await pollJobStatus(jobId, judgmentId);

          result = {
            status: finalStatus.status === 'completed' ? 'completed' : 'failed',
            jobId,
            packetId: finalStatus.packetId,
            message:
              finalStatus.status === 'completed'
                ? 'Enforcement packet generated successfully'
                : finalStatus.errorMessage ?? 'Packet generation failed',
          };
        }

        setState({
          isLoading: false,
          error: result.status === 'failed' ? result.message : null,
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
        pollingRef.current.delete(judgmentId);
      }
    },
    [pollJobStatus]
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
    isFlashing,
    isRealtimeConnected: packetRealtime.isConnected || jobRealtime.isConnected,
    realtimeEventCount: packetRealtime.eventCount + jobRealtime.eventCount,
  };
}
