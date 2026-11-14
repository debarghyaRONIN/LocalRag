# =====================================================================
# Stage 1: Build Sealed Frontend (React 18 + TypeScript + Nocturne)
# =====================================================================
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci || npm install

COPY frontend/ ./
RUN npm run build

# =====================================================================
# Stage 2: Unified Sovereign Enclave Runtime (vLLM + Backend + Frontend)
# =====================================================================
FROM vllm/vllm-openai:latest AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=8000 \
    HOST=0.0.0.0 \
    VLLM_BASE_URL=http://127.0.0.1:8001/v1 \
    VLLM_PORT=8001 \
    VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct \
    GPU_MEMORY_UTILIZATION=0.65 \
    MAX_MODEL_LEN=8192 \
    QDRANT_PATH=/app/data/qdrant_storage \
    DATABASE_URL=sqlite+aiosqlite:////app/data/ragapp.db

WORKDIR /app

# Install system libraries needed for offline OCR, image processing, and process management
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache FastEmbed embedding and reranker ONNX models for 100% offline air-gapped retrieval
RUN python3 -c "\
from fastembed import TextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5'); \
TextCrossEncoder('BAAI/bge-reranker-base'); \
print('FastEmbed ONNX models cached successfully.')"

# Copy compiled Frontend SPA assets from Stage 1 into /app/frontend/dist
COPY --from=frontend-builder /build/dist /app/frontend/dist

# Copy Backend application code
COPY backend/ /app/backend/

# Copy launcher entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Create persistent storage scaffolding
RUN mkdir -p /app/data/uploads /app/data/qdrant_storage /app/models /root/.cache/huggingface

# Expose Frontend UI ports (3000, 5173), Backend API port (8000), and vLLM inference port (8001)
EXPOSE 3000 5173 8000 8001

HEALTHCHECK --interval=20s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
