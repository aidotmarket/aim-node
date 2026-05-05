// FUTURE-BUILD ARTIFACT
// TypeScript source. No build pipeline exists for src/gateway_v2/ as of Chunk 10.
// Compilation, packaging, and Dockerfile integration will be addressed in a follow-up BQ
// (BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE).
// Defined in specs/bq-aim-node-gateway-v2-gate2.md Chunk 10 (DIST Packaging Compatibility)
// for surface contract; build infrastructure deferred.

export type GatewayV2InstallMode = "buyer_local" | "seller_edge";

export type GatewayV2SurfaceName =
  | "discover"
  | "quote"
  | "connect"
  | "invoke"
  | "meter"
  | "receipt"
  | "publish"
  | "verify_provider"
  | "request_access"
  | "estimate_cost"
  | "create_billing_session";

export type GatewayV2ConnectorRegistryState = "not_loaded" | "ready" | "degraded";

export interface GatewayV2ConnectorRegistration {
  connectorId: string;
  mode: GatewayV2InstallMode;
  surfaces: GatewayV2SurfaceName[];
  credentialRefPrefix: "local://aim-node/secrets/";
}

export interface GatewayV2ConnectorRegistrySnapshot {
  runtime: "gateway-v2";
  state: GatewayV2ConnectorRegistryState;
  registrations: GatewayV2ConnectorRegistration[];
}

export const gatewayV2SurfaceNames: GatewayV2SurfaceName[] = [
  "discover",
  "quote",
  "connect",
  "invoke",
  "meter",
  "receipt",
  "publish",
  "verify_provider",
  "request_access",
  "estimate_cost",
  "create_billing_session",
];

export const gatewayV2InstallModes: GatewayV2InstallMode[] = ["buyer_local", "seller_edge"];

export function connectorRegistryReady(snapshot: GatewayV2ConnectorRegistrySnapshot): boolean {
  return (
    snapshot.runtime === "gateway-v2" &&
    snapshot.state === "ready" &&
    snapshot.registrations.every((registration) =>
      registration.surfaces.every((surface) => gatewayV2SurfaceNames.includes(surface)),
    ) &&
    snapshot.registrations.every((registration) => registration.credentialRefPrefix === "local://aim-node/secrets/")
  );
}
