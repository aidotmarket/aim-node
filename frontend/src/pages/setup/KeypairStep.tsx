import { ApiError, api } from '@/lib/api';
import { Check, Copy, KeyRound } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button } from '@/components/ui';
import { useSetupWizard } from '@/hooks/useSetupWizard';

interface KeypairResponse {
  fingerprint: string;
  created: boolean;
}

export function KeypairStep() {
  const navigate = useNavigate();
  const { passphrase, clearPassphrase, markComplete, next, back } = useSetupWizard();
  const [result, setResult] = useState<KeypairResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasExistingKeypair, setHasExistingKeypair] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const canContinue = result !== null || hasExistingKeypair;

  const handleGenerate = async () => {
    setError(null);
    setHasExistingKeypair(false);
    setIsGenerating(true);

    try {
      const payload = passphrase ? { passphrase } : undefined;
      const response = await api.post<KeypairResponse>('/setup/keypair', payload);
      setResult(response);
      clearPassphrase();
      markComplete(1);
    } catch (caughtError) {
      if (caughtError instanceof ApiError && caughtError.status === 409) {
        setHasExistingKeypair(true);
        setError('A node identity already exists for this installation.');
      } else {
        setError(caughtError instanceof Error ? caughtError.message : 'Failed to generate keypair');
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopy = async () => {
    if (!result?.fingerprint || !navigator.clipboard) return;
    await navigator.clipboard.writeText(result.fingerprint);
    setIsCopied(true);
  };

  const handleBack = () => {
    back();
    navigate('/setup/welcome');
  };

  const handleContinue = () => {
    if (!canContinue) return;
    next();
    navigate('/setup/connection');
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Generate your node identity</h2>
        <p className="text-sm text-brand-text-secondary">
          Create the encrypted keypair that identifies this AIM Node when it connects to the
          network.
        </p>
      </div>

      <div className="rounded-brand border border-[#E8E8E8] bg-brand-surface p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-full bg-indigo-50 p-2 text-brand-indigo">
            <KeyRound size={18} />
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium text-brand-text">Node fingerprint</p>
            <p className="text-sm text-brand-text-secondary">
              The fingerprint is safe to display and helps you confirm which node identity is
              active.
            </p>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={handleGenerate} loading={isGenerating}>
            Generate Keypair
          </Button>
          {result && (
            <Badge variant={result.created ? 'success' : 'warning'}>
              {result.created ? 'Created' : 'Reused existing'}
            </Badge>
          )}
          {hasExistingKeypair && <Badge variant="warning">Already exists</Badge>}
        </div>

        {error && (
          <p className="mt-4 text-sm text-brand-error" role="alert">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-5 rounded-brand border border-[#E8E8E8] bg-white p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-brand-text-secondary">
                  Fingerprint
                </p>
                <p className="font-mono text-sm text-brand-text">{result.fingerprint}</p>
              </div>
              <Button variant="secondary" onClick={handleCopy}>
                {isCopied ? <Check size={16} /> : <Copy size={16} />}
                {isCopied ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </div>
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
