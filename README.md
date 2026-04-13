# AIM Node

**Peer-to-peer model and pipeline serving for the [ai.market](https://ai.market) network.**

[![License: ELv2](https://img.shields.io/badge/License-ELv2-3F51B5.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3F51B5.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-3F51B5.svg)](https://www.docker.com/)
[![ai.market](https://img.shields.io/badge/ai.market-network-0F6E56.svg)](https://ai.market)

---

AIM Node is a lightweight container that connects your compute to the ai.market peer-to-peer network. It can operate as a **provider** (serving models and pipelines to buyers) or a **consumer** (accessing remote models via a local API).

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
mkdir ~/aim-node && cd ~/aim-node
curl -fsSL https://get.ai.market/aim-node/docker-compose.yml -o docker-compose.yml
docker compose up -d
```

## Auth Chain

### UI -> Node (Management Plane)

The UI exclusively talks to the aim-node management API (`/api/mgmt/*`). It never calls
ai-market-backend directly.

**CSRF protection** (loopback access):
- Fetch `GET /api/mgmt/health` and read the `X-CSRF-Token` response header
- Include `X-CSRF-Token: <token>` on all `POST`, `PUT`, and `DELETE` requests
- Alternatively, requests from `Origin: http://localhost:*` are accepted without the CSRF header

**Remote access** (`--host 0.0.0.0`):
- A session token is issued on first request from localhost
- The token is returned in the response body (`session_token`) and via `Set-Cookie: aim_session`
- Subsequent requests from any origin must include `X-Session-Token` or the `aim_session` cookie

### Node -> Backend (Marketplace Plane)

aim-node authenticates to ai-market-backend with a two-step flow:

1. **API Key Exchange:** `POST /auth/token` with `X-API-Key: {key}` returns `access_token` and `refresh_token`
2. **Bearer Token:** all subsequent calls use `Authorization: Bearer {access_token}`
3. **Refresh:** on `401`, the node calls `POST /auth/refresh` with `Authorization: Bearer {refresh_token}`
4. **Token storage:** `{data_dir}/auth_token.json` and never exposed to the UI or browser

The UI never sees the API key, bearer token, or private key. The node facade injects
auth headers transparently.

### Auth per Endpoint Family

| Endpoint Family | Method | Notes |
|----------------|--------|-------|
| `/auth/token` | X-API-Key | Initial exchange only |
| `/auth/refresh` | Bearer (refresh token) | On access token expiry |
| `/aim/nodes/register/*` | X-API-Key + Ed25519 signature | Challenge-response |
| `/aim/nodes/{id}/tools/*` | Bearer | `node_id` claim required |
| `/aim/sessions/*` | Bearer | `node_id` + `session_id` |
| `/aim/metering/events` | Bearer + Ed25519 signed payload | Integrity guarantee |
| `/aim/payouts/*`, `/aim/settlements/*` | Bearer | `seller_id` claim |
| `/aim/discover/*` | Bearer (buyer) or public | Search is unauthenticated |
| `/aim/nodes/{id}/trust*` | Bearer | |
| `/aim/observability/*` | Bearer | |
| `/allie/chat/agentic` | Bearer (via API key) | allAI proxy |

## Management API

Once running, the management API is available at `http://localhost:8080/api/mgmt/health`.

## Documentation

Full documentation is available at [ai.market/docs](https://ai.market).

## License

This project is licensed under the [Elastic License 2.0 (ELv2)](LICENSE).
