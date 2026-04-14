import { useNodeStore } from '@/store/nodeStore';

type NodeStateSnapshot = Pick<
  ReturnType<typeof useNodeStore.getState>,
  'loading' | 'locked' | 'setupComplete'
>;

export function useNodeState(): NodeStateSnapshot {
  const loading = useNodeStore((state) => state.loading);
  const locked = useNodeStore((state) => state.locked);
  const setupComplete = useNodeStore((state) => state.setupComplete);

  return {
    loading,
    locked,
    setupComplete,
  };
}
