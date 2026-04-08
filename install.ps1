# =============================================================================
# AIM-Node Installer for Windows
# =============================================================================
# Usage:
#   irm https://get.ai.market/aim-node/windows | iex
#
# What it does:
#   1. Verifies Docker is installed and running
#   2. Downloads docker-compose.aim-node.yml into $HOME\aim-node
#   3. Pulls ghcr.io/aidotmarket/aim-node:latest
#   4. Runs `docker compose up -d`
# =============================================================================

$ErrorActionPreference = "Stop"

function Write-Info  { param($msg) Write-Host "  > $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "`n  ERROR: $msg`n" -ForegroundColor Red; exit 1 }

function Test-DockerReady {
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $null = docker info 2>&1
        $ErrorActionPreference = $prev
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$repo        = "aidotmarket/aim-node"
$branch      = "main"
$composeUrl  = "https://raw.githubusercontent.com/$repo/$branch/docker-compose.aim-node.yml"
$image       = "ghcr.io/aidotmarket/aim-node:latest"
$installDir  = Join-Path $HOME "aim-node"

Write-Host ""
Write-Host "  AIM-Node Installer" -ForegroundColor Cyan
Write-Host ""

# --- Docker check -----------------------------------------------------------
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Err "Docker is not installed. Install Docker Desktop from https://docs.docker.com/desktop/install/windows/ and re-run."
}

if (-not (Test-DockerReady)) {
    Write-Warn "Docker daemon is not running. Start Docker Desktop and re-run this installer."
    exit 1
}
Write-Ok "Docker is ready"

# --- Install dir ------------------------------------------------------------
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}
Set-Location $installDir
Write-Ok "Install dir: $installDir"

# --- Compose file -----------------------------------------------------------
Write-Info "Downloading docker-compose.aim-node.yml..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    Invoke-WebRequest -Uri $composeUrl -OutFile "docker-compose.aim-node.yml" -UseBasicParsing
} catch {
    Write-Err "Failed to download compose file: $_"
}
Write-Ok "Downloaded compose file"

# --- .env -------------------------------------------------------------------
if (-not (Test-Path ".env")) {
    @"
# AIM-Node configuration
AIM_NODE_VERSION=latest
AIM_NODE_PORT=8080
AIM_API_URL=https://api.ai.market
AIM_NODE_NAME=my-node
"@ | Set-Content -Path ".env"
    Write-Ok "Generated .env"
} else {
    Write-Info ".env already exists — keeping it"
}

# --- Pull image -------------------------------------------------------------
Write-Info "Pulling $image..."
docker pull $image
if ($LASTEXITCODE -ne 0) { Write-Err "Failed to pull $image" }
Write-Ok "Image pulled"

# --- Start ------------------------------------------------------------------
Write-Info "Starting AIM-Node..."
docker compose -f docker-compose.aim-node.yml up -d
if ($LASTEXITCODE -ne 0) { Write-Err "docker compose up failed" }
Write-Ok "Containers started"

# --- Health -----------------------------------------------------------------
$port = (Select-String -Path ".env" -Pattern "^AIM_NODE_PORT=(\d+)" | ForEach-Object { $_.Matches.Groups[1].Value })
if (-not $port) { $port = "8080" }
$url = "http://localhost:$port/api/mgmt/health"

Write-Info "Waiting for health check at $url..."
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        $ErrorActionPreference = $prev
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}

if ($ready) {
    Write-Ok "AIM-Node is healthy"
    Write-Host ""
    Write-Host "  AIM-Node is running" -ForegroundColor Green
    Write-Host "     Health:  $url"
    Write-Host "     Dir:     $installDir"
    Write-Host "     Logs:    docker compose -f $installDir\docker-compose.aim-node.yml logs -f"
    Write-Host ""
} else {
    Write-Warn "Health check did not pass within 60s — check logs:"
    Write-Host "    docker compose -f $installDir\docker-compose.aim-node.yml logs --tail=50"
    exit 1
}
