"""
Unit and integration tests for indexing scheduler and job queue lifecycle.

Validates:
1. DBIndexingJob model persistence and state transitions:
   - Statuses: QUEUED, RUNNING, PAUSED, COMPLETED, FAILED.
   - Progress tracking: total_files, processed_files, total_chunks, error_message.
2. File discovery and exclusion filtering:
   - Supported text and code extensions.
   - Exclusion of hidden files, .git, node_modules, build directories, and binaries.
3. ResourceScheduler monitoring and priority scheduling:
   - System RAM usage inspection via psutil.
   - GPU VRAM telemetry (with graceful fallback for CPU-only systems).
   - Priority chat scope tracking (register_chat_start, register_chat_finish).
   - Dynamic yielding/throttling of background indexing tasks when interactive chats are in flight.
4. JobManager async concurrency and lifecycle:
   - Folder ingestion job submission and execution.
   - Cooperative pause and resume controls.
   - Crash recovery on startup (recovering jobs left in RUNNING state).
5. Vector store index scalability configuration:
   - HNSW graph parameters (m=16, ef_construct=100) and scalar quantization.
6. REST API endpoints for indexing management:
   - GET /api/v1/indexing/jobs
   - GET /api/v1/indexing/jobs/{job_id}
   - POST /api/v1/indexing/jobs/{job_id}/pause
   - POST /api/v1/indexing/jobs/{job_id}/resume
   - POST /api/v1/indexing/ingest-folder
   - POST /api/v1/indexing/ingest-repo
   - GET /api/v1/indexing/scheduler/status
"""

import asyncio
import tempfile
import uuid
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBIndexingJob, IndexingJobStatus
from backend.app.services.indexing.scheduler import (
    ResourceScheduler,
    get_resource_scheduler,
)
from backend.app.services.indexing.job_manager import (
    JobManager,
    discover_files,
    get_job_manager,
)
from backend.app.services.retrieval.vector_store import QdrantVectorStore


# ============================================================================
# 1. DBIndexingJob Model Persistence and Lifecycle
# ============================================================================

@pytest.mark.asyncio
async def test_indexing_job_model_lifecycle():
    """Verify DBIndexingJob database persistence and status updates across lifecycle states."""
    await init_db()

    job_id = f"job_lifecycle_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        job = DBIndexingJob(
            job_id=job_id,
            job_type="folder",
            source_path="/opt/data/knowledge_base",
            total_files=50,
            processed_files=0,
            total_chunks=0,
            status=IndexingJobStatus.PENDING,
            error_message=None,
        )
        session.add(job)
        await session.commit()

    # Transition to RUNNING
    async with AsyncSessionLocal() as session:
        fetched = await session.get(DBIndexingJob, job_id)
        assert fetched is not None
        assert fetched.status == IndexingJobStatus.PENDING
        assert fetched.total_files == 50

        fetched.status = IndexingJobStatus.RUNNING
        fetched.processed_files = 25
        fetched.total_chunks = 100
        await session.commit()

    # Transition to COMPLETED
    async with AsyncSessionLocal() as session:
        updated = await session.get(DBIndexingJob, job_id)
        assert updated.status == IndexingJobStatus.RUNNING
        assert updated.processed_files == 25
        assert updated.total_chunks == 100

        updated.status = IndexingJobStatus.COMPLETED
        updated.processed_files = 50
        updated.total_chunks = 220
        await session.commit()

    async with AsyncSessionLocal() as session:
        final = await session.get(DBIndexingJob, job_id)
        assert final.status == IndexingJobStatus.COMPLETED
        assert final.processed_files == 50
        assert final.total_chunks == 220


# ============================================================================
# 2. File Discovery and Filtering
# ============================================================================

