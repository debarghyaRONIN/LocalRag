import pytest
import uuid
from pathlib import Path
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.services.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.retrieval.vector_store import QdrantVectorStore


@pytest.mark.asyncio
async def test_end_to_end_ingestion_and_retrieval(tmp_path: Path):
    await init_db()

    unique_token = uuid.uuid4().hex[:8]
    sample_doc = tmp_path / f"deep_learning_spec_{unique_token}.txt"
    sample_doc.write_text(
        f"Build {unique_token}: NVIDIA GeForce RTX 3060 has 12 GB of GDDR6 VRAM with a 192-bit memory interface. "
        "It supports CUDA 12.x and TensorRT acceleration for quantized LLM inference. "
        "By utilizing ONNX Runtime for dense embeddings, CPU and GPU memory bandwidth is optimized.",
        encoding="utf-8"
    )

    vector_store = QdrantVectorStore(storage_path=str(tmp_path / "test_qdrant"))
    pipeline = IngestionPipeline(vector_store=vector_store)
    retrieval_engine = HybridRetrievalEngine(vector_store=vector_store)

    # Ingest document
    async with AsyncSessionLocal() as session:
        meta = await pipeline.ingest_file(sample_doc, session)
        assert meta.doc_id.startswith("doc_")
        assert meta.total_child_chunks >= 1
        assert meta.total_parent_chunks >= 1

        # Idempotency check: ingesting identical file must return same doc_id
        meta_repeat = await pipeline.ingest_file(sample_doc, session)
        assert meta_repeat.doc_id == meta.doc_id

    # Retrieve & Rerank
    query = "What is the memory specification of the RTX 3060?"
    candidates, latencies = retrieval_engine.retrieve_and_rerank(
        query=query,
        top_k=3,
        min_score=0.10
    )

    assert len(candidates) >= 1
    top_hit = candidates[0]
    assert "RTX 3060" in top_hit.content or "VRAM" in top_hit.content
    assert top_hit.rerank_score is not None
    assert top_hit.parent_content is not None
    assert "embed_ms" in latencies
    assert "retrieval_ms" in latencies
    assert "rerank_ms" in latencies

    # Clean up: delete document
    vector_store.delete_by_document(meta.doc_id)

