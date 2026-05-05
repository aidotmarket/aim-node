# Gateway V2 TypeScript Build Status

## TypeScript files in dist-related paths

- `src/gateway_v2/buyer.ts`
- `src/gateway_v2/client_contracts.ts`
- `src/gateway_v2/connect.ts`
- `src/gateway_v2/connector_registry.ts`
- `src/gateway_v2/connectors/runtime.ts`
- `src/gateway_v2/discover.ts`
- `src/gateway_v2/health.ts`
- `src/gateway_v2/invoke.ts`
- `src/gateway_v2/local_secret_refs.ts`
- `src/gateway_v2/meter.ts`
- `src/gateway_v2/meter_buffer.ts`
- `src/gateway_v2/publish.ts`
- `src/gateway_v2/quote.ts`
- `src/gateway_v2/receipt.ts`

## Current build status

No TypeScript build pipeline exists for `src/gateway_v2/` as of Chunk 10. These files define the Gateway V2 surface contract for DIST packaging compatibility, but they are not compiled, packaged, or integrated into the Dockerfile.

Build infrastructure is deferred to `BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE`.

## Runtime warning

Install profiles reference health.ts and connector_registry.ts. These files are NOT built as of Chunk 10 and the runtime will not execute them until the build pipeline lands.
