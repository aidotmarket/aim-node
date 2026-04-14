import { Eye, EyeOff } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Input } from '@/components/ui';
import { useSetupWizard } from '@/hooks/useSetupWizard';

function validatePassphrase(passphrase: string) {
  return {
    minLength: passphrase.length >= 12,
    uppercase: /[A-Z]/.test(passphrase),
    number: /\d/.test(passphrase),
  };
}

function getStrengthColor(passphrase: string) {
  if (!passphrase) return 'bg-[#E8E8E8]';

  const checks = validatePassphrase(passphrase);
  const satisfiedChecks = Object.values(checks).filter(Boolean).length;

  if (satisfiedChecks === 3) return 'bg-brand-success';
  if (satisfiedChecks === 2) return 'bg-brand-warning';
  return 'bg-brand-error';
}

export function WelcomeStep() {
  const navigate = useNavigate();
  const { passphrase, setPassphrase, markComplete, next } = useSetupWizard();
  const [confirmPassphrase, setConfirmPassphrase] = useState('');
  const [showPassphrase, setShowPassphrase] = useState(false);
  const [showConfirmPassphrase, setShowConfirmPassphrase] = useState(false);

  const checks = useMemo(() => validatePassphrase(passphrase), [passphrase]);
  const isValid = checks.minLength && checks.uppercase && checks.number;
  const matches = passphrase.length > 0 && passphrase === confirmPassphrase;
  const canContinue = isValid && matches;
  const strengthColor = getStrengthColor(passphrase);

  const handleContinue = () => {
    if (!canContinue) return;
    markComplete(0);
    next();
    navigate('/setup/keypair');
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-brand-text">Welcome to AIM Node</h2>
        <p className="text-sm text-brand-text-secondary">
          Create a passphrase to protect your node identity during setup. This passphrase stays in
          memory only until keypair generation succeeds.
        </p>
      </div>

      <div className="space-y-5">
        <div className="space-y-2">
          <div className="relative">
            <Input
              label="Create Passphrase"
              type={showPassphrase ? 'text' : 'password'}
              value={passphrase}
              onChange={(event) => setPassphrase(event.target.value)}
              placeholder="Enter a secure passphrase"
              className="pr-20"
            />
            <button
              type="button"
              onClick={() => setShowPassphrase((value) => !value)}
              className="absolute right-3 top-[34px] inline-flex items-center gap-1 text-xs font-medium text-brand-text-secondary"
              aria-label={showPassphrase ? 'Hide passphrase' : 'Show passphrase'}
            >
              {showPassphrase ? <EyeOff size={14} /> : <Eye size={14} />}
              {showPassphrase ? 'Hide' : 'Show'}
            </button>
          </div>
          <div className="space-y-2">
            <div
              data-testid="passphrase-strength-bar"
              className="h-2 w-full rounded-full bg-[#E8E8E8]"
            >
              <div
                data-testid="passphrase-strength-fill"
                className={`h-2 rounded-full transition-colors ${strengthColor}`}
                style={{ width: passphrase ? '100%' : '0%' }}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant={checks.minLength ? 'success' : 'neutral'}>12+ characters</Badge>
              <Badge variant={checks.uppercase ? 'success' : 'neutral'}>Uppercase letter</Badge>
              <Badge variant={checks.number ? 'success' : 'neutral'}>Number</Badge>
            </div>
          </div>
        </div>

        <div className="relative">
          <Input
            label="Confirm Passphrase"
            type={showConfirmPassphrase ? 'text' : 'password'}
            value={confirmPassphrase}
            onChange={(event) => setConfirmPassphrase(event.target.value)}
            placeholder="Re-enter your passphrase"
            error={
              confirmPassphrase.length > 0 && !matches ? 'Passphrases do not match' : undefined
            }
            className="pr-20"
          />
          <button
            type="button"
            onClick={() => setShowConfirmPassphrase((value) => !value)}
            className="absolute right-3 top-[34px] inline-flex items-center gap-1 text-xs font-medium text-brand-text-secondary"
            aria-label={showConfirmPassphrase ? 'Hide confirm passphrase' : 'Show confirm passphrase'}
          >
            {showConfirmPassphrase ? <EyeOff size={14} /> : <Eye size={14} />}
            {showConfirmPassphrase ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>

      <div className="flex justify-end">
        <Button variant="primary" onClick={handleContinue} disabled={!canContinue}>
          Continue
        </Button>
      </div>
    </div>
  );
}

export { getStrengthColor, validatePassphrase };
