import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

interface HealthResponse {
  status: string;
  locked: boolean;
  setup_complete: boolean;
}

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => api.get<HealthResponse>('/health'),
    refetchInterval: 10000,
    refetchOnWindowFocus: true,
  });
}
