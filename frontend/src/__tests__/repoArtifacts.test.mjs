// @vitest-environment node

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, it } from 'vitest';

const testFileDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(testFileDir, '../..');
const repoRoot = path.resolve(frontendDir, '..');
const dockerfilePath = path.join(repoRoot, 'Dockerfile');
const dockerignorePath = path.join(repoRoot, '.dockerignore');
const docsPath = path.join(repoRoot, 'docs', 'DEVELOPMENT.md');
const distDir = path.join(frontendDir, 'dist');

describe('repo artifacts', () => {
  beforeAll(() => {
    rmSync(distDir, { recursive: true, force: true });
    execFileSync('npm', ['run', 'build'], {
      cwd: frontendDir,
      stdio: 'pipe',
      env: process.env,
    });
  }, 120_000);

  it('defines a frontend build stage with the expected base image', () => {
    const dockerfile = readFileSync(dockerfilePath, 'utf8');
    const frontendStage = dockerfile.indexOf('FROM node:20-alpine AS frontend-build');
    const runtimeStage = dockerfile.indexOf('FROM python:3.11-slim-bookworm AS runtime');

    expect(frontendStage).toBeGreaterThanOrEqual(0);
    expect(runtimeStage).toBeGreaterThan(frontendStage);
  });

  it('copies built frontend assets into /data/frontend/dist and fixes ownership', () => {
    const dockerfile = readFileSync(dockerfilePath, 'utf8');

    expect(dockerfile).toContain('COPY --from=frontend-build /app/frontend/dist /data/frontend/dist');
    expect(dockerfile).toContain('RUN chown -R aimnode:aimnode /data/frontend');
  });

  it('ignores frontend build artifacts and dependencies in docker builds', () => {
    const dockerignore = readFileSync(dockerignorePath, 'utf8');

    expect(dockerignore).toContain('frontend/node_modules');
    expect(dockerignore).toContain('frontend/.vite');
    expect(dockerignore).toContain('frontend/dist');
  });

  it('documents frontend development, docker assets, and testing flows', () => {
    const docs = readFileSync(docsPath, 'utf8');

    expect(docs).toContain('Python 3.11+');
    expect(docs).toContain('Node 20 LTS');
    expect(docs).toContain('npm run dev');
    expect(docs).toContain('http://localhost:8080');
    expect(docs).toContain('frontend/dist');
    expect(docs).toContain('/data/frontend/dist');
    expect(docs).toContain('brand-indigo');
    expect(docs).toContain('brand-teal');
    expect(docs).toContain('brand-surface');
    expect(docs).toContain('@/components/ui');
    expect(docs).toContain('variant');
    expect(docs).toContain('size');
    expect(docs).toContain('npm test');
    expect(docs).toContain('python3 -m pytest');
  });

  it('produces the expected frontend build output structure', () => {
    expect(existsSync(path.join(distDir, 'index.html'))).toBe(true);
    expect(existsSync(path.join(distDir, 'assets'))).toBe(true);
  });
});
