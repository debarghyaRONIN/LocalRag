#!/usr/bin/env bash
# ==============================================================================
# Ragapp Air-Gap Production Startup Script (POSIX Bash / Linux)
# Zero-Egress Offline Mode Enforcement
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND="${1:-start}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

MODELS_DIR="${SCRIPT_DIR}/models"
IMAGES_DIR="${SCRIPT_DIR}/docker_images"

# ------------------------------------------------------------------------------
# 1. Enforce Air-Gap / Zero-Egress Environment Flags
# ------------------------------------------------------------------------------
echo "🛡️  Enforcing Zero-Egress Air-Gap Environment Variables..."
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export AIRGAP_MODE=true
export DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1

# Local model paths
export HF_HOME="${MODELS_DIR}"
export TRANSFORMERS_CACHE="${MODELS_DIR}"
export FASTEMBED_CACHE_PATH="${MODELS_DIR}/embeddings"

PYTHON_BIN="$(which python3 || which python || echo "python3")"

# ------------------------------------------------------------------------------
# 2. Command Execution
# ------------------------------------------------------------------------------
case "${COMMAND}" in
    verify)
        echo "🔍 Running Airgap Offline Preflight Verification..."
        "${PYTHON_BIN}" -c "from backend.app.core.network_guard import assert_offline_mode, audit_network_guard; assert_offline_mode(); print('✅ Air-gap offline verification successful:', audit_network_guard())"
        ;;
    load-images)
        echo "📦 Loading offline Docker tar images from ${IMAGES_DIR}..."
        if [ -d "${IMAGES_DIR}" ]; then
            for img in "${IMAGES_DIR}"/*.tar; do
                if [ -f "${img}" ]; then
                    echo "   Loading: $(basename "${img}")..."
                    docker load -i "${img}"
                fi
            done
            echo "✅ All offline Docker images loaded."
        else
            echo "⚠️  No docker_images directory found at ${IMAGES_DIR}."
        fi
        ;;
    docker-up)
        echo "🐳 Launching local container infrastructure in offline mode..."
        cd "${SCRIPT_DIR}"
        docker compose up -d
        echo "✅ Offline services running (Qdrant, Postgres, Phoenix, vLLM)."
        ;;
    docker-down)
        echo "🛑 Stopping offline containers..."
        cd "${SCRIPT_DIR}"
        docker compose down
        ;;
    dev)
        echo "🚀 Launching Ragapp in Air-Gapped Development Mode..."
        cd "${SCRIPT_DIR}"
        exec "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${HOST}" --port "${PORT}" --reload
        ;;
    start)
        echo "⚡ Launching Ragapp Air-Gapped Production Server on http://${HOST}:${PORT}..."
        cd "${SCRIPT_DIR}"
        exec "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${HOST}" --port "${PORT}"
        ;;
    *)
        echo "Usage: $0 {start|dev|verify|load-images|docker-up|docker-down}"
        exit 1
        ;;
esac
