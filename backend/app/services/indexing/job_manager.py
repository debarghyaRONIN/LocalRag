import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import AsyncSessionLocal
from backend.app.db.models import DBIndexingJob, IndexingJobStatus
from backend.app.services.indexing.scheduler import ResourceScheduler, get_resource_scheduler
from backend.app.services.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Set[str] = {
    ".pdf", ".docx", ".txt", ".md", ".json", ".csv", ".html", ".htm",
    ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".cpp", ".c", ".h", ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1",
    ".yaml", ".yml", ".toml", ".sql",
}

IGNORED_DIRECTORIES: Set[str] = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv",
    "venv", "env", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", ".config", "data", "target", "out",
}


def discover_files(root_path: Path, recursive: bool = True) -> List[Path]:
    """
    Discover all indexable document and code files within a target path,
    skipping hidden directories, build artifacts, dependency dirs, and binary files.
    """
    discovered: List[Path] = []
    if not root_path.exists():
        return discovered

    if root_path.is_file():
        if root_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            discovered.append(root_path)
        return discovered

    iterator = root_path.rglob("*") if recursive else root_path.glob("*")
    for p in iterator:
        try:
            if not p.is_file():
                continue
            # Check if any parent part is in IGNORED_DIRECTORIES or starts with '.'
            parts = p.relative_to(root_path).parts
            if any(part in IGNORED_DIRECTORIES for part in parts[:-1]):
                continue
            if any(part.startswith(".") and part != "." for part in parts[:-1]):
                continue
            if p.name.startswith("."):
                continue
            if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                discovered.append(p)
        except Exception:
            continue

    discovered.sort()
    return discovered


