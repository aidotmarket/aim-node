import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface SetupStatusResponse {
  setup_complete: boolean;
  locked: boolean;
  unlocked: boolean;
  current_step: number;
}

export function useSetupStatus() {
  return useQuery<SetupStatusResponse>({
    queryKey: ['setup-status'],
    queryFn: () => api.get<SetupStatusResponse>('/setup/status'),
    staleTime: 30000,
  });
}
