import { Eye, EyeOff } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api } from '@/lib/api';
import { Badge, Button, Card, Input } from '@/components/ui';
import { useSetupWizard } from '@/hooks/useSetupWizard';

interface TestConnectionResponse {
  reachable: boolean;
  version: string | null;
}

export function ConnectionStep() {
  const navigate = useNavigate();
  const {
    apiUrl,
    apiKey,
    connectionReachable,
    connectionVersion,
    setConnection,
    markComplete,
    next,
    back,
  } = useSetupWizard();
  const [showApiKey, setShowApiKey] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canContinue = connectionReachable === true && apiUrl.trim().length > 0 && apiKey.trim().length > 0;

  const handleApiUrlChange = (value: string) => {
    setConnection({ apiUrl: value, reachable: null, version: null });
    setError(null);
  };

  const handleApiKeyChange = (value: string) => {
    setConnection({ apiKey: value, reachable: null, version: null });
    setError(null);
  };

  const handleTestConnection = async () => {
    setError(null);
    setIsTesting(true);

    try {
      const response = await api.post<TestConnectionResponse>('/setup/test-connection', {
        api_url: apiUrl,
        api_key: apiKey,
      });

      setConnection({
        apiUrl,
        apiKey,
        reachable: response.reachable,
        version: response.version,
      });

      if (response.reachable) {
        markComplete(2);
      }
    } catch (caughtError) {
      setConnection({ reachable: false, version: null });
      setError(caughtError instanceof ApiError ? caughtError.message : 'Failed to test connection');
    } finally {
      setIsTesting(false);
    }
  };

  const handleBack = () => {
    back();
    navigate('/setup/keypair');
  };

  const handleContinue = () => {
    if (!canContinue) return;
    next();
    navigate('/setup/upstream');
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Connect to ai.market</h2>
        <p className="text-sm text-brand-text-secondary">
          Test the management API connection before continuing to upstream configuration.
        </p>
      </div>

      <div className="space-y-5">
        <Input
          label="API URL"
          value={apiUrl}
          onChange={(event) => handleApiUrlChange(event.target.value)}
          placeholder="https://api.ai.market"
        />

        <div className="relative">
          <Input
            label="API Key"
            type={showApiKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(event) => handleApiKeyChange(event.target.value)}
            placeholder="Enter your ai.market API key"
            className="pr-20"
          />
          <button
            type="button"
            onClick={() => setShowApiKey((value) => !value)}
            className="absolute right-3 top-[34px] inline-flex items-center gap-1 text-xs font-medium text-brand-text-secondary"
            aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
          >
            {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
            {showApiKey ? 'Hide' : 'Show'}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            onClick={handleTestConnection}
            loading={isTesting}
            disabled={!apiUrl.trim() || !apiKey.trim()}
          >
            Test Connection
          </Button>
          {connectionReachable !== null && (
            <Badge variant={connectionReachable ? 'success' : 'error'}>
              {connectionReachable ? 'Reachable' : 'Unreachable'}
            </Badge>
          )}
          {connectionVersion && <Badge variant="info">Version {connectionVersion}</Badge>}
        </div>

        {(connectionReachable !== null || error) && (
          <Card padding="sm" className="bg-brand-surface">
            <div className="flex flex-col gap-2 text-sm">
              <p className="text-brand-text">
                Connection status:{' '}
                <span className={connectionReachable ? 'text-brand-success' : 'text-brand-error'}>
                  {connectionReachable ? 'Reachable' : 'Unreachable'}
                </span>
              </p>
              {connectionVersion && (
                <p className="text-brand-text-secondary">Platform version: {connectionVersion}</p>
              )}
              {error && (
                <p role="alert" className="text-brand-error">
                  {error}
                </p>
              )}
            </div>
          </Card>
        )}
      </div>

      <div className="flex justify-between gap-3">
        <Button variant="ghost" onClick={handleBack}>
          Back
        </Button>
        <Button variant="primary" onClick={handleContinue} disabled={!canContinue}>
          Continue
        </Button>
      </div>
    </div>
  );
}
