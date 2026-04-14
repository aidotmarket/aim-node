# =============================================================================
# AIM-Node — Production Dockerfile
# =============================================================================
# Peer-to-peer model and pipeline serving for the ai.market network.
#
# - Multi-stage build (builder + runtime)
# - Non-root user (aimnode:1001)
# - Pinned base image
# - No dev dependencies in final image
# =============================================================================

# ---- Stage 1: Frontend build ----
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Builder ----
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy package sources needed for install
COPY pyproject.toml README.md ./
COPY aim_node/ ./aim_node/

# Install the package (and its runtime deps) into /install prefix
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install ".[management]"


# ---- Stage 3: Runtime ----
FROM python:3.11-slim-bookworm AS runtime

LABEL maintainer="ai.market <ops@ai.market>"
LABEL description="AIM-Node — Peer-to-peer model and pipeline serving for ai.market"

WORKDIR /app

# Minimal runtime deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local
COPY --from=frontend-build /app/frontend/dist /data/frontend/dist

# Create non-root user
RUN groupadd -g 1001 aimnode \
    && useradd -u 1001 -g aimnode -m -s /bin/bash aimnode

# Create data directories
RUN mkdir -p /data/config /data/keystore /data/cache \
    && chown -R aimnode:aimnode /data
RUN chown -R aimnode:aimnode /data/frontend

# Copy application source (kept alongside the installed package for transparency)
COPY --chown=aimnode:aimnode aim_node/ ./aim_node/

# Copy entrypoint
COPY --chown=root:root entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN chown -R aimnode:aimnode /app

USER aimnode

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8080}/api/mgmt/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
