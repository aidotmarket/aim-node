import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

interface SetupStatusResponse {
  complete: boolean;
  steps: Record<string, boolean>;
}

export function useSetupStatus() {
  return useQuery<SetupStatusResponse>({
    queryKey: ['setup-status'],
    queryFn: () => api.get<SetupStatusResponse>('/setup/status'),
    staleTime: 30000,
  });
}
