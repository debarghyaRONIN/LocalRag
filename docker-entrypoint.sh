#!/usr/bin/env bash
set -e

# =====================================================================
# Sealed Sovereign Enclave - Unified Container Entrypoint
# Runs vLLM Inference + FastAPI Backend + Built React Frontend
# =====================================================================

VLLM_PID=""
BACKEND_PID=""
FRONTEND_PID=""
VITE_PID=""

cleanup() {
  echo ""
  echo "[Sealed Enclave] Received stop signal. Gracefully shutting down services..."
  if [ -n "$FRONTEND_PID" ]; then
    kill -TERM "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$VITE_PID" ]; then
    kill -TERM "$VITE_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ]; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$VLLM_PID" ]; then
    kill -TERM "$VLLM_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  echo "[Sealed Enclave] All processes stopped."
  exit 0
}

trap cleanup SIGTERM SIGINT SIGQUIT

echo "====================================================================="
echo "  SEALED AIRGAP SOVEREIGN ENCLAVE"
echo "  100% Local Inference & Knowledge Engine in a Single Container"
echo "====================================================================="

# 1. Prepare local persistent directories
mkdir -p /app/data/uploads /app/data/qdrant_storage /app/models /root/.cache/huggingface

# 2. Check GPU environment
USE_GPU=false
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "[+] Hardware: NVIDIA GPU accelerator detected:"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
  USE_GPU=true
else
  echo "[!] Hardware: No active NVIDIA GPU detected or --gpus flag omitted."
  echo "    Running inference in host CPU / fallback mode."
fi

# 3. Launch local vLLM inference server in background
VLLM_PORT="${VLLM_PORT:-8001}"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.80}"
KV_CACHE_MEMORY_BYTES="${KV_CACHE_MEMORY_BYTES:-536870912}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-2048}"

echo ""
echo "[+] Initializing dedicated vLLM server for '${VLLM_MODEL}' on port ${VLLM_PORT}..."

if [ "$USE_GPU" = "true" ]; then
  python3 -m vllm.entrypoints.openai.api_server \
    --model "${VLLM_MODEL}" \
    --port "${VLLM_PORT}" \
    --host 0.0.0.0 \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --kv-cache-memory-bytes "${KV_CACHE_MEMORY_BYTES}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --dtype auto \
    --enforce-eager \
    ${EXTRA_VLLM_ARGS:-} &
  VLLM_PID=$!
else
  # CPU fallback execution
  python3 -m vllm.entrypoints.openai.api_server \
    --model "${VLLM_MODEL}" \
    --port "${VLLM_PORT}" \
    --host 0.0.0.0 \
    --max-model-len 4096 \
    --dtype float32 \
    ${EXTRA_VLLM_ARGS:-} &
  VLLM_PID=$!
fi

# 4. Wait for vLLM API server to initialize
echo "[*] Waiting for vLLM model weights and KV cache to warm up..."
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
  if curl -s "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
    echo "[+] vLLM is ONLINE and serving ${VLLM_MODEL} on port ${VLLM_PORT}!"
    break
  fi
  sleep 2
  WAITED=$((WAITED + 2))
  # Check if vLLM process exited prematurely
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "[!] Warning: vLLM process exited. Check Docker container GPU allocations."
    break
  fi
done

# 5. Start Dedicated Frontend Server (Ports 3000 and 5173)
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
echo ""
echo "[+] Starting Dedicated Frontend Server on 0.0.0.0:${FRONTEND_PORT}..."
python3 /app/backend/app/serve_frontend.py "${FRONTEND_PORT}" &
FRONTEND_PID=$!

echo "[+] Starting Frontend Vite Compatibility Listener on 0.0.0.0:5173..."
python3 /app/backend/app/serve_frontend.py 5173 &
VITE_PID=$!

# 6. Start FastAPI Backend API & Unified Server (Port 8000)
PORT="${PORT:-8000}"
echo ""
echo "[+] Starting FastAPI Backend API on 0.0.0.0:${PORT}..."
export VLLM_BASE_URL="http://127.0.0.1:${VLLM_PORT}/v1"
export QDRANT_PATH="/app/data/qdrant_storage"
export DATABASE_URL="sqlite+aiosqlite:////app/data/ragapp.db"

python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}" &
BACKEND_PID=$!

echo ""
echo "====================================================================="
echo "  SEALED ENCLAVE READY AND RUNNING:"
echo "  - Dedicated Frontend UI:    http://localhost:${FRONTEND_PORT}"
echo "  - Vite Compatibility UI:    http://localhost:5173"
echo "  - Backend & Web Combined:   http://localhost:${PORT}"
echo "  - Backend REST API Docs:    http://localhost:${PORT}/docs"
echo "  - vLLM Endpoint:            http://localhost:${VLLM_PORT}/v1"
echo "  - Egress Network Policy:    Zero Outbound (Air-Gapped)"
echo "====================================================================="
echo ""

# Keep container alive and supervise child processes
while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[!] Warning: Backend process exited. Auto-recovering uvicorn..."
    python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}" &
    BACKEND_PID=$!
  fi
  sleep 2
done

