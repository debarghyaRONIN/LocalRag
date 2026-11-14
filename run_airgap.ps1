# ==============================================================================
# Ragapp Air-Gap Production Startup Script (PowerShell / Windows)
# Zero-Egress Offline Mode Enforcement
# ==============================================================================
param (
    [Parameter(Position=0)]
    [ValidateSet("start", "dev", "verify", "load-images", "docker-up", "docker-down")]
    [string]$Command = "start",

    [string]$HostIP = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$SCRIPT_ROOT = $PSScriptRoot
$MODELS_DIR = Join-Path $SCRIPT_ROOT "models"
$IMAGES_DIR = Join-Path $SCRIPT_ROOT "docker_images"

# ------------------------------------------------------------------------------
# 1. Enforce Air-Gap / Zero-Egress Environment Flags
# ------------------------------------------------------------------------------
Write-Host "🛡️  Enforcing Zero-Egress Air-Gap Environment Variables..." -ForegroundColor Cyan
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_DATASETS_OFFLINE = "1"
$env:AIRGAP_MODE = "true"
$env:DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"

# Redirect model cache directories to local air-gapped models
$env:HF_HOME = $MODELS_DIR
$env:TRANSFORMERS_CACHE = $MODELS_DIR
$env:FASTEMBED_CACHE_PATH = Join-Path $MODELS_DIR "embeddings"

Write-Host "   HF_HUB_OFFLINE        = $env:HF_HUB_OFFLINE" -ForegroundColor DarkGray
$PythonCmd = if ($env:CONDA_PREFIX -and (Test-Path "$env:CONDA_PREFIX\python.exe")) {
    "$env:CONDA_PREFIX\python.exe"
} elseif (Test-Path "$env:USERPROFILE\miniconda3\envs\ragapp\python.exe") {
    "$env:USERPROFILE\miniconda3\envs\ragapp\python.exe"
} elseif (Test-Path "$env:USERPROFILE\anaconda3\envs\ragapp\python.exe") {
    "$env:USERPROFILE\anaconda3\envs\ragapp\python.exe"
} else {
    "python"
}

# ------------------------------------------------------------------------------
# 2. Command Execution
# ------------------------------------------------------------------------------
switch ($Command) {
    "verify" {
        Write-Host "🔍 Running Airgap Offline Preflight Verification..." -ForegroundColor Cyan
        & $PythonCmd -c "from backend.app.core.network_guard import assert_offline_mode, audit_network_guard; assert_offline_mode(); print('✅ Air-gap offline verification successful:', audit_network_guard())"
    }

    "load-images" {
        Write-Host "📦 Loading offline Docker tar images from $IMAGES_DIR..." -ForegroundColor Cyan
        if (Test-Path $IMAGES_DIR) {
            Get-ChildItem -Path $IMAGES_DIR -Filter "*.tar" | ForEach-Object {
                Write-Host "   Loading: $($_.Name)..." -ForegroundColor Yellow
                docker load -i $_.FullName
            }
            Write-Host "✅ All offline Docker images loaded." -ForegroundColor Green
        } else {
            Write-Warning "No docker_images directory found at $IMAGES_DIR."
        }
    }

    "docker-up" {
        Write-Host "🐳 Launching local container infrastructure in offline mode..." -ForegroundColor Cyan
        Set-Location $SCRIPT_ROOT
        docker compose up -d
        Write-Host "✅ Offline services running (Qdrant, Postgres, Phoenix, vLLM)." -ForegroundColor Green
    }

    "docker-down" {
        Write-Host "🛑 Stopping offline containers..." -ForegroundColor Cyan
        Set-Location $SCRIPT_ROOT
        docker compose down
    }

    "dev" {
        Write-Host "🚀 Launching Ragapp in Air-Gapped Development Mode..." -ForegroundColor Green
        Set-Location $SCRIPT_ROOT
        & $PythonCmd -m uvicorn backend.app.main:app --host $HostIP --port $Port --reload
    }

    "start" {
        Write-Host "⚡ Launching Ragapp Air-Gapped Production Server on http://${HostIP}:${Port}..." -ForegroundColor Green
        Set-Location $SCRIPT_ROOT
        & $PythonCmd -m uvicorn backend.app.main:app --host $HostIP --port $Port
    }
}