class JobControl:
    """In-memory synchronization and control primitives for an active indexing job."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # set = running, clear = paused
        self.cancel_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.is_paused: bool = False
        self.is_cancelled: bool = False


class JobManager:
    """
    Job Queue Manager for large-scale knowledge engine indexing (1M-10M chunks).
    Features:
    - Async concurrency controls via Semaphore to limit simultaneous indexing tasks.
    - Persistent job progress tracked in DB (files & chunks).
    - Resource-aware priority yielding during active chat sessions via ResourceScheduler.
    - Crash recovery: detects and resumes interrupted/crashed jobs on startup.
    - Cooperative pause and resume capabilities.
    """

    _instance: Optional["JobManager"] = None

    def __init__(
        self,
        max_concurrency: int = 2,
        pipeline: Optional[IngestionPipeline] = None,
        scheduler: Optional[ResourceScheduler] = None,
    ):
        self.max_concurrency = max_concurrency
        self.pipeline = pipeline or IngestionPipeline()
        self.scheduler = scheduler or get_resource_scheduler()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._jobs: Dict[str, JobControl] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "JobManager":
        if cls._instance is None:
            cls._instance = JobManager()
        return cls._instance

    def _get_or_create_control(self, job_id: str) -> JobControl:
        if job_id not in self._jobs:
            self._jobs[job_id] = JobControl(job_id)
        return self._jobs[job_id]

    # ---------------------------------------------------------
    # Job Submission (Folder & Repo)
    # ---------------------------------------------------------
    async def submit_folder_job(
        self,
        folder_path: str,
        clearance_level: int = 1,
        allowed_departments: Optional[List[str]] = None,
        recursive: bool = True,
    ) -> Dict[str, Any]:
        """Submit a directory folder for background ingestion and indexing."""
        resolved_path = Path(folder_path).resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Folder path does not exist: {folder_path}")

        files = discover_files(resolved_path, recursive=recursive)
        job_id = f"job_folder_{uuid.uuid4().hex[:12]}"

        async with AsyncSessionLocal() as session:
            job = DBIndexingJob(
                job_id=job_id,
                job_type="folder",
                source_path=str(resolved_path),
                total_files=len(files),
                processed_files=0,
                total_chunks=0,
                status=IndexingJobStatus.PENDING,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(job)
            await session.commit()

        ctrl = self._get_or_create_control(job_id)
        task = asyncio.create_task(
            self._run_job_with_semaphore(
                job_id=job_id,
                files=files,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments or [],
            )
        )
        ctrl.task = task

        return await self.get_job(job_id)

    async def submit_repo_job(
        self,
        repo_path: str,
        clearance_level: int = 1,
        allowed_departments: Optional[List[str]] = None,
        branch_or_commit: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a code repository for structural AST and code-aware ingestion."""
        resolved_path = Path(repo_path).resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        files = discover_files(resolved_path, recursive=True)
        job_id = f"job_repo_{uuid.uuid4().hex[:12]}"

        async with AsyncSessionLocal() as session:
            job = DBIndexingJob(
                job_id=job_id,
                job_type="repo",
                source_path=str(resolved_path),
                total_files=len(files),
                processed_files=0,
                total_chunks=0,
                status=IndexingJobStatus.PENDING,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(job)
            await session.commit()

        ctrl = self._get_or_create_control(job_id)
        task = asyncio.create_task(
            self._run_job_with_semaphore(
                job_id=job_id,
                files=files,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments or [],
            )
        )
        ctrl.task = task

        return await self.get_job(job_id)

    # ---------------------------------------------------------
    # Concurrency and Worker Execution
    # ---------------------------------------------------------
    async def _run_job_with_semaphore(
        self,
        job_id: str,
        files: List[Path],
        clearance_level: int,
        allowed_departments: List[str],
    ):
        """Worker wrapper enforcing max concurrency bounds."""
        async with self._semaphore:
            await self._execute_job(
                job_id=job_id,
                files=files,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments,
            )

    async def _execute_job(
        self,
        job_id: str,
        files: List[Path],
        clearance_level: int,
        allowed_departments: List[str],
    ):
        """Main indexing execution loop with checkpointing, pause/resume, and resource throttling."""
        ctrl = self._get_or_create_control(job_id)

        # Update status to RUNNING if not paused
        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if not job:
                return
            if job.status != IndexingJobStatus.PAUSED:
                job.status = IndexingJobStatus.RUNNING
                job.updated_at = datetime.utcnow()
                await session.commit()

        processed_count = 0
        total_chunks = 0

        # Retrieve already processed counts if resuming
        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if job:
                processed_count = job.processed_files
                total_chunks = job.total_chunks

        # If resuming, slice files from current processed_count
        pending_files = files[processed_count:] if processed_count < len(files) else []

        try:
            for file_path in pending_files:
                # 1. Check if paused
                if not ctrl.pause_event.is_set():
                    logger.info(f"[JobManager] Job {job_id} paused at file {processed_count}/{len(files)}")
                    async with AsyncSessionLocal() as session:
                        job = await session.get(DBIndexingJob, job_id)
                        if job:
                            job.status = IndexingJobStatus.PAUSED
                            job.updated_at = datetime.utcnow()
                            await session.commit()
                    # Await resume signal
                    await ctrl.pause_event.wait()

                # Check if cancelled
                if ctrl.is_cancelled:
                    logger.info(f"[JobManager] Job {job_id} cancelled")
                    return

                # 2. Resource scheduler throttle/yield check (prioritize chat generation)
                await self.scheduler.throttle_or_yield(job_id=job_id)

                # 3. Ingest single file
                chunks_added = 0
                try:
                    async with AsyncSessionLocal() as session:
                        doc_meta = await self.pipeline.ingest_file(
                            file_path=file_path,
                            db_session=session,
                            filename=file_path.name,
                            clearance_level=clearance_level,
                            allowed_departments=allowed_departments,
                        )
                        chunks_added = doc_meta.total_child_chunks
                except Exception as e:
                    logger.warning(f"[JobManager] Failed to ingest {file_path.name} in job {job_id}: {e}")

                processed_count += 1
                total_chunks += chunks_added

                # 4. Checkpoint progress in DB
                async with AsyncSessionLocal() as session:
                    job = await session.get(DBIndexingJob, job_id)
                    if job:
                        job.processed_files = processed_count
                        job.total_chunks = total_chunks
                        job.updated_at = datetime.utcnow()
                        await session.commit()

            # Mark completed
            async with AsyncSessionLocal() as session:
                job = await session.get(DBIndexingJob, job_id)
                if job and job.status != IndexingJobStatus.PAUSED and not ctrl.is_cancelled:
                    job.status = IndexingJobStatus.COMPLETED
                    job.processed_files = len(files)
                    job.total_chunks = total_chunks
                    job.updated_at = datetime.utcnow()
                    await session.commit()
                    logger.info(f"[JobManager] Job {job_id} completed successfully ({processed_count} files, {total_chunks} chunks)")

        except asyncio.CancelledError:
            logger.info(f"[JobManager] Job {job_id} task was cancelled")
            async with AsyncSessionLocal() as session:
                job = await session.get(DBIndexingJob, job_id)
                if job:
                    job.status = IndexingJobStatus.PAUSED
                    job.updated_at = datetime.utcnow()
                    await session.commit()
            raise

        except Exception as e:
            logger.error(f"[JobManager] Job {job_id} failed with error: {e}", exc_info=True)
            async with AsyncSessionLocal() as session:
                job = await session.get(DBIndexingJob, job_id)
                if job:
                    job.status = IndexingJobStatus.FAILED
                    job.error_message = str(e)
                    job.updated_at = datetime.utcnow()
                    await session.commit()

    # ---------------------------------------------------------
    # Pause and Resume Capabilities
    # ---------------------------------------------------------
    async def pause_job(self, job_id: str) -> bool:
        """Pause a running or pending indexing job."""
        ctrl = self._jobs.get(job_id)
        if ctrl:
            ctrl.pause_event.clear()
            ctrl.is_paused = True

        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if not job:
                return False
            if job.status in [IndexingJobStatus.RUNNING, IndexingJobStatus.PENDING]:
                job.status = IndexingJobStatus.PAUSED
                job.updated_at = datetime.utcnow()
                await session.commit()
                return True
            elif job.status == IndexingJobStatus.PAUSED:
                return True
            return False

    async def resume_job(self, job_id: str) -> bool:
        """
        Resume a paused or interrupted indexing job.
        If the in-memory task is already waiting, signals it.
        Otherwise (e.g. after restart or crash), re-spawns background execution.
        """
        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if not job:
                return False
            if job.status not in [IndexingJobStatus.PAUSED, IndexingJobStatus.PENDING, IndexingJobStatus.RUNNING]:
                return False

        ctrl = self._jobs.get(job_id)
        if ctrl and ctrl.task and not ctrl.task.done():
            # In-memory paused task exists, simply signal resume
            ctrl.is_paused = False
            ctrl.pause_event.set()
            async with AsyncSessionLocal() as session:
                job = await session.get(DBIndexingJob, job_id)
                if job:
                    job.status = IndexingJobStatus.RUNNING
                    job.updated_at = datetime.utcnow()
                    await session.commit()
            return True

        # Job needs re-launching (e.g. after crash or server restart)
        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if not job:
                return False
            source_path = Path(job.source_path)
            if not source_path.exists():
                job.status = IndexingJobStatus.FAILED
                job.error_message = f"Source path no longer exists: {job.source_path}"
                job.updated_at = datetime.utcnow()
                await session.commit()
                return False

            job.status = IndexingJobStatus.RUNNING
            job.updated_at = datetime.utcnow()
            await session.commit()

        files = discover_files(source_path, recursive=True)
        new_ctrl = self._get_or_create_control(job_id)
        new_ctrl.is_paused = False
        new_ctrl.pause_event.set()
        task = asyncio.create_task(
            self._run_job_with_semaphore(
                job_id=job_id,
                files=files,
                clearance_level=1,
                allowed_departments=[],
            )
        )
        new_ctrl.task = task
        return True

    # ---------------------------------------------------------
    # Crash Recovery
    # ---------------------------------------------------------
    async def resume_crashed_jobs(self) -> List[str]:
        """
        Scan database for jobs marked as RUNNING from an earlier session/crash.
        Automatically resumes their execution.
        """
        resumed_ids: List[str] = []
        async with AsyncSessionLocal() as session:
            stmt = select(DBIndexingJob).where(DBIndexingJob.status == IndexingJobStatus.RUNNING)
            res = await session.execute(stmt)
            crashed_jobs = res.scalars().all()

            for job in crashed_jobs:
                resumed_ids.append(job.job_id)

        for jid in resumed_ids:
            logger.info(f"[JobManager] Recovering and resuming crashed indexing job: {jid}")
            await self.resume_job(jid)

        return resumed_ids

    # ---------------------------------------------------------
    # Status and Queries
    # ---------------------------------------------------------
    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve current metadata and progress for a single job."""
        async with AsyncSessionLocal() as session:
            job = await session.get(DBIndexingJob, job_id)
            if not job:
                return None

            progress = 0.0
            if job.total_files > 0:
                progress = round((job.processed_files / job.total_files) * 100.0, 1)

            return {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "source_path": job.source_path,
                "total_files": job.total_files,
                "processed_files": job.processed_files,
                "total_chunks": job.total_chunks,
                "status": job.status,
                "error_message": job.error_message,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "progress_percent": progress,
            }

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List indexing jobs with optional status filter and pagination."""
        async with AsyncSessionLocal() as session:
            stmt = select(DBIndexingJob)
            if status:
                stmt = stmt.where(DBIndexingJob.status == status)

            stmt = stmt.order_by(DBIndexingJob.created_at.desc()).offset(offset).limit(limit)
            res = await session.execute(stmt)
            jobs = res.scalars().all()

            results = []
            for job in jobs:
                progress = 0.0
                if job.total_files > 0:
                    progress = round((job.processed_files / job.total_files) * 100.0, 1)

                results.append({
                    "job_id": job.job_id,
                    "job_type": job.job_type,
                    "source_path": job.source_path,
                    "total_files": job.total_files,
                    "processed_files": job.processed_files,
                    "total_chunks": job.total_chunks,
                    "status": job.status,
                    "error_message": job.error_message,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "progress_percent": progress,
                })

            return results


def get_job_manager() -> JobManager:
    return JobManager.get_instance()
