# BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE — Gate 1 Design Spec

**Status:** Gate 1 design-only · **Priority:** P1 · **Pillar:** AIM-Node (product)
**Filed:** S561 (2026-05-05) · **Authored:** S609.W round 4 · **Branch:** spec/bq-aim-node-gateway-v2-typescript-build-pipeline-gate1
**Sibling context:** S561 cross-review of gateway packaging — AG + DS both raised HIGH finding on TS files lacking build path; documentation fold landed in that chunk; this BQ holds the structural fix.

## §0 Honest posture

Authored from Claude.ai web sandbox without filesystem access to aim-node. The exact TypeScript file inventory under `src/gateway_v2/`, the current `Dockerfile`, the existing CI workflow files in `.github/workflows/`, and any partial package.json that may already exist are NOT inspected directly. Spec built from the BQ entity body (v1, S561-authored) + AIM-Node pillar context from userMemories. Gate 2 builder running on Titan-1 must (a) inventory the TS files under `src/gateway_v2/`, (b) confirm no pre-existing `package.json` or `tsconfig.json` already in the tree, (c) read the current `Dockerfile` to identify the install-image surface, and (d) inventory current CI workflows. Sections marked [GATE-2 CONFIRMATION REQUIRED] depend on filesystem access this Worker does not have.

## §1 Problem statement

The new buyer/builder gateway packaging (shipped at AIM-Node Gateway V2 Chunks 1–N) introduced TypeScript source files for runtime components — health checks, connector registry, possibly others. The aim-node repository has NO TypeScript build pipeline. Today these files ship as `.ts` source that the runtime cannot execute (Node.js can run `.js`, not raw `.ts` without `ts-node` or a build step).

**Customer impact:**
- Install verification scripts pass file-presence checks (the `.ts` files exist) but FAIL any actual runtime exercise of those components.
- Health-check and connector-registry components are advertised as part of install profiles but effectively do not exist in the running install.
- Operator who runs the install gets a green-on-files / broken-on-runtime install state — a worst-case false-positive.

**Failure-mode signature:**
- Operator follows install instructions; install completes with no errors.
- Operator runs a connector or a health check; the runtime fails because the entry-point `.js` file does not exist (only `.ts` source ships).
- Recovery: operator manually installs `typescript` + `ts-node` AND figures out the correct entrypoint AND runs the build by hand. None of which is documented.

## §2 Scope

**In scope (Gate 1 design):**
- `package.json` under `src/gateway_v2/` (or repo root if Gate 2 confirms that's the canonical location): declares TS dependencies, build script, entry points.
- `tsconfig.json` under same path: declares target ES version, module system, output directory, source files.
- Build script: `npm run build` produces compiled `.js` artifacts in an output directory (suggested: `dist/`).
- Dockerfile integration: `Dockerfile` runs the build during image construction so compiled JavaScript ships in the install image; `.ts` source does NOT need to ship.
- CI gate: `.github/workflows/` step that fails the build if `.ts` source files exist in the repo without corresponding compiled artifacts being produced by the build pipeline (catches the regression class that filed this BQ).

**Out of scope (per BQ context):**
- Rewriting any TS components (the existing TS files are fine; they just need a build path).
- Adding new TypeScript components beyond what currently exists in `src/gateway_v2/`.
- Migrating non-TS components (Python, etc.) — unaffected by this BQ.
- Sequencing decision (ship before Chunks 11–12 vs after) — deferred to Max per BQ body's next_action; the Gate 1 design is independent of when it ships.

## §3 Build pipeline design

### §3.1 package.json (target shape)

```json
{
  "name": "aim-node-gateway-v2",
  "version": "0.1.0",
  "private": true,
  "main": "dist/index.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "clean": "rm -rf dist",
    "build:check": "tsc -p tsconfig.json --noEmit",
    "prebuild": "npm run clean"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/node": "^20.0.0"
  }
}
```

**Dependency policy:** Devdependencies only at this stage. If runtime TS components import npm packages, those move to `dependencies`. **[GATE-2 CONFIRMATION REQUIRED]** Gate 2 builder inventories actual `import` statements in the TS source and pins the runtime-dependency set.

### §3.2 tsconfig.json (target shape)

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "declaration": false,
    "sourceMap": true
  },
  "include": ["src/**/*.ts"],
  "exclude": ["node_modules", "dist", "**/*.spec.ts"]
}
```

**Module system choice:** `commonjs` because aim-node entry-points are likely invoked from Python/shell wrappers expecting Node's standard `require()` resolution. **[GATE-2 CONFIRMATION REQUIRED]** Gate 2 builder confirms entry-point invocation pattern; if ESM is required, switch to `"module": "NodeNext"` and `"type": "module"` in package.json.

**Target ES2022:** Modern enough to avoid polyfills; Node 20 (LTS) supports natively.

**Strict mode:** Defaults to enabled. If existing TS source fails strict compilation, Gate 2 builder may need to (a) fix the violations, or (b) relax `strict` to a transitional `noImplicitAny: false` setting and file a follow-up BQ to tighten.

### §3.3 Build script behavior

`npm run build`:
1. Clean prior `dist/` output (via `prebuild` hook).
2. Compile all `.ts` files in `src/` to `.js` in `dist/`.
3. Generate source maps for debugging.
4. Exit non-zero on any compilation error.

`npm run build:check`: type-check only; no emit. Used in CI for fast feedback on PRs that don't need a full build artifact.

## §4 Dockerfile integration

**Pattern (multi-stage build):**

```dockerfile
# Stage 1 — build
FROM node:20-alpine AS builder
WORKDIR /build
COPY src/gateway_v2/package*.json ./
RUN npm ci
COPY src/gateway_v2/ ./
RUN npm run build