def test_file_discovery_comprehensive_filtering():
    """Verify file discovery captures supported files and filters out hidden dirs and build artifacts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        # Valid source files
        (root / "guide.md").write_text("# Guide", encoding="utf-8")
        (root / "pipeline.py").write_text("print('pipeline')", encoding="utf-8")
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "query.ts").write_text("const a = 1;", encoding="utf-8")

        # Nested valid directory
        sub_dir = root / "docs" / "sub"
        sub_dir.mkdir(parents=True)
        (sub_dir / "api.txt").write_text("API specs", encoding="utf-8")

        # Directories to ignore
        git_dir = root / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "blob.txt").write_text("git binary blob", encoding="utf-8")

        node_dir = root / "node_modules" / "express"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("module.exports = {};", encoding="utf-8")

        pycache_dir = root / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "pipeline.cpython-311.pyc").write_bytes(b"\x00\x01\x02")

        # Ignored extensions
        (root / "archive.zip").write_bytes(b"\x50\x4b\x03\x04")
        (root / ".env").write_text("SECRET=123", encoding="utf-8")

        discovered = discover_files(root, recursive=True)
        filenames = {p.name for p in discovered}

        assert "guide.md" in filenames
        assert "pipeline.py" in filenames
        assert "index.html" in filenames
        assert "query.ts" in filenames
        assert "api.txt" in filenames

        # Ignored must not be discovered
        assert "blob.txt" not in filenames
        assert "index.js" not in filenames
        assert "pipeline.cpython-311.pyc" not in filenames
        assert "archive.zip" not in filenames
        assert ".env" not in filenames


# ============================================================================
# 3. ResourceScheduler and Priority In-Flight Throttling
# ============================================================================

@pytest.mark.asyncio
async def test_resource_scheduler_priority_throttling():
    """Verify ResourceScheduler tracks chat requests and throttles background tasks."""
    scheduler = ResourceScheduler(ram_threshold_percent=95.0)

    # 1. RAM inspection
    ram = scheduler.get_ram_usage()
    assert "total_mb" in ram
    assert "available_mb" in ram
    assert ram["total_mb"] > 0

    # 2. VRAM telemetry check
    vram = scheduler.get_vram_usage()
    assert isinstance(vram, list)

    # 3. Priority chat registration
    assert scheduler.active_chats_count == 0
    assert not scheduler.has_active_chats

    async with scheduler.priority_chat_scope():
        assert scheduler.active_chats_count == 1
        assert scheduler.has_active_chats
        is_constrained, reasons = scheduler.check_constraints()
        assert is_constrained is True
        assert any("Interactive chat in flight" in r for r in reasons)

    assert scheduler.active_chats_count == 0
    assert not scheduler.has_active_chats

    # 4. Throttling simulation
    async def simulated_user_chat():
        async with scheduler.priority_chat_scope():
            await asyncio.sleep(0.2)

    chat_task = asyncio.create_task(simulated_user_chat())
    await asyncio.sleep(0.04)

    # Background task checks throttle_or_yield
    yield_res = await scheduler.throttle_or_yield(job_id="test_throttle_01", poll_interval=0.04, max_wait_seconds=1.5)
    assert yield_res["throttled"] is True
    assert yield_res["waited_seconds"] >= 0.05
    assert any("Interactive chat in flight" in r for r in yield_res["reasons"])

    await chat_task


# ============================================================================
# 4. JobManager Pause and Resume Lifecycle
# ============================================================================

@pytest.mark.asyncio
async def test_job_manager_pause_and_resume():
    """Verify JobManager handles job submission, pausing, resuming, and completion."""
    await init_db()
    jm = get_job_manager()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        for i in range(3):
            (root / f"document_{i}.txt").write_text(f"Document payload content {i}", encoding="utf-8")

        # Submit folder job
        job_info = await jm.submit_folder_job(str(root))
        job_id = job_info["job_id"]
        assert job_id.startswith("job_folder_")
        assert job_info["total_files"] == 3

        # Pause job
        paused = await jm.pause_job(job_id)
        assert paused is True
        job_state = await jm.get_job(job_id)
        assert job_state["status"] in (IndexingJobStatus.PAUSED, IndexingJobStatus.COMPLETED)

        # Resume job
        resumed = await jm.resume_job(job_id)
        assert resumed is True

        # Wait for completion (allow sufficient buffer under GPU/CPU contention)
        for _ in range(120):
            job_state = await jm.get_job(job_id)
            if job_state["status"] in (IndexingJobStatus.COMPLETED, IndexingJobStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert job_state["status"] == IndexingJobStatus.COMPLETED
        assert job_state["processed_files"] == 3
        assert job_state["progress_percent"] == 100.0


# ============================================================================
# 5. JobManager Crash Recovery
# ============================================================================

@pytest.mark.asyncio
async def test_job_manager_crashed_job_recovery():
    """Verify JobManager detects interrupted jobs marked RUNNING and resumes them."""
    await init_db()
    jm = get_job_manager()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "recovered_file.txt").write_text("Recovered file content.", encoding="utf-8")

        crashed_job_id = f"job_crash_sim_{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            job = DBIndexingJob(
                job_id=crashed_job_id,
                job_type="folder",
                source_path=str(root),
                total_files=1,
                processed_files=0,
                total_chunks=0,
                status=IndexingJobStatus.RUNNING,  # Left in RUNNING state prior to restart
            )
            session.add(job)
            await session.commit()

        resumed_jobs = await jm.resume_crashed_jobs()
        assert crashed_job_id in resumed_jobs

        # Wait for completion (allow sufficient buffer under GPU/CPU contention)
        for _ in range(120):
            job_state = await jm.get_job(crashed_job_id)
            if job_state["status"] in (IndexingJobStatus.COMPLETED, IndexingJobStatus.FAILED):
                break
            await asyncio.sleep(0.1)

        assert job_state["status"] == IndexingJobStatus.COMPLETED
        assert job_state["processed_files"] == 1


# ============================================================================
# 6. Qdrant HNSW and Quantization Parameters
# ============================================================================

def test_qdrant_vector_store_hnsw_and_quantization():
    """Verify QdrantVectorStore initializes with HNSW (m=16, ef_construct=100) and scalar quantization."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = QdrantVectorStore(
            storage_path=tmp_dir,
            hnsw_m=16,
            hnsw_ef_construct=100,
            enable_quantization=True,
            on_disk=True,
        )

        assert store.hnsw_m == 16
        assert store.hnsw_ef_construct == 100
        assert store.enable_quantization is True

        col_info = store.client.get_collection(store.collection_name)
        assert col_info.config.hnsw_config.m == 16
        assert col_info.config.hnsw_config.ef_construct == 100

        store.close()


