from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.benchmarks.benchmark_engine import ScaleBenchmarkingEngine

router = APIRouter()
_engine = None


def get_benchmark_engine() -> ScaleBenchmarkingEngine:
    global _engine
    if _engine is None:
        _engine = ScaleBenchmarkingEngine()
    return _engine


class BenchmarkRunRequest(BaseModel):
    documents: int = Field(default=3, ge=1, le=50, description="Number of synthetic documents to ingest and benchmark")


@router.post("/benchmarks/run")
async def run_benchmark(request: BenchmarkRunRequest = BenchmarkRunRequest()):
    """
    Execute on-demand scale benchmark measuring ingestion throughput,
    retrieval latency percentiles (p50, p95, p99), and IR quality metrics (Recall@10, MRR, nDCG).
    """
    try:
        engine = get_benchmark_engine()
        report = await engine.run_full_benchmark(num_documents=request.documents)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark execution failed: {str(e)}")


@router.get("/benchmarks/hardware")
async def get_hardware():
    """Get host hardware profile (RAM, CPU, GPU acceleration)."""
    return ScaleBenchmarkingEngine.get_hardware_profile()

