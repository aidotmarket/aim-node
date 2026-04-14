import { create } from 'zustand';
import { api } from '@/lib/api';

interface HealthResponse {
  status: string;
  locked: boolean;
  setup_complete: boolean;
}

interface NodeState {
  setupComplete: boolean;
  locked: boolean;
  healthStatus: 'healthy' | 'degraded' | 'unknown';
  csrfToken: string | null;
  loading: boolean;
  bootstrap: () => Promise<void>;
}

export const useNodeStore = create<NodeState>((set) => ({
  setupComplete: false,
  locked: false,
  healthStatus: 'unknown',
  csrfToken: null,
  loading: false,

  bootstrap: async () => {
    set({ loading: true });
    try {
      const data = await api.get<HealthResponse>('/health');
      set({
        setupComplete: data.setup_complete ?? false,
        locked: data.locked ?? false,
        healthStatus: data.status === 'healthy' ? 'healthy' : 'degraded',
        loading: false,
      });
    } catch {
      set({
        healthStatus: 'unknown',
        loading: false,
      });
    }
  },
}));
