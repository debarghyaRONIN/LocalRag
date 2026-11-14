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


@pytest.mark.asyncio
async def test_db_indexing_job_model():
    """Verify DBIndexingJob model persistence, default attributes, and queries."""
    await init_db()

    job_id = f"job_test_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        job = DBIndexingJob(
            job_id=job_id,
            job_type="folder",
            source_path="/test/path/data",
            total_files=42,
            processed_files=10,
            total_chunks=150,
            status=IndexingJobStatus.RUNNING,
            error_message=None,
        )
        session.add(job)
        await session.commit()

    async with AsyncSessionLocal() as session:
        saved = await session.get(DBIndexingJob, job_id)
        assert saved is not None
        assert saved.job_id == job_id
        assert saved.job_type == "folder"
        assert saved.total_files == 42
        assert saved.processed_files == 10
        assert saved.total_chunks == 150
        assert saved.status == IndexingJobStatus.RUNNING
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Test status update
        saved.status = IndexingJobStatus.PAUSED
        await session.commit()

    async with AsyncSessionLocal() as session:
        updated = await session.get(DBIndexingJob, job_id)
        assert updated.status == IndexingJobStatus.PAUSED


@pytest.mark.asyncio
async def test_resource_scheduler_monitoring_and_priority():
    """Verify system RAM/VRAM inspection and priority scheduling for in-flight chat."""
    scheduler = ResourceScheduler()

    # 1. RAM inspection
    ram = scheduler.get_ram_usage()
    assert "total_mb" in ram
    assert "available_mb" in ram
    assert "percent" in ram
    assert ram["total_mb"] > 0

    # 2. VRAM inspection (safe fallback if no GPU)
    vram = scheduler.get_vram_usage()
    assert isinstance(vram, list)

    # 3. Priority chat registration and context manager
    assert not scheduler.has_active_chats
    assert scheduler.active_chats_count == 0

    async with scheduler.priority_chat_scope():
        assert scheduler.has_active_chats
        assert scheduler.active_chats_count == 1
        is_constrained, reasons = scheduler.check_constraints()
        assert is_constrained is True
        assert any("Interactive chat in flight" in r for r in reasons)

    assert not scheduler.has_active_chats
    assert scheduler.active_chats_count == 0

    # 4. Throttling check when active chat is running
    async def chat_simulator():
        async with scheduler.priority_chat_scope():
            await asyncio.sleep(0.3)

    chat_task = asyncio.create_task(chat_simulator())
    await asyncio.sleep(0.05)  # Let chat task acquire lock

    # Background task throttle_or_yield should detect active chat and wait
    result = await scheduler.throttle_or_yield(job_id="test_throttle_job", poll_interval=0.05, max_wait_seconds=2.0)
    assert result["throttled"] is True
    assert any("Interactive chat in flight" in r for r in result["reasons"])
    assert result["waited_seconds"] >= 0.1

    await chat_task


