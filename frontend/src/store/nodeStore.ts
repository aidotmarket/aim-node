import { create } from 'zustand';
import { api } from '@/lib/api';

interface HealthResponse {
  healthy: boolean;
  locked: boolean;
  setup_complete: boolean;
  csrf_token?: string | null;
}

export interface NodeState {
  setupComplete: boolean;
  locked: boolean;
  healthStatus: 'healthy' | 'degraded' | 'unknown';
  csrfToken: string | null;
  loading: boolean;
  bootstrap: () => Promise<void>;
}

const initialState = {
  setupComplete: false,
  locked: false,
  healthStatus: 'unknown' as const,
  csrfToken: null,
  loading: true,
};

export const useNodeStore = create<NodeState>((set) => ({
  ...initialState,

  bootstrap: async () => {
    set({ loading: true });
    try {
      const health = await api.get<HealthResponse>('/health');
      set({
        setupComplete: health.setup_complete,
        locked: health.locked,
        healthStatus: health.healthy ? 'healthy' : 'degraded',
        csrfToken: health.csrf_token ?? null,
        loading: false,
      });
    } catch {
      set({
        setupComplete: false,
        locked: false,
        healthStatus: 'unknown',
        csrfToken: null,
        loading: false,
      });
    }
  },
}));