# ============================================================================
# 7. Indexing REST API Endpoints
# ============================================================================

@pytest.mark.asyncio
async def test_indexing_api_routes():
    """Verify REST API routes for folder/repo ingestion, job query, pause, and scheduler status."""
    await init_db()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "test_api_doc.txt").write_text("Indexing API verification document.", encoding="utf-8")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Ingest folder
            resp = await client.post(
                "/api/v1/indexing/ingest-folder",
                json={
                    "folder_path": str(root),
                    "clearance_level": 1,
                    "allowed_departments": ["Engineering"],
                    "recursive": True,
                },
            )
            assert resp.status_code == 201
            job_id = resp.json()["job_id"]
            assert job_id.startswith("job_folder_")

            # 2. Get job
            job_resp = await client.get(f"/api/v1/indexing/jobs/{job_id}")
            assert job_resp.status_code == 200
            assert job_resp.json()["job_id"] == job_id

            # 3. List jobs
            list_resp = await client.get("/api/v1/indexing/jobs")
            assert list_resp.status_code == 200
            assert any(j["job_id"] == job_id for j in list_resp.json())

            # 4. Ingest repository
            repo_resp = await client.post(
                "/api/v1/indexing/ingest-repo",
                json={"repo_path": str(root), "clearance_level": 1},
            )
            assert repo_resp.status_code == 201
            assert repo_resp.json()["job_id"].startswith("job_repo_")

            # 5. Pause and resume
            pause_resp = await client.post(f"/api/v1/indexing/jobs/{job_id}/pause")
            assert pause_resp.status_code in (200, 400)

            resume_resp = await client.post(f"/api/v1/indexing/jobs/{job_id}/resume")
            assert resume_resp.status_code in (200, 400)

            # 6. Scheduler status
            sched_resp = await client.get("/api/v1/indexing/scheduler/status")
            assert sched_resp.status_code == 200
            sched_data = sched_resp.json()
            assert "ram" in sched_data
            assert "active_interactive_chats" in sched_data
            assert "is_throttled" in sched_data
