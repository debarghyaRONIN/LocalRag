from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.session import get_db
from backend.app.db.models import DBAuditLog
from backend.app.domain.models import AuditLogEntry, AuditIntegrityReport
from backend.app.services.compliance.audit_ledger import verify_audit_integrity

router = APIRouter()


@router.get("/compliance/audit-logs", response_model=List[AuditLogEntry])
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=1000, description="Max entries to return"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    user_id: Optional[str] = Query(None, description="Filter logs by user ID"),
    action: Optional[str] = Query(None, description="Filter logs by action name"),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve cryptographically chained audit log records.
    Ordered in reverse-chronological order (newest first).
    """
    stmt = select(DBAuditLog)
    if user_id:
        stmt = stmt.where(DBAuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(DBAuditLog.action == action)

    stmt = stmt.order_by(DBAuditLog.timestamp.desc(), DBAuditLog.log_id.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    entries = res.scalars().all()

    return [
        AuditLogEntry(
            log_id=e.log_id,
            timestamp=e.timestamp,
            user_id=e.user_id,
            action=e.action,
            query_hash=e.query_hash,
            exposed_chunk_ids=e.exposed_chunk_ids or [],
            model_used=e.model_used,
            latency_ms=e.latency_ms,
            prev_hash=e.prev_hash,
            entry_hash=e.entry_hash,
        )
        for e in entries
    ]


@router.get("/compliance/verify-integrity", response_model=AuditIntegrityReport)
async def verify_integrity(db: AsyncSession = Depends(get_db)):
    """
    Cryptographic verification endpoint for audit trail integrity.
    Iterates sequentially through the entire blockchain/hash chain,
    verifying both SHA-256(prev_hash + event_data) and parent-child hash links.
    Returns whether the ledger is untampered, along with details of any discrepancies.
    """
    report = await verify_audit_integrity(db=db)
    return AuditIntegrityReport(
        is_valid=report["is_valid"],
        total_records=report["total_records"],
        tampered_records=report["tampered_records"],
        verified_at=report["verified_at"],
        message=report["message"],
    )

