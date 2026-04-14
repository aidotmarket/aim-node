import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '@/lib/api';
import { Badge, Button, Card } from '@/components/ui';
import { useSetupWizard } from '@/hooks/useSetupWizard';

interface FinalizeResponse {
  ok: boolean;
}

export function ReviewStep() {
  const navigate = useNavigate();
  const {
    fingerprint,
    apiUrl,
    apiKey,
    connectionReachable,
    connectionVersion,
    upstreamUrl,
    toolsFound,
    upstreamReachable,
    upstreamSkipped,
    mode,
    setMode,
  } = useSetupWizard();
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFinalize = async () => {
    if ((mode === 'provider' || mode === 'both') && !upstreamUrl.trim()) {
      setError('An upstream URL is required for provider and both modes.');
      return;
    }

    setError(null);
    setIsFinalizing(true);

    try {
      const response = await api.post<FinalizeResponse>('/setup/finalize', {
        mode,
        api_url: apiUrl,
        api_key: apiKey,
        upstream_url:
          upstreamUrl.trim() &&
          (!upstreamSkipped || mode === 'provider' || mode === 'both')
            ? upstreamUrl.trim()
            : undefined,
      });

      if (response.ok) {
        navigate('/dashboard');
      } else {
        setError('Finalize failed.');
      }
    } catch (caughtError) {
      setError(caughtError instanceof ApiError ? caughtError.message : 'Failed to finalize setup');
    } finally {
      setIsFinalizing(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Review & Finalize</h2>
        <p className="text-sm text-brand-text-secondary">
          Confirm the collected setup details, choose the node mode, and write the final
          configuration.
        </p>
      </div>

      <Card className="space-y-5" padding="md">
        <div className="flex items-start justify-between gap-3 border-b border-gray-200 pb-4">
          <div className="space-y-1">
            <p className="text-sm font-medium text-brand-text">Node identity</p>
            <p className="font-mono text-sm text-brand-text">{fingerprint || 'Not generated yet'}</p>
          </div>
          <Link
            className="text-sm font-medium text-brand-indigo"
            to="/setup/keypair"
            aria-label="Edit node identity"
          >
            Edit
          </Link>
        </div>

        <div className="flex items-start justify-between gap-3 border-b border-gray-200 pb-4">
          <div className="space-y-2">
            <p className="text-sm font-medium text-brand-text">ai.market connection</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={connectionReachable ? 'success' : 'error'}>
                {connectionReachable ? 'Reachable' : 'Unreachable'}
              </Badge>
              {connectionVersion && <Badge variant="info">Version {connectionVersion}</Badge>}
            </div>
            <p className="text-sm text-brand-text-secondary">{apiUrl}</p>
          </div>
          <Link
            className="text-sm font-medium text-brand-indigo"
            to="/setup/connection"
            aria-label="Edit ai.market connection"
          >
            Edit
          </Link>
        </div>

        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <p className="text-sm font-medium text-brand-text">Upstream endpoint</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={upstreamReachable ? 'success' : 'warning'}>
                {upstreamReachable ? 'Reachable' : 'Not confirmed'}
              </Badge>
              <Badge variant="info">{toolsFound} tools found</Badge>
            </div>
            <p className="text-sm text-brand-text-secondary">
              {upstreamUrl || 'No upstream configured'}
            </p>
          </div>
          <Link
            className="text-sm font-medium text-brand-indigo"
            to="/setup/upstream"
            aria-label="Edit upstream endpoint"
          >
            Edit
          </Link>
        </div>
      </Card>

      <Card className="space-y-4" padding="md">
        <div className="space-y-1">
          <p className="text-sm font-medium text-brand-text">Node mode</p>
          <p className="text-sm text-brand-text-secondary">
            Choose how this node should participate after setup completes.
          </p>
        </div>

        <div role="radiogroup" aria-label="Node mode" className="space-y-3">
          {[
            { value: 'provider', label: 'Provider' },
            { value: 'consumer', label: 'Consumer' },
            { value: 'both', label: 'Both' },
          ].map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-center gap-3 rounded-brand border border-gray-200 p-4 text-sm text-brand-text"
            >
              <input
                type="radio"
                name="mode"
                value={option.value}
                checked={mode === option.value}
                onChange={() => setMode(option.value as 'provider' | 'consumer' | 'both')}
                className="h-4 w-4 accent-indigo-600"
              />
              {option.label}
            </label>
          ))}
        </div>
      </Card>

      {error && (
        <p role="alert" className="text-sm text-brand-error">
          {error}
        </p>
      )}

      <div className="flex justify-end">
        <Button variant="primary" className="bg-indigo-600 hover:bg-indigo-600/90" onClick={handleFinalize} loading={isFinalizing}>
          Finalize Setup
        </Button>
      </div>
    </div>
  );
}
