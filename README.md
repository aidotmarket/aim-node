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

## Management API

Once running, the management API is available at `http://localhost:8080/api/mgmt/health`.

## Documentation

Full documentation is available at [ai.market/docs](https://ai.market).

## License

This project is licensed under the [Elastic License 2.0 (ELv2)](LICENSE).
