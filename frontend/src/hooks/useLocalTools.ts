import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface ToolSummary {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  validation_status: string;
  last_scanned_at: string;
}

export interface ToolListResponse {
  tools: ToolSummary[];
  scanned_at: string | null;
}

export interface ToolDetailResponse {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  validation_status: string;
  last_scanned_at: string;
  last_validated_at: string | null;
}

export interface ToolValidationResponse {
  tool_id: string;
  status: string;
  latency_ms: number;
  error: string | null;
}

export function useLocalTools() {
  return useQuery<ToolListResponse>({
    queryKey: ['local-tools'],
    queryFn: () => api.get<ToolListResponse>('/tools'),
  });
}

export function useToolDetail(toolId?: string) {
  return useQuery<ToolDetailResponse>({
    queryKey: ['tool-detail', toolId],
    queryFn: () => api.get<ToolDetailResponse>(`/tools/${toolId}`),
    enabled: Boolean(toolId),
  });
}

export function useDiscoverTools() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.post<ToolListResponse>('/tools/discover'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['local-tools'] });
    },
  });
}

export function useValidateTool(toolId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.post<ToolValidationResponse>(`/tools/${toolId}/validate`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tool-detail', toolId] });
      void queryClient.invalidateQueries({ queryKey: ['local-tools'] });
    },
  });
}

