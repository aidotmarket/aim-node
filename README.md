# AIM-Node

AIM-Node — Peer-to-peer model and pipeline serving for the ai.market network.
Provider and consumer modes for peer-to-peer model/pipeline access.

## Quick Install

### Mac & Linux

```bash
curl -fsSL https://get.ai.market/aim-node | bash
```

### Windows

```powershell
irm https://get.ai.market/aim-node/windows | iex
```

## Manual Install

```bash
docker pull ghcr.io/aidotmarket/aim-node:latest

# Grab the compose file
curl -fsSL https://raw.githubusercontent.com/aidotmarket/aim-node/main/docker-compose.aim-node.yml \
  -o docker-compose.aim-node.yml

docker compose -f docker-compose.aim-node.yml up -d
```

The management API will be available at `http://localhost:8080/api/mgmt/health`.

## Configuration

Environment variables (set in `.env` or via shell):

| Variable          | Default                  | Description                          |
|-------------------|--------------------------|--------------------------------------|
| `AIM_NODE_VERSION`| `latest`                 | Image tag to pull                    |
| `AIM_NODE_PORT`   | `8080`                   | Host port to bind                    |
| `AIM_API_URL`     | `https://api.ai.market`  | AIM control-plane URL                |
| `AIM_NODE_NAME`   | `my-node`                | Human-readable node name             |

Persistent data lives in named Docker volumes:
`aim-node-config`, `aim-node-keystore`, `aim-node-cache`.

## Releasing

Maintainers ship releases via `scripts/release.sh`:

```bash
./scripts/release.sh rc patch       # cut a release candidate
./scripts/release.sh promote        # promote latest RC to stable
```

Tag pushes (`v*`) trigger `.github/workflows/docker-build.yml`,
which builds multi-arch images (amd64 + arm64) and publishes to
`ghcr.io/aidotmarket/aim-node`.
