import os
import sys
import shutil
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


def resolve_data_dir(base_dir: Path) -> Path:
    """
    Determines a writable data directory:
    1. If SEALED_DATA_DIR environment variable is set and non-empty, use it.
    2. If (base_dir / "data") is writable, use it (portable / local development mode).
    3. If (base_dir / "data") is NOT writable (e.g. installed under C:\\Program Files),
       fallback to standard Windows user local app data:
       %LOCALAPPDATA%\\Sealed Sovereign Enclave\\data (or ~/.sealed_sovereign/data)
    """
    if "SEALED_DATA_DIR" in os.environ and os.environ["SEALED_DATA_DIR"].strip():
        p = Path(os.environ["SEALED_DATA_DIR"]).resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass

    cand = (base_dir / "data").resolve()
    try:
        cand.mkdir(parents=True, exist_ok=True)
        probe = cand / ".write_probe"
        with open(probe, "w") as f:
            f.write("1")
        probe.unlink(missing_ok=True)
        return cand
    except Exception:
        if sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
            p = Path(local_app_data) / "Sealed Sovereign Enclave" / "data"
        else:
            p = Path(os.path.expanduser("~/.local/share/sealed_sovereign/data"))
        p.mkdir(parents=True, exist_ok=True)
        # Copy license if present in base_dir
        src_lic = base_dir / "data" / "license.sig"
        if src_lic.exists() and not (p / "license.sig").exists():
            try:
                shutil.copy2(src_lic, p / "license.sig")
            except Exception:
                pass
        return p.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Application
    APP_NAME: str = "Local Production RAG"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Storage Paths
    BASE_DIR: Path = Path(os.environ.get("BASE_DIR", Path(__file__).resolve().parent.parent.parent.parent)).resolve()
    DATA_DIR: Path = resolve_data_dir(Path(os.environ.get("BASE_DIR", Path(__file__).resolve().parent.parent.parent.parent)).resolve())
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    QDRANT_STORAGE_DIR: Path = DATA_DIR / "qdrant_storage"

    # Air-Gap Hardening & Offline Storage
    AIRGAP_MODE: bool = True
    LOCAL_MODELS_DIR: Path = BASE_DIR / "models"
    OFFLINE_LLM_DIR: Path = BASE_DIR / "models" / "llm"
    OFFLINE_EMBEDDING_DIR: Path = BASE_DIR / "models" / "embeddings"
    OFFLINE_RERANKER_DIR: Path = BASE_DIR / "models" / "reranker"
    LOCAL_LLM_DIR: Path = OFFLINE_LLM_DIR
    LOCAL_EMBEDDING_DIR: Path = OFFLINE_EMBEDDING_DIR
    LOCAL_RERANKER_DIR: Path = OFFLINE_RERANKER_DIR

    # Vector Database
    QDRANT_URL: Optional[str] = None  # None => use local embedded directory QDRANT_PATH
    QDRANT_PATH: Optional[str] = "./data/qdrant_storage"
    QDRANT_COLLECTION: str = "local_rag_documents"
    QDRANT_VECTOR_SIZE: int = 384  # 384 for bge-small-en-v1.5, 1024 for bge-m3
    QDRANT_HNSW_M: int = 16
    QDRANT_HNSW_EF_CONSTRUCT: int = 100
    QDRANT_ENABLE_SCALAR_QUANTIZATION: bool = True
    QDRANT_ON_DISK: bool = True

    # Relational Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/ragapp.db"

    # vLLM Dedicated High-Performance Inference Engine
    VLLM_BASE_URL: str = "http://localhost:8001/v1"
    VLLM_API_KEY: str = "EMPTY"
    VLLM_MODEL: str = "Qwen/Qwen2.5-3B-Instruct"
    VLLM_TEMPERATURE: float = 0.1
    VLLM_MAX_TOKENS: int = 2048
    VLLM_TIMEOUT_SECONDS: float = 60.0

    # Aliases for generic references
    @property
    def LLM_BASE_URL(self) -> str:
        return self.VLLM_BASE_URL

    @property
    def LLM_API_KEY(self) -> str:
        return self.VLLM_API_KEY

    @property
    def LLM_MODEL(self) -> str:
        return self.VLLM_MODEL

    # Local Quantized ONNX Models (FastEmbed)
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    # Chunking Configuration (Hierarchical Parent-Child)
    PARENT_CHUNK_SIZE: int = 1000
    PARENT_CHUNK_OVERLAP: int = 150
    CHILD_CHUNK_SIZE: int = 250
    CHILD_CHUNK_OVERLAP: int = 40

    # Retrieval & Reranker Pipeline
    RETRIEVAL_TOP_K: int = 25
    RERANK_TOP_K: int = 5
    RERANK_MIN_SCORE: float = 0.20
    RRF_K: int = 60
    MAX_CONTEXT_TOKENS: int = 3000

    # Observability
    ENABLE_METRICS: bool = True
    PHOENIX_COLLECTOR_ENDPOINT: Optional[str] = "http://localhost:6006/v1/traces"


settings = Settings()

# Ensure directories exist
try:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    settings.QDRANT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"[Warning] Could not initialize data directories: {e}")

for m_dir in [
    settings.LOCAL_MODELS_DIR,
    settings.OFFLINE_LLM_DIR,
    settings.OFFLINE_EMBEDDING_DIR,
    settings.OFFLINE_RERANKER_DIR,
]:
    try:
        m_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

if settings.AIRGAP_MODE:
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
