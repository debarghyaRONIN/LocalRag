import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, status

from backend.app.domain.models import (
    IndexingJobResponse,
    IngestFolderRequest,
    IngestRepoRequest,
)
from backend.app.services.indexing.job_manager import get_job_manager
from backend.app.services.indexing.scheduler import get_resource_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/indexing/jobs", response_model=List[IndexingJobResponse])
async def list_indexing_jobs(
    status: Optional[str] = Query(None, description="Filter jobs by status (pending, running, paused, completed, failed)"),
    limit: int = Query(50, ge=1, le=500, description="Max jobs to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    List all background indexing jobs with real-time file and chunk progress.
    Supports status filtering and pagination.
    """
    jm = get_job_manager()
    jobs = await jm.list_jobs(status=status, limit=limit, offset=offset)
    return jobs


@router.get("/indexing/jobs/{job_id}", response_model=IndexingJobResponse)
async def get_indexing_job(job_id: str):
    """Get status, processed files, and total indexed chunks for a specific job."""
    jm = get_job_manager()
    job = await jm.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Indexing job '{job_id}' not found")
    return job


@router.post("/indexing/jobs/{job_id}/pause")
async def pause_indexing_job(job_id: str):
    """
    Pause an active or pending indexing job.
    The worker checkpoint saves progress and cleanly yields resources.
    """
    jm = get_job_manager()
    success = await jm.pause_job(job_id)
    if not success:
        job = await jm.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Indexing job '{job_id}' not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause job '{job_id}' with status '{job.get('status')}'",
        )
    return {"status": "success", "job_id": job_id, "message": "Indexing job paused successfully"}


@router.post("/indexing/jobs/{job_id}/resume")
async def resume_indexing_job(job_id: str):
    """
    Resume a paused or interrupted indexing job.
    Picks up from the last checkpoint without re-processing already ingested files.
    """
    jm = get_job_manager()
    success = await jm.resume_job(job_id)
    if not success:
        job = await jm.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Indexing job '{job_id}' not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume job '{job_id}' with status '{job.get('status')}'",
        )
    return {"status": "success", "job_id": job_id, "message": "Indexing job resumed successfully"}


@router.post("/indexing/ingest-folder", response_model=IndexingJobResponse, status_code=status.HTTP_201_CREATED)
async def ingest_folder(payload: IngestFolderRequest):
    """
    Submit a folder of documents or code files for asynchronous indexing into Qdrant & SQLite.
    Files are discovered, chunked hierarchically, and indexed with resource-aware throttling.
    """
    jm = get_job_manager()
    try:
        job_info = await jm.submit_folder_job(
            folder_path=payload.folder_path,
            clearance_level=payload.clearance_level,
            allowed_departments=payload.allowed_departments,
            recursive=payload.recursive,
        )
        return job_info
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit folder ingest job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit folder indexing job: {str(e)}")


@router.post("/indexing/ingest-repo", response_model=IndexingJobResponse, status_code=status.HTTP_201_CREATED)
async def ingest_repository(payload: IngestRepoRequest):
    """
    Submit an entire software repository for structural code-aware indexing.
    Preserves structural AST hierarchy and line numbers.
    """
    jm = get_job_manager()
    try:
        job_info = await jm.submit_repo_job(
            repo_path=payload.repo_path,
            clearance_level=payload.clearance_level,
            allowed_departments=payload.allowed_departments,
            branch_or_commit=payload.branch_or_commit,
        )
        return job_info
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit repo ingest job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit repo indexing job: {str(e)}")


@router.get("/indexing/scheduler/status")
async def get_scheduler_status() -> Dict[str, Any]:
    """
    Inspect the resource scheduler: system RAM, GPU VRAM, active chat generations,
    and whether background embedding is currently being throttled.
    """
    scheduler = get_resource_scheduler()
    return scheduler.get_system_metrics()
