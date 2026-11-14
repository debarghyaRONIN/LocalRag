# RagProd Local: Production-Grade Offline RAG System

Enterprise-grade, privacy-first Retrieval-Augmented Generation (RAG) system running completely offline on consumer PC hardware (**AMD Ryzen 5 5600X, 32 GB RAM, NVIDIA GeForce RTX 3060 12 GB VRAM**).

---

## Key Highlights

- **Zero Cloud Leakage**: Ingestion, dense embedding, cross-encoder reranking, and generation run 100% locally.
- **Strict 12GB VRAM Envelope**: Model weights and KV caches are strictly partitioned to prevent CUDA Out-Of-Memory (OOM) errors.
- **Hierarchical Parent-Child Chunking**: Small child chunks (250 tokens) are indexed into Qdrant for semantic precision; parent chunks (1000 tokens) are passed to the generator to preserve complete surrounding context.
- **Hybrid Retrieval & Reranking**: Dense cosine vector search + sparse lexical BM25 fused via Reciprocal Rank Fusion (RRF), passed through an ONNX **`bge-reranker-base`** cross-encoder with score cutoff filtering.
- **Content-Addressable Idempotency**: SHA-256 document hashing ensures identical files are never re-indexed or duplicated.
- **Verifiable Citations**: Grounded LLM prompt forces inline citations `[1]`, `[2]` linked directly to source documents, page numbers, and exact text chunks.
- **Full Stack React + Vite UI**: Built with TypeScript, Tailwind CSS, Lucide icons, streaming SSE chat, interactive citation source inspector drawer, and drag-and-drop document manager.

---

## Architecture Diagram

```
+-------------------------------------------------------------------------------+
| React + TypeScript + Tailwind UI (Port 5173 / Port 8000)                      |
| - SSE Token Streaming Chat                                                    |
| - Interactive Source Inspector Drawer (Parent Context & Reranker Score)       |
| - Drag-and-drop Multi-Format Document Ingestion                               |
+-------------------------------------------------------------------------------+
                                      |
                           HTTP / SSE | REST API
                                      v
+-------------------------------------------------------------------------------+
| FastAPI Async Gateway (Port 8000)                                             |
| - API Router: /api/v1/query, /api/v1/documents, /api/v1/health, /api/v1/sessions|
| - SQLite (WAL Mode) / PostgreSQL Metadata & Conversation History              |
+-------------------------------------------------------------------------------+
           |                                             |
           v                                             v
+-------------------------------------+   +-------------------------------------+
| Ingestion & Chunking Service        |   | Hybrid Retrieval & Rerank Engine    |
| - PyMuPDF / docx / CSV layout parser|   | 1. Query Dense ONNX Embedding       |
| - SHA-256 Hash Deduplication        |   | 2. Qdrant Dense Cosine Search       |
| - Parent-Child Hierarchical Chunker |   | 3. Lexical BM25 Overlap & RRF Fusion|
| - FastEmbed ONNX (bge-small-en-v1.5)|   | 4. ONNX Cross-Encoder (bge-reranker)|
+-------------------------------------+   +-------------------------------------+
           |                                             |
           +----------------------+----------------------+
                                  |
                                  v
+-------------------------------------------------------------------------------+
| Local Storage & Inference Layer                                               |
| - Qdrant Vector DB: Embedded Local Storage or Docker Cluster                  |
| - Local LLM Engine: Ollama / LM Studio / vLLM (Qwen2.5-7B-Instruct-Q4)        |
+-------------------------------------------------------------------------------+
```

---

## Hardware Budget (12 GB VRAM / 32 GB RAM)

| Component | Engine / Model | Memory Footprint | Device |
| :--- | :--- | :--- | :--- |
| **Generator LLM** | `vLLM (Qwen/Qwen2.5-3B-Instruct / 7B-AWQ)` | ~6.5 GB VRAM | GPU (CUDA / PagedAttention) |
| **Dense Embeddings** | `bge-small-en-v1.5` (ONNX Quantized) | ~150 MB RAM/VRAM | CPU / GPU |
| **Cross-Encoder Reranker** | `bge-reranker-base` (ONNX) | ~400 MB RAM/VRAM | CPU / GPU |
| **Vector DB** | Qdrant (Rust HNSW) | ~250 MB RAM | Host RAM |
| **Relational DB** | SQLite WAL / Postgres | ~100 MB RAM | Host RAM |
| **FastAPI Backend** | Python 3.11 Uvicorn | ~200 MB RAM | Host RAM |
| **Headroom Margin** | Windows DWM / Dynamic KV Cache | ~4.5 GB VRAM free | Safety Buffer |

---

## Quickstart

### 1. Prerequisites
- Windows 11 with Python 3.11 (Conda environment `ragapp`)
- Node.js 20+ and npm
- vLLM serving engine running on port 8001 (via Docker or native WSL2 `vllm serve`)

### 2. Single-Command Launch (PowerShell)

```powershell
# 1. Start vLLM inference engine (Docker CUDA container or native)
.\run.ps1 vllm-docker
# or native: .\run.ps1 vllm-serve

# 2. Development Mode (Starts FastAPI backend on port 8000 and Vite dev server on port 5173)
.\run.ps1 dev

# 3. Production Single-Port Mode (Serves both API & UI on http://localhost:8000)
.\run.ps1 build
.\run.ps1 start

# 4. Run Automated Test Suite
.\run.ps1 test
```

---

## API Endpoints

- `GET  /api/v1/health`: Real-time GPU VRAM stats, Qdrant chunk count, document counts.
- `POST /api/v1/documents/upload`: Multipart file upload (PDF, DOCX, TXT, MD, CSV, JSON).
- `GET  /api/v1/documents`: List all indexed documents.
- `DELETE /api/v1/documents/{doc_id}`: Purge document and vectors.
- `POST /api/v1/query`: Standard JSON query endpoint.
- `POST /api/v1/query/stream`: Server-Sent Events (SSE) streaming endpoint.
- `GET  /api/v1/sessions`: List conversation sessions.
- `GET  /metrics`: Prometheus metrics scraper endpoint.

