export type GatewayV2HealthCheckName =
  | "backend_reachability"
  | "auth_bootstrap_state"
  | "connector_registry_readiness"
  | "meter_buffer_status"
  | "update_channel"
  | "local_secret_store_availability";

export type GatewayV2HealthState = "pass" | "warn" | "fail";

export interface GatewayV2HealthCheck {
  name: GatewayV2HealthCheckName;
  requiredForModes: Array<"buyer_local" | "seller_edge">;
  failureImpact: string;
}

export interface GatewayV2HealthSignal {
  name: GatewayV2HealthCheckName;
  state: GatewayV2HealthState;
  detail?: string;
}

export interface GatewayV2HealthReport {
  runtime: "gateway-v2";
  mode: "buyer_local" | "seller_edge";
  state: GatewayV2HealthState;
  checks: GatewayV2HealthSignal[];
}

export const gatewayV2HealthChecks: GatewayV2HealthCheck[] = [
  {
    name: "backend_reachability",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 cannot resolve canonical discover, quote, meter, receipt, billing, or trust state.",
  },
  {
    name: "auth_bootstrap_state",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 cannot establish the local principal and signed request envelope.",
  },
  {
    name: "connector_registry_readiness",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 cannot route connector ids to local or seller edge runtime handlers.",
  },
  {
    name: "meter_buffer_status",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 must fail closed when local metering cannot drain within policy.",
  },
  {
    name: "update_channel",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 cannot verify that the installed runtime follows the pinned update path.",
  },
  {
    name: "local_secret_store_availability",
    requiredForModes: ["buyer_local", "seller_edge"],
    failureImpact: "Gateway-V2 cannot use runtime credentials because credentials must remain local.",
  },
];

export function evaluateGatewayV2Health(
  mode: "buyer_local" | "seller_edge",
  checks: GatewayV2HealthSignal[],
): GatewayV2HealthReport {
  const states = checks.map((check) => check.state);
  const state: GatewayV2HealthState = states.includes("fail") ? "fail" : states.includes("warn") ? "warn" : "pass";
  return {
    runtime: "gateway-v2",
    mode,
    state,
    checks,
  };
}
