import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api } from '@/lib/api';
import { Badge, Button, Card, Input } from '@/components/ui';
import { useSetupWizard } from '@/hooks/useSetupWizard';

interface TestUpstreamResponse {
  reachable: boolean;
  latency_ms: number | null;
  tools_found: number;
  error: string | null;
}

export function UpstreamStep() {
  const navigate = useNavigate();
  const {
    upstreamUrl,
    upstreamReachable,
    toolsFound,
    upstreamError,
    upstreamSkipped,
    setUpstream,
    markComplete,
    next,
    back,
  } = useSetupWizard();
  const [isTesting, setIsTesting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const canContinue = upstreamReachable === true || upstreamSkipped;
  const failureMessage = localError ?? upstreamError;

  const handleUrlChange = (value: string) => {
    setUpstream({
      url: value,
      reachable: null,
      toolsFound: 0,
      error: null,
      skipped: false,
    });
    setLocalError(null);
  };

  const handleTestUpstream = async () => {
    setLocalError(null);
    setIsTesting(true);

    try {
      const response = await api.post<TestUpstreamResponse>('/setup/test-upstream', {
        url: upstreamUrl,
      });

      setUpstream({
        url: upstreamUrl,
        reachable: response.reachable,
        toolsFound: response.tools_found,
        error: response.error,
        skipped: false,
      });

      if (response.reachable) {
        markComplete(3);
      }
    } catch (caughtError) {
      const message =
        caughtError instanceof ApiError ? caughtError.message : 'Failed to test upstream';
      setUpstream({
        url: upstreamUrl,
        reachable: false,
        toolsFound: 0,
        error: message,
        skipped: false,
      });
      setLocalError(message);
    } finally {
      setIsTesting(false);
    }
  };

  const handleSkip = () => {
    setUpstream({
      url: upstreamUrl,
      reachable: false,
      toolsFound: 0,
      error: 'You can configure this later in Settings',
      skipped: true,
    });
    markComplete(3);
    next();
    navigate('/setup/review');
  };

  const handleBack = () => {
    back();
    navigate('/setup/connection');
  };

  const handleContinue = () => {
    if (!canContinue) return;
    next();
    navigate('/setup/review');
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Configure upstream endpoint</h2>
        <p className="text-sm text-brand-text-secondary">
          Your MCP upstream is the remote endpoint AIM Node queries for available tools and
          capabilities when operating in provider mode.
        </p>
      </div>

      <div className="space-y-5">
        <Input
          label="MCP Endpoint URL"
          value={upstreamUrl}
          onChange={(event) => handleUrlChange(event.target.value)}
          placeholder="https://upstream.example.com/mcp"
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            onClick={handleTestUpstream}
            loading={isTesting}
            disabled={!upstreamUrl.trim()}
          >
            Test Upstream
          </Button>
          {upstreamReachable !== null && (
            <Badge variant={upstreamReachable ? 'success' : 'error'}>
              {upstreamReachable ? 'Reachable' : 'Unreachable'}
            </Badge>
          )}
          {upstreamReachable === true && <Badge variant="info">{toolsFound} tools found</Badge>}
        </div>

        {(upstreamReachable !== null || failureMessage || upstreamSkipped) && (
          <Card padding="sm" className="bg-brand-surface">
            <div className="space-y-2 text-sm">
              {upstreamReachable !== null && (
                <p className="text-brand-text">
                  Upstream status:{' '}
                  <span className={upstreamReachable ? 'text-brand-success' : 'text-brand-error'}>
                    {upstreamReachable ? 'Reachable' : 'Unreachable'}
                  </span>
                </p>
              )}
              {upstreamReachable === true && (
                <p className="text-brand-text-secondary">Discovered tools: {toolsFound}</p>
              )}
              {failureMessage && (
                <p role="alert" className="text-brand-error">
                  {failureMessage}
                </p>
              )}
              {(failureMessage || upstreamSkipped) && (
                <p className="text-brand-text-secondary">
                  You can configure this later in Settings
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
        <div className="flex gap-3">
          {(failureMessage || upstreamSkipped) && (
            <Button variant="ghost" onClick={handleSkip}>
              Skip for now
            </Button>
          )}
          <Button variant="primary" onClick={handleContinue} disabled={!canContinue}>
            Continue
          </Button>
        </div>
      </div>
    </div>
  );
}
