#!/usr/bin/env bash
# AIM-Node — Container entrypoint
# Ensures /data dirs exist and starts the management HTTP server.
set -e

mkdir -p /data/config /data/keystore /data/cache

exec aim-node serve \
    --data-dir /data \
    --host 0.0.0.0 \
    --port "${PORT:-8080}"
