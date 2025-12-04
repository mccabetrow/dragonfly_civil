/**
 * PacketGenerator Component
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Generates court-ready legal packets (DOCX) for enforcement.
 * Designed to plug into the Radar Detail Drawer.
 *
 * Supports:
 * - Income Execution (NY) - Wage garnishment
 * - Information Subpoena (NY) - Discovery
 */

import { useState } from 'react';
import { Card, Title, Text, Select, SelectItem, Button } from '@tremor/react';
import { FileText, Download, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type PacketType = 'income_execution_ny' | 'info_subpoena_ny';

export interface PacketGeneratorProps {
  judgmentId: number;
  defaultPacketType?: PacketType;
}

interface PacketResponse {
  packet_url: string;
  packet_type: string;
  judgment_id: number;
}

type GenerationStatus = 'idle' | 'loading' | 'success' | 'error';

// ═══════════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════════

const PACKET_TYPES: { value: PacketType; label: string; description: string }[] = [
  {
    value: 'income_execution_ny',
    label: 'Income Execution (NY)',
    description: 'Wage garnishment order for employers',
  },
  {
    value: 'info_subpoena_ny',
    label: 'Information Subpoena (NY)',
    description: 'Discovery document for financial info',
  },
];

function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  return envUrl || '';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export function PacketGenerator({
  judgmentId,
  defaultPacketType = 'income_execution_ny',
}: PacketGeneratorProps) {
  const [packetType, setPacketType] = useState<PacketType>(defaultPacketType);
  const [status, setStatus] = useState<GenerationStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [packetUrl, setPacketUrl] = useState<string | null>(null);

  const handleGenerate = async () => {
    setStatus('loading');
    setErrorMessage(null);
    setPacketUrl(null);

    try {
      const baseUrl = getApiBaseUrl();
      const response = await fetch(`${baseUrl}/api/v1/packets/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          judgment_id: judgmentId,
          type: packetType,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Request failed: ${response.status}`);
      }

      const data: PacketResponse = await response.json();
      setPacketUrl(data.packet_url);
      setStatus('success');

      // Open download in new tab
      window.open(data.packet_url, '_blank');
    } catch (err) {
      console.error('Packet generation failed:', err);
      setErrorMessage(err instanceof Error ? err.message : 'Failed to generate packet');
      setStatus('error');
    }
  };

  const handleDownload = () => {
    if (packetUrl) {
      window.open(packetUrl, '_blank');
    }
  };

  const selectedType = PACKET_TYPES.find((t) => t.value === packetType);

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="h-5 w-5 text-blue-500" />
        <Title className="text-base">Legal Packets</Title>
      </div>

      <div className="space-y-4">
        {/* Packet Type Selector */}
        <div>
          <Text className="text-xs text-gray-500 mb-1">Document Type</Text>
          <Select
            value={packetType}
            onValueChange={(value) => setPacketType(value as PacketType)}
            disabled={status === 'loading'}
          >
            {PACKET_TYPES.map((type) => (
              <SelectItem key={type.value} value={type.value}>
                {type.label}
              </SelectItem>
            ))}
          </Select>
          {selectedType && (
            <Text className="text-xs text-gray-400 mt-1">{selectedType.description}</Text>
          )}
        </div>

        {/* Generate Button */}
        <Button
          onClick={handleGenerate}
          disabled={status === 'loading'}
          className="w-full"
          color="blue"
        >
          {status === 'loading' ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <FileText className="h-4 w-4 mr-2" />
              Generate Packet
            </>
          )}
        </Button>

        {/* Status Messages */}
        {status === 'success' && packetUrl && (
          <div className="flex items-center gap-2 p-3 bg-green-50 rounded-lg border border-green-200">
            <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <Text className="text-sm text-green-800 font-medium">Packet Ready</Text>
              <Text className="text-xs text-green-600 truncate">
                Download started automatically
              </Text>
            </div>
            <Button
              size="xs"
              variant="secondary"
              onClick={handleDownload}
              className="flex-shrink-0"
            >
              <Download className="h-3 w-3 mr-1" />
              Download
            </Button>
          </div>
        )}

        {status === 'error' && errorMessage && (
          <div className="flex items-start gap-2 p-3 bg-red-50 rounded-lg border border-red-200">
            <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <Text className="text-sm text-red-800 font-medium">Generation Failed</Text>
              <Text className="text-xs text-red-600">{errorMessage}</Text>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default PacketGenerator;