# Stage 2 — runtime (existing aim-node image stage)
FROM <existing-aim-node-base-image>
# ... existing aim-node Dockerfile content ...
COPY --from=builder /build/dist /app/gateway_v2/dist
```

**[GATE-2 CONFIRMATION REQUIRED]** Gate 2 builder reads the current `Dockerfile`, identifies the right insertion point, and confirms whether the install image already has Node available. If not, Stage 2 needs `apk add nodejs` or equivalent.

**`.dockerignore` update:** Add `node_modules`, `dist`, `*.tsbuildinfo` to avoid copying local build state into the build context.

**Image-size impact:** Compiled JS is comparable in size to source TS. Source maps add ~30% overhead per file; consider stripping in production images (a follow-up BQ).

## §5 CI gate design

**Goal:** Prevent the regression class that filed this BQ — `.ts` source landing without a corresponding build path.

**Workflow file:** `.github/workflows/typescript-build-gate.yml` (or extend an existing workflow).

**Checks:**
1. **Build success:** Run `npm run build` from `src/gateway_v2/`; fail the workflow on any compilation error.
2. **Type-check pass:** Run `npm run build:check`; fail on any type error.
3. **Source-without-artifact detection:** Grep `git ls-files src/gateway_v2/**/*.ts` filtered against `tsconfig.json` `exclude` patterns; for each remaining `.ts` file, confirm a corresponding `.js` exists in `dist/` after `npm run build`. Any orphan `.ts` (source without artifact) fails the workflow.
4. **package.json + tsconfig.json presence check:** If any `.ts` file exists under `src/gateway_v2/` but `package.json` or `tsconfig.json` is missing, fail the workflow with a clear error pointing at this BQ as the canonical fix.

**Trigger:** PR open + push to main.

**Branch protection:** Coordinate with BQ-CI-MERGE-GATE-BRANCH-PROTECTION-S574 follow-ups so this check is required for merge to main.

## §6 Acceptance criteria (Gate 1)

1. **AC1 — package.json under src/gateway_v2/:** `package.json` declares the build script, typescript devDependency, and entry point. Designed shape per §3.1.
2. **AC2 — tsconfig.json under src/gateway_v2/:** `tsconfig.json` declares target ES2022, commonjs module, dist/ output, strict mode. Designed shape per §3.2.
3. **AC3 — npm run build produces compiled JS in dist/:** Build completes; `dist/` contains compiled `.js` artifacts for every `.ts` source file under `src/`.
4. **AC4 — Dockerfile builds compiled JS into install image:** Multi-stage Dockerfile compiles TS at image-build time; install image contains compiled `.js` in the correct path; raw `.ts` source does NOT need to ship in the install image (optional: ship for debugging via build-arg).
5. **AC5 — CI gate fails on orphan TS source:** PR that adds a `.ts` file under `src/gateway_v2/` without producing a corresponding `.js` artifact via the build fails the workflow with a clear error message naming this BQ.
6. **AC6 — CI gate fails on missing package.json or tsconfig.json:** PR that introduces `.ts` files into a directory lacking either config file fails the workflow.
7. **AC7 — Strict mode honored OR transitional relaxation documented:** If existing TS source passes strict mode, ship as-is. If not, Gate 2 builder either fixes violations or files a follow-up BQ to tighten; Gate 1 spec records the choice.
8. **AC8 — Install verification exercises runtime components:** Install-verification script (existing in aim-node) is updated to actually invoke at least one TS-component entrypoint (health check or connector-registry probe) and fail on runtime error. Catches the false-positive class this BQ filed against.

## §7 Risks

1. **R1 — Strict-mode failures.** Existing TS source may not compile under strict mode out of the box (`any`-typed values, implicit return types). *Mitigation:* AC7 allows transitional relaxation; Gate 2 builder pins the choice based on compilation evidence.
2. **R2 — Multi-stage Dockerfile bloats image.** Adding Node-builder stage adds ~150MB to image at build time. Stage 2 only copies compiled output. *Mitigation:* multi-stage ensures only `dist/` ships; build-time bloat is acceptable.
3. **R3 — TS source imports require runtime npm packages.** Gate 1 assumes devDependencies-only; reality may require runtime deps. *Mitigation:* Gate 2 builder inventories imports; if runtime deps needed, image must include `npm install --omit=dev` step in Stage 2.
4. **R4 — ESM-vs-CJS mismatch.** §3.2 picks commonjs as default; if entry-points are invoked as ESM, switch is mandatory. *Mitigation:* Gate 2 builder confirms invocation pattern before locking module system.
5. **R5 — Sequencing decision pending Max input.** BQ body's next_action says "S562: confer with Max on whether to ship the TS build pipeline before further gateway chunks land, or queue behind Chunks 11–12 first." Gate 1 design is independent of this; Gate 2 build dispatch waits for sequencing answer. *Mitigation:* this BQ's spec proceeds; Gate 2 dispatch gates on Max's sequencing call.

## §8 Open questions for Gate 2

1. **[GATE-2 CONFIRMATION REQUIRED]** What is the full inventory of `.ts` files under `src/gateway_v2/` today? Spec assumes health-check and connector-registry; Gate 2 grep produces the canonical list.
2. **[GATE-2 CONFIRMATION REQUIRED]** Does `src/gateway_v2/` already contain any partial `package.json` or `tsconfig.json` from a prior chunk? If so, Gate 2 extends; if not, Gate 2 creates from scratch.
3. **[GATE-2 CONFIRMATION REQUIRED]** What is the current `Dockerfile` structure for aim-node, and where is the right insertion point for the multi-stage builder?
4. **[GATE-2 CONFIRMATION REQUIRED]** Does the install image already have Node available, or does Stage 2 need `apk add nodejs`?
5. **[GATE-2 CONFIRMATION REQUIRED]** What is the existing install-verification script? AC8 updates it; Gate 2 needs to know the entry point.
6. ESM vs CJS: how are TS entry-points invoked in aim-node? `require('gateway_v2/health-check')` (CJS) or `import` from another TS module (ESM)? Pin the module system based on this answer.
7. Branch-protection coordination: is BQ-CI-MERGE-GATE-BRANCH-PROTECTION-S574 follow-ups landing before or after this BQ ships? Affects whether the CI gate is advisory or required at ship time.

## §9 Compat & migration

**Existing TS files:** No rewrite needed; they're fine as-is. Gate 2 just adds the build path around them.

**Operators with cached install images:** Operators running pre-fix images continue running with un-runnable TS source. Fix lands in the next aim-node release; operators on older releases hit the same false-positive until they upgrade. Gate 2 ship-day announcement should call this out.

**Sequencing with gateway chunks 11–12:** Per BQ body next_action, Max decides whether this ships before or after Chunks 11–12. If after, Chunks 11–12 may add MORE `.ts` files — same un-runnable state. Risk: 11–12 compound the false-positive. Recommendation if Max asks: ship this BQ first if Chunks 11–12 are TS-touching; ship after if they're not.

**v1 of installed gateway:** Existing installs running v0.0.1 stable (per userMemories) are NOT affected — v0.0.1 predates the TS components. Only Gateway V2 installs hit the false-positive.
