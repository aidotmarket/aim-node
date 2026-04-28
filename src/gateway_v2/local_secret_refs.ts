export type LocalSecretRef = `local://aim-node/secrets/${string}`;

export function localGrantSecretRef(accessGrantId: string): LocalSecretRef {
  if (!accessGrantId) {
    throw new Error("accessGrantId is required");
  }
  return `local://aim-node/secrets/grants/${accessGrantId}`;
}

export function assertLocalSecretRef(secretRef: string): asserts secretRef is LocalSecretRef {
  if (!secretRef.startsWith("local://aim-node/secrets/")) {
    throw new Error("secret_ref must point to the local aim-node secret store");
  }
}

export function assertNoRawSellerSecrets(fields: Record<string, unknown>): void {
  for (const fieldName of Object.keys(fields)) {
    const lowered = fieldName.toLowerCase();
    if (lowered.includes("raw_secret") || lowered.includes("seller_secret")) {
      throw new Error("raw seller secrets are forbidden in gateway.connect");
    }
  }
}
