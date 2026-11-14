import os
import sys
import time
import math
import random
import logging
import psutil
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.core.config import settings
from backend.app.domain.models import DocumentMetadata, ParentChunk, ChildChunk
from backend.app.services.retrieval.embeddings import EmbeddingEngine
from backend.app.services.retrieval.vector_store import QdrantVectorStore
from backend.app.services.retrieval.fts_store import FTS5BM25Store
from backend.app.services.retrieval.reranker import RerankerEngine
from backend.app.services.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBDocument, DBParentChunk
from sqlalchemy import delete

logger = logging.getLogger("benchmark")


@dataclass
class HardwareProfile:
    platform: str
    cpu_count: int
    ram_total_gb: float
    ram_available_gb: float
    gpu_available: bool
    gpu_device_name: str


@dataclass
class IngestionMetrics:
    total_documents: int
    total_chunks: int
    total_tokens: int
    total_time_seconds: float
    chunks_per_second: float
    tokens_per_second: float
    ram_used_mb: float


@dataclass
class LatencyPercentiles:
    mean_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class RetrievalMetrics:
    total_queries: int
    qps: float
    embed_latency: LatencyPercentiles
    retrieval_latency: LatencyPercentiles
    rerank_latency: LatencyPercentiles
    total_latency: LatencyPercentiles


@dataclass
class IRQualityMetrics:
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float


@dataclass
class BenchmarkReport:
    hardware: HardwareProfile
    ingestion: IngestionMetrics
    retrieval: RetrievalMetrics
    ir_quality: IRQualityMetrics


class SyntheticCorpusGenerator:
    """Generates synthetic domain-specific enterprise documents with matching ground-truth queries."""

    TOPICS = [
        ("Airgap Network Cryptography", [
            ("Quantum-Resilient Cipher Negotiation Protocol", "The cipher negotiation protocol utilizes lattice-based Kyber-768 for ephemeral key exchange and Dilithium-3 for digital signatures, ensuring zero plaintext transmission across the air-gap boundary."),
            ("Hardware Security Module Hardware Token Expiration", "Hardware Security Module tokens enforce an immutable TTL of 3600 seconds, requiring tactile cryptographic re-attestation before session key regeneration occurs."),
            ("Zero-Trust Egress Isolation Architecture", "All egress sockets outside the classified enclave are physically blocked by hardware optical data diodes preventing reverse-channel exfiltration."),
        ]),
        ("Distributed Sovereign Vector Engine", [
            ("HNSW Graph Quantization and Memory Footprint", "Scalar INT8 quantization shrinks 1024-dimensional float32 embeddings by four times, enabling up to 10 million vector points to reside comfortably within 16 gigabytes of RAM."),
            ("FTS5 BM25 Lexical Inverted Index Concurrency", "SQLite FTS5 virtual tables maintain synchronous full-text tokens with write-ahead logging (WAL), delivering sub-millisecond keyword lookup for unique serial identifiers and acronyms."),
            ("Parent-Child Chunk Grounding Mechanics", "Child chunks of 128 tokens optimize vector similarity search, while 512-token parent chunks provide complete surrounding context directly to local LLM prompts without additional database roundtrips."),
        ]),
        ("Local Inference Infrastructure", [
            ("vLLM Continuous PagedAttention Scheduling", "PagedAttention decomposes key-value cache memory into non-contiguous physical pages, minimizing fragmentation and sustaining high concurrent token generation throughput."),
            ("Offline Cross-Encoder Reranking Execution", "The BGE-Reranker-v2-m3 model runs via ONNX Runtime local execution provider, scoring candidate document-query pairs with full bidirectional self-attention to filter vector hallucinations."),
            ("Priority Scheduling for Background Indexing Jobs", "When interactive user chat generation begins, background vector indexing is paused instantly to preserve GPU VRAM and CPU cache resources for low-latency token streaming."),
        ]),
    ]

    @classmethod
    def generate(cls, num_docs: int = 3) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
        documents = []
        eval_pairs = []

        for i in range(num_docs):
            topic_idx = i % len(cls.TOPICS)
            topic_name, sections = cls.TOPICS[topic_idx]
            filename = f"bench_doc_{i + 1}_{topic_name.lower().replace(' ', '_')}.txt"

            doc_text_parts = [f"# Enterprise Technical Report: {topic_name}\nDoc ID: BENCH-DOC-{i + 1}\n"]
            for sec_idx, (sec_title, sec_content) in enumerate(sections, start=1):
                doc_text_parts.append(f"## {sec_title}\n{sec_content}\n")

                # Generate a targeted query matching this exact section
                query = f"What are the specifications and implementation details of {sec_title} in {topic_name}?"
                eval_pairs.append({
                    "query": query,
                    "target_keyword": sec_title.split()[0].lower(),
                    "expected_content": sec_content[:60],
                    "doc_index": i + 1,
                })

            full_text = "\n\n".join(doc_text_parts)
            documents.append({
                "filename": filename,
                "content": full_text,
            })

        return documents, eval_pairs


