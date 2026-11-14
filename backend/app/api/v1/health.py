import subprocess
from typing import Optional, Tuple
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.app.core.config import settings
from backend.app.domain.models import HealthResponse
from backend.app.db.session import get_db
from backend.app.db.models import DBDocument, DBParentChunk
from backend.app.services.retrieval.vector_store import QdrantVectorStore
from backend.app.services.generation.llm_client import VLLMClient
from backend.app.inference.manager import InferenceManager
from backend.app.inference.detector.models import GPUVendor

router = APIRouter()
vllm_client = VLLMClient()


def get_gpu_vram() -> Tuple[bool, Optional[str], Optional[int], Optional[int]]:
    """
    Query GPU status and VRAM usage in MB across NVIDIA and AMD hardware.
    Integrates with the unified InferenceManager hardware detector.
    """
    try:
        hw = InferenceManager.get_instance().detect_hardware()
        if hw.detected_devices:
            dev = hw.selected_device or hw.detected_devices[0]
            name = dev.name
            total_mb = dev.vram_total_mb

            # If NVIDIA, attempt precise live query via nvidia-smi
            if hw.selected_vendor == GPUVendor.NVIDIA or dev.vendor == GPUVendor.NVIDIA:
                try:
                    output = subprocess.check_output(
                        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                        encoding="utf-8",
                        timeout=1.5
                    ).strip()
                    if output:
                        parts = [p.strip() for p in output.split(",")]
                        used_mb = int(parts[0])
                        total_mb = int(parts[1])
                        return True, name, used_mb, total_mb
                except Exception:
                    pass

            used_mb = dev.vram_used_mb if dev.vram_used_mb > 0 else (
                (dev.vram_total_mb - dev.vram_free_mb) if dev.vram_free_mb else None
            )
            return True, name, used_mb, total_mb
    except Exception:
        pass
    return False, None, None, None


@router.get("/health", response_model=HealthResponse)
async def check_system_health(db: AsyncSession = Depends(get_db)):
    """
    Diagnostic healthcheck returning real-time GPU VRAM, Qdrant vector counts, and DB counts.
    """
    gpu_available, gpu_name, used_mb, total_mb = get_gpu_vram()

    # Vector store count
    vector_store = QdrantVectorStore.get_instance()
    total_vectors = vector_store.count()

    # Relational DB count
    doc_count_stmt = select(func.count(DBDocument.doc_id))
    doc_res = await db.execute(doc_count_stmt)
    total_docs = doc_res.scalar() or 0

    # vLLM Engine readiness
    vllm_status = await vllm_client.check_readiness()

    return HealthResponse(
        status="healthy",
        app_version=settings.APP_VERSION,
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        gpu_memory_used_mb=used_mb,
        gpu_memory_total_mb=total_mb,
        vector_db_ready=True,
        vllm_ready=vllm_status.get("online", False),
        vllm_model=vllm_status.get("primary_model") or settings.VLLM_MODEL,
        total_indexed_documents=total_docs,
        total_indexed_chunks=total_vectors,
    )

