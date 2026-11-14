import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.benchmarks.benchmark_engine import (
    ScaleBenchmarkingEngine,
    SyntheticCorpusGenerator,
    compute_percentiles,
)


def test_synthetic_corpus_generator():
    docs, eval_pairs = SyntheticCorpusGenerator.generate(num_docs=2)
    assert len(docs) == 2
    assert len(eval_pairs) == 6
    assert "content" in docs[0]
    assert "query" in eval_pairs[0]
    assert "expected_content" in eval_pairs[0]


def test_percentile_computation():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    pcts = compute_percentiles(vals)
    assert pcts.mean_ms == 30.0
    assert pcts.p50_ms == 30.0
    assert pcts.p90_ms == 50.0


def test_hardware_profiler():
    hw = ScaleBenchmarkingEngine.get_hardware_profile()
    assert hw.cpu_count >= 1
    assert hw.ram_total_gb > 0
    assert isinstance(hw.gpu_available, bool)


@pytest.mark.asyncio
async def test_benchmark_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Test hardware endpoint
        hw_resp = await ac.get("/api/v1/benchmarks/hardware")
        assert hw_resp.status_code == 200
        hw_data = hw_resp.json()
        assert "cpu_count" in hw_data
        assert "ram_total_gb" in hw_data

        # Test run endpoint with 1 document for quick test execution
        run_resp = await ac.post("/api/v1/benchmarks/run", json={"documents": 1})
        assert run_resp.status_code == 200
        rep = run_resp.json()
        assert "hardware" in rep
        assert "ingestion" in rep
        assert "retrieval" in rep
        assert "ir_quality" in rep
        assert rep["ingestion"]["total_documents"] == 1
        assert rep["retrieval"]["total_queries"] == 3
        assert "recall_at_10" in rep["ir_quality"]

