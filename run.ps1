# Local Production Sealed Application Runner
param (
    [Parameter(Position=0)]
    [ValidateSet("dev", "start", "build", "test", "docker-build", "docker-run", "docker-up", "docker-down", "docker-logs", "vllm-docker", "vllm-serve")]
    [string]$Command = "dev"
)

$CondaBase = if ($env:CONDA_PREFIX) { $env:CONDA_PREFIX } elseif (Test-Path "$env:USERPROFILE\miniconda3") { "$env:USERPROFILE\miniconda3" } elseif (Test-Path "$env:USERPROFILE\anaconda3") { "$env:USERPROFILE\anaconda3" } else { "" }
$PYTHON = if ($CondaBase -and (Test-Path "$CondaBase\envs\ragapp\python.exe")) { "$CondaBase\envs\ragapp\python.exe" } elseif (Get-Command python -ErrorAction SilentlyContinue) { (Get-Command python).Source } else { "python" }

switch ($Command) {
    "dev" {
        Write-Host "🚀 Starting Sealed in Development Mode..." -ForegroundColor Cyan
        Write-Host "   Frontend: http://localhost:5173" -ForegroundColor Green
        Write-Host "   Backend API: http://localhost:8000" -ForegroundColor Green
        Write-Host "   vLLM Expected At: http://localhost:8001/v1" -ForegroundColor Yellow

        # Start Backend in new process
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; & '$PYTHON' -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload"

        # Start Frontend Vite dev server
        Set-Location "$PSScriptRoot\frontend"
        npm run dev
    }

    "build" {
        Write-Host "🔨 Building React + TypeScript Frontend (Nocturne)..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot\frontend"
        npm run build
        Write-Host "✅ Built assets placed into frontend/dist/" -ForegroundColor Green
    }

    "start" {
        Write-Host "⚡ Starting Production Single-Port Server (FastAPI + Built Nocturne SPA)..." -ForegroundColor Cyan
        Write-Host "   App URL: http://localhost:8000" -ForegroundColor Green
        Set-Location "$PSScriptRoot"
        & $PYTHON -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
    }

    "test" {
        Write-Host "🧪 Running Automated Test Suite..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        & $PYTHON -m pytest backend/tests -v
    }

    "docker-build" {
        Write-Host "🐳 Building Unified Docker Image (Frontend + Backend + vLLM)..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        docker build -t sealed-app:latest .
        Write-Host "✅ Docker image 'sealed-app:latest' built successfully!" -ForegroundColor Green
    }

    "docker-run" {
        Write-Host "🚀 Launching Unified Sealed Container (All-in-One)..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        docker run -d --name sealed-sovereign-enclave --gpus all `
            -p 3000:3000 -p 5173:5173 -p 8000:8000 -p 8001:8001 `
            -v sealed_data:/app/data `
            -v huggingface_data:/root/.cache/huggingface `
            sealed-app:latest
        Write-Host "   Frontend UI:  http://localhost:3000 (and http://localhost:5173)" -ForegroundColor Green
        Write-Host "   App / API:    http://localhost:8000" -ForegroundColor Green
        Write-Host "   vLLM Endpoint: http://localhost:8001/v1" -ForegroundColor Green
    }

    "docker-up" {
        Write-Host "🐳 Launching via Docker Compose..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        docker compose up -d
        Write-Host "   Frontend UI: http://localhost:3000 (and http://localhost:5173)" -ForegroundColor Green
        Write-Host "   Sealed App:  http://localhost:8000" -ForegroundColor Green
        Write-Host "   vLLM API:    http://localhost:8001/v1" -ForegroundColor Green
    }

    "docker-down" {
        Write-Host "🛑 Stopping Docker container..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        docker compose down
    }

    "docker-logs" {
        docker logs -f sealed-sovereign-enclave
    }

    "vllm-docker" {
        Write-Host "🚀 Launching vLLM CUDA container on port 8001..." -ForegroundColor Cyan
        Set-Location "$PSScriptRoot"
        docker compose up -d sealed
        Write-Host "   vLLM endpoint: http://localhost:8001/v1" -ForegroundColor Green
    }

    "vllm-serve" {
        Write-Host "⚡ Starting native vLLM inference server on port 8001..." -ForegroundColor Cyan
        vllm serve Qwen/Qwen2.5-3B-Instruct --port 8001 --gpu-memory-utilization 0.70 --max-model-len 8192
    }
}
