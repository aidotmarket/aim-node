import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api } from '@/lib/api';
import { Button, Input } from '@/components/ui';

interface UnlockResponse {
  unlocked: boolean;
}

export function UnlockPage() {
  const navigate = useNavigate();
  const [passphrase, setPassphrase] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!passphrase.trim()) {
      setError('Enter your passphrase to unlock the node.');
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      const response = await api.post<UnlockResponse>('/unlock', {
        passphrase,
      });

      if (response.unlocked) {
        navigate('/dashboard');
        return;
      }

      setError('Unlock failed. Try again.');
    } catch (caughtError) {
      setError(caughtError instanceof ApiError ? caughtError.message : 'Failed to unlock node');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Unlock your node</h2>
        <p className="text-sm text-brand-text-secondary">
          Enter the passphrase for this installation to resume using the node.
        </p>
      </div>

      <form className="space-y-5" onSubmit={handleSubmit}>
        <Input
          label="Passphrase"
          type="password"
          value={passphrase}
          onChange={(event) => {
            setPassphrase(event.target.value);
            setError(null);
          }}
          placeholder="Enter your passphrase"
          autoComplete="current-password"
        />

        {error && (
          <p role="alert" className="text-sm text-brand-error">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <Button
            type="submit"
            variant="primary"
            className="bg-[#3F51B5]"
            loading={isSubmitting}
            disabled={!passphrase.trim()}
          >
            Unlock
          </Button>
        </div>
      </form>
    </div>
  );
}