def compute_percentiles(values: List[float]) -> LatencyPercentiles:
    if not values:
        return LatencyPercentiles(0, 0, 0, 0, 0)
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def pct(p):
        idx = int(math.ceil(p * n) - 1)
        return sorted_vals[max(0, min(n - 1, idx))]

    return LatencyPercentiles(
        mean_ms=round(sum(sorted_vals) / n, 2),
        p50_ms=round(pct(0.50), 2),
        p90_ms=round(pct(0.90), 2),
        p95_ms=round(pct(0.95), 2),
        p99_ms=round(pct(0.99), 2),
    )


class ScaleBenchmarkingEngine:
    """Production-grade scale benchmarking engine for ingestion, hybrid retrieval, and IR quality."""

    def __init__(self):
        self.pipeline = IngestionPipeline()
        self.retrieval_engine = HybridRetrievalEngine()

    @staticmethod
    def get_hardware_profile() -> HardwareProfile:
        vm = psutil.virtual_memory()
        gpu_avail = False
        gpu_name = "None"
        try:
            import torch
            if torch.cuda.is_available():
                gpu_avail = True
                gpu_name = torch.cuda.get_device_name(0)
        except Exception:
            pass

        return HardwareProfile(
            platform=sys.platform,
            cpu_count=os.cpu_count() or 4,
            ram_total_gb=round(vm.total / (1024 ** 3), 2),
            ram_available_gb=round(vm.available / (1024 ** 3), 2),
            gpu_available=gpu_avail,
            gpu_device_name=gpu_name,
        )

    async def benchmark_ingestion(self, documents: List[Dict[str, str]]) -> Tuple[IngestionMetrics, List[str]]:
        bench_dir = settings.DATA_DIR / "benchmarks_tmp"
        bench_dir.mkdir(parents=True, exist_ok=True)

        total_chunks = 0
        total_tokens = 0
        doc_ids = []

        ram_before = psutil.virtual_memory().used
        t0 = time.perf_counter()

        async with AsyncSessionLocal() as session:
            for item in documents:
                file_path = bench_dir / item["filename"]
                file_path.write_text(item["content"], encoding="utf-8")

                meta = await self.pipeline.ingest_file(
                    file_path=file_path,
                    db_session=session,
                    filename=item["filename"],
                )
                doc_ids.append(meta.doc_id)
                total_chunks += meta.total_child_chunks
                # Approximate tokens
                total_tokens += len(item["content"].split()) * 2

                # Cleanup temporary file
                try:
                    file_path.unlink()
                except Exception:
                    pass

        elapsed = time.perf_counter() - t0
        ram_after = psutil.virtual_memory().used
        ram_diff_mb = max(0.0, (ram_after - ram_before) / (1024 * 1024))

        chunks_per_sec = total_chunks / max(elapsed, 0.001)
        tokens_per_sec = total_tokens / max(elapsed, 0.001)

        metrics = IngestionMetrics(
            total_documents=len(documents),
            total_chunks=total_chunks,
            total_tokens=total_tokens,
            total_time_seconds=round(elapsed, 3),
            chunks_per_second=round(chunks_per_sec, 2),
            tokens_per_second=round(tokens_per_sec, 2),
            ram_used_mb=round(ram_diff_mb, 2),
        )
        return metrics, doc_ids

    def benchmark_retrieval(
        self,
        eval_pairs: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> Tuple[RetrievalMetrics, IRQualityMetrics]:
        embed_times = []
        retrieval_times = []
        rerank_times = []
        total_times = []

        recalls_5 = []
        recalls_10 = []
        mrrs = []
        ndcgs = []

        t_bench_start = time.perf_counter()

        for ep in eval_pairs:
            q = ep["query"]
            expected = ep["expected_content"]

            t0 = time.perf_counter()
            candidates, latencies = self.retrieval_engine.retrieve_and_rerank(
                query=q,
                top_k=top_k,
                min_score=-10.0,  # capture full candidate list for evaluation
            )
            total_ms = (time.perf_counter() - t0) * 1000

            embed_times.append(latencies.get("embed_ms", 0.0))
            retrieval_times.append(latencies.get("retrieval_ms", 0.0))
            rerank_times.append(latencies.get("rerank_ms", 0.0))
            total_times.append(total_ms)

            # Evaluate IR accuracy
            rank_found = 0
            for r_idx, c in enumerate(candidates, start=1):
                if expected[:30].lower() in (c.parent_content or "").lower() or expected[:30].lower() in c.content.lower():
                    rank_found = r_idx
                    break

            if rank_found > 0:
                recalls_5.append(1.0 if rank_found <= 5 else 0.0)
                recalls_10.append(1.0 if rank_found <= 10 else 0.0)
                mrrs.append(1.0 / rank_found)
                ndcgs.append(1.0 / math.log2(rank_found + 1))
            else:
                recalls_5.append(0.0)
                recalls_10.append(0.0)
                mrrs.append(0.0)
                ndcgs.append(0.0)

        total_elapsed = time.perf_counter() - t_bench_start
        num_queries = len(eval_pairs)
        qps = num_queries / max(total_elapsed, 0.001)

        retrieval_metrics = RetrievalMetrics(
            total_queries=num_queries,
            qps=round(qps, 2),
            embed_latency=compute_percentiles(embed_times),
            retrieval_latency=compute_percentiles(retrieval_times),
            rerank_latency=compute_percentiles(rerank_times),
            total_latency=compute_percentiles(total_times),
        )

        n_eval = max(len(eval_pairs), 1)
        ir_metrics = IRQualityMetrics(
            recall_at_5=round(sum(recalls_5) / n_eval, 4),
            recall_at_10=round(sum(recalls_10) / n_eval, 4),
            mrr_at_10=round(sum(mrrs) / n_eval, 4),
            ndcg_at_10=round(sum(ndcgs) / n_eval, 4),
        )

        return retrieval_metrics, ir_metrics

    async def run_full_benchmark(self, num_documents: int = 3) -> Dict[str, Any]:
        """Execute complete scale benchmarking cycle."""
        await init_db()
        hardware = self.get_hardware_profile()

        # 1. Generate Synthetic Corpus
        docs, eval_pairs = SyntheticCorpusGenerator.generate(num_docs=num_documents)

        # 2. Benchmark Ingestion
        ingest_metrics, doc_ids = await self.benchmark_ingestion(docs)

        # 3. Benchmark Retrieval & IR Quality
        retrieval_metrics, ir_metrics = self.benchmark_retrieval(eval_pairs)

        report = BenchmarkReport(
            hardware=hardware,
            ingestion=ingest_metrics,
            retrieval=retrieval_metrics,
            ir_quality=ir_metrics,
        )

        # Cleanup generated documents from vector store and DB
        async with AsyncSessionLocal() as session:
            for did in doc_ids:
                try:
                    self.retrieval_engine.vector_store.delete_by_document(did)
                    self.retrieval_engine.fts_store.delete_by_doc(did)
                    await session.execute(delete(DBParentChunk).where(DBParentChunk.doc_id == did))
                    await session.execute(delete(DBDocument).where(DBDocument.doc_id == did))
                except Exception:
                    pass
            await session.commit()

        return {
            "hardware": asdict(hardware),
            "ingestion": asdict(ingest_metrics),
            "retrieval": asdict(retrieval_metrics),
            "ir_quality": asdict(ir_metrics),
        }


def print_cli_report(report: Dict[str, Any]):
    hw = report["hardware"]
    ing = report["ingestion"]
    ret = report["retrieval"]
    ir = report["ir_quality"]

    print("\n" + "=" * 65)
    print("  AIRGAP LOCAL RAG ENGINE - SCALE BENCHMARK REPORT")
    print("=" * 65)
    print(f"Hardware Platform:   {hw['platform']} ({hw['cpu_count']} CPUs)")
    print(f"System RAM:          {hw['ram_available_gb']} GB available / {hw['ram_total_gb']} GB total")
    print(f"GPU Accelerator:     {hw['gpu_device_name']} (Available: {hw['gpu_available']})")
    print("-" * 65)
    print("INGESTION PERFORMANCE")
    print(f"Documents Ingested:  {ing['total_documents']}")
    print(f"Chunks Produced:     {ing['total_chunks']}")
    print(f"Throughput (chunks): {ing['chunks_per_second']} chunks/sec")
    print(f"Throughput (tokens): {ing['tokens_per_second']} tokens/sec")
    print(f"Elapsed Ingestion:   {ing['total_time_seconds']}s")
    print("-" * 65)
    print("RETRIEVAL LATENCY BREAKDOWN (ms)")
    print(f"Total Queries:       {ret['total_queries']} ({ret['qps']} QPS)")
    print(f"Dense Embedding:     p50={ret['embed_latency']['p50_ms']}ms | p95={ret['embed_latency']['p95_ms']}ms | Mean={ret['embed_latency']['mean_ms']}ms")
    print(f"Hybrid Retrieval:    p50={ret['retrieval_latency']['p50_ms']}ms | p95={ret['retrieval_latency']['p95_ms']}ms | Mean={ret['retrieval_latency']['mean_ms']}ms")
    print(f"ONNX Reranker:       p50={ret['rerank_latency']['p50_ms']}ms | p95={ret['rerank_latency']['p95_ms']}ms | Mean={ret['rerank_latency']['mean_ms']}ms")
    print(f"Total E2E Latency:   p50={ret['total_latency']['p50_ms']}ms | p95={ret['total_latency']['p95_ms']}ms | Mean={ret['total_latency']['mean_ms']}ms")
    print("-" * 65)
    print("INFORMATION RETRIEVAL ACCURACY (Ground Truth)")
    print(f"Recall@5:            {ir['recall_at_5'] * 100:.1f}%")
    print(f"Recall@10:           {ir['recall_at_10'] * 100:.1f}%")
    print(f"MRR@10:              {ir['mrr_at_10']:.4f}")
    print(f"nDCG@10:             {ir['ndcg_at_10']:.4f}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Airgap Local RAG Benchmark Engine")
    parser.add_argument("--docs", type=int, default=3, help="Number of synthetic documents to ingest and test")
    args = parser.parse_args()

    engine = ScaleBenchmarkingEngine()
    result = asyncio.run(engine.run_full_benchmark(num_documents=args.docs))
    print_cli_report(result)

