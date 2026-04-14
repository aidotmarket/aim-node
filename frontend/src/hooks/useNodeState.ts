import { useState, useEffect } from 'react';

interface NodeState {
  loading: boolean;
  locked: boolean;
  setupComplete: boolean;
}

export function useNodeState(): NodeState {
  const [state, setState] = useState<NodeState>({
    loading: true,
    locked: false,
    setupComplete: false,
  });

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/mgmt/health', { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => {
        setState({
          loading: false,
          locked: data.locked ?? false,
          setupComplete: data.setup_complete ?? false,
        });
      })
      .catch(() => {
        setState({ loading: false, locked: false, setupComplete: false });
      });
    return () => controller.abort();
  }, []);

  return state;
}