def test_file_discovery_filtering():
    """Verify that file discovery respects supported extensions and ignores hidden/build dirs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        # Create valid files
        (root / "doc1.txt").write_text("hello text")
        (root / "main.py").write_text("print('hello')")
        (root / "README.md").write_text("# Readme")

        # Create ignored dirs and files
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "config.txt").write_text("git config")

        pycache_dir = root / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "main.cpython-311.pyc").write_text("compiled bytecode")

        node_dir = root / "node_modules" / "some_pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "index.js").write_text("console.log()")

        # Create ignored extensions
        (root / "binary.bin").write_bytes(b"\x00\x01\x02")
        (root / ".hidden_file.txt").write_text("hidden")

        discovered = discover_files(root, recursive=True)
        filenames = [p.name for p in discovered]

        assert "doc1.txt" in filenames
        assert "main.py" in filenames
        assert "README.md" in filenames
        assert "config.txt" not in filenames
        assert "main.cpython-311.pyc" not in filenames
        assert "index.js" not in filenames
        assert "binary.bin" not in filenames
        assert ".hidden_file.txt" not in filenames


def test_qdrant_vector_store_hnsw_and_quantization_config():
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
        quant_config = getattr(col_info.config.params.vectors, "quantization_config", None) or col_info.config.quantization_config
        assert quant_config is not None

        store.close()


@pytest.mark.asyncio
async def test_job_manager_pause_resume_lifecycle():
    """Verify JobManager pause, resume, and progress tracking."""
    await init_db()
    jm = get_job_manager()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        for i in range(3):
            (root / f"file_{i}.txt").write_text(f"Sample content for indexing file {i}")

        # Submit folder job
        job_info = await jm.submit_folder_job(str(root))
        job_id = job_info["job_id"]
        assert job_id.startswith("job_folder_")
        assert job_info["total_files"] == 3

        # Test pause
        paused = await jm.pause_job(job_id)
        assert paused is True
        job_state = await jm.get_job(job_id)
        assert job_state["status"] in [IndexingJobStatus.PAUSED, IndexingJobStatus.COMPLETED]

        # Test resume
        resumed = await jm.resume_job(job_id)
        assert resumed is True

        # Wait for completion (allow sufficient buffer under GPU/CPU contention)
        for _ in range(120):
            job_state = await jm.get_job(job_id)
            if job_state["status"] in [IndexingJobStatus.COMPLETED, IndexingJobStatus.FAILED]:
                break
            await asyncio.sleep(0.1)

        assert job_state["status"] == IndexingJobStatus.COMPLETED
        assert job_state["processed_files"] == 3
        assert job_state["progress_percent"] == 100.0


@pytest.mark.asyncio
async def test_job_manager_crash_recovery():
    """Verify JobManager detects and resumes crashed jobs marked RUNNING in database."""
    await init_db()
    jm = get_job_manager()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "doc_crash.txt").write_text("Crash recovery test content")

        crashed_id = f"job_crash_{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as session:
            job = DBIndexingJob(
                job_id=crashed_id,
                job_type="folder",
                source_path=str(root),
                total_files=1,
                processed_files=0,
                total_chunks=0,
                status=IndexingJobStatus.RUNNING,  # Left in RUNNING state upon unexpected server shutdown
            )
            session.add(job)
            await session.commit()

        # Execute crash recovery
        resumed = await jm.resume_crashed_jobs()
        assert crashed_id in resumed

        # Wait for resumed job to finish (allow sufficient buffer under GPU/CPU contention)
        for _ in range(120):
            job_state = await jm.get_job(crashed_id)
            if job_state["status"] in [IndexingJobStatus.COMPLETED, IndexingJobStatus.FAILED]:
                break
            await asyncio.sleep(0.1)

        assert job_state["status"] == IndexingJobStatus.COMPLETED
        assert job_state["processed_files"] == 1


@pytest.mark.asyncio
async def test_indexing_api_endpoints():
    """Verify REST API routes for folder ingestion, repo ingestion, pause, resume, and job status."""
    await init_db()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "sample_api_test.txt").write_text("API test content for indexing verification")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Ingest folder
            resp = await client.post(
                "/api/v1/indexing/ingest-folder",
                json={
                    "folder_path": str(root),
                    "clearance_level": 2,
                    "allowed_departments": ["Engineering"],
                    "recursive": True,
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            job_id = data["job_id"]
            assert job_id.startswith("job_folder_")
            assert data["total_files"] == 1

            # 2. Get job status
            job_resp = await client.get(f"/api/v1/indexing/jobs/{job_id}")
            assert job_resp.status_code == 200
            assert job_resp.json()["job_id"] == job_id

            # 3. List jobs
            list_resp = await client.get("/api/v1/indexing/jobs")
            assert list_resp.status_code == 200
            jobs = list_resp.json()
            assert any(j["job_id"] == job_id for j in jobs)

            # 4. Ingest repository endpoint
            repo_resp = await client.post(
                "/api/v1/indexing/ingest-repo",
                json={
                    "repo_path": str(root),
                    "clearance_level": 1,
                },
            )
            assert repo_resp.status_code == 201
            repo_data = repo_resp.json()
            assert repo_data["job_id"].startswith("job_repo_")

            # 5. Pause and resume endpoints
            pause_resp = await client.post(f"/api/v1/indexing/jobs/{job_id}/pause")
            assert pause_resp.status_code in [200, 400]

            resume_resp = await client.post(f"/api/v1/indexing/jobs/{job_id}/resume")
            assert resume_resp.status_code in [200, 400]

            # 6. Scheduler status endpoint
            sched_resp = await client.get("/api/v1/indexing/scheduler/status")
            assert sched_resp.status_code == 200
            sched_data = sched_resp.json()
            assert "ram" in sched_data
            assert "active_interactive_chats" in sched_data
            assert "is_throttled" in sched_data
