import hashlib
import json
import time
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import DBAuditLog
from backend.app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Standard 64-character zero-hash for ledger genesis block
GENESIS_HASH = "0" * 64


def build_event_data(
    log_id: str,
    timestamp: Union[datetime, str],
    user_id: str,
    action: str,
    query_hash: Optional[str] = None,
    exposed_chunk_ids: Optional[List[str]] = None,
    model_used: Optional[str] = None,
    latency_ms: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Construct canonical dictionary of event data for cryptographic serialization.
    """
    if isinstance(timestamp, datetime):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    return {
        "action": str(action),
        "exposed_chunk_ids": list(exposed_chunk_ids) if exposed_chunk_ids else [],
        "latency_ms": latency_ms if latency_ms is not None else {},
        "log_id": str(log_id),
        "model_used": str(model_used) if model_used else "",
        "query_hash": str(query_hash) if query_hash else "",
        "timestamp": ts_str,
        "user_id": str(user_id),
    }


def compute_entry_hash(prev_hash: str, event_data: Union[str, Dict[str, Any]]) -> str:
    """
    Calculates SHA-256(prev_hash + event_data) for tamper-evident chained ledger.
    """
    if isinstance(event_data, dict):
        payload = json.dumps(event_data, sort_keys=True, separators=(",", ":"))
    else:
        payload = str(event_data)

    raw_string = prev_hash + payload
    return hashlib.sha256(raw_string.encode("utf-8")).hexdigest()


async def record_audit_event(
    db: Optional[AsyncSession] = None,
    user_id: str = "anonymous",
    action: str = "query",
    query_hash: Optional[str] = None,
    exposed_chunk_ids: Optional[List[str]] = None,
    model_used: Optional[str] = None,
    latency_ms: Optional[Any] = None,
    log_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    event_data: Optional[Dict[str, Any]] = None,
    **kwargs
) -> DBAuditLog:
    """
    Record an immutable event into the cryptographically chained audit ledger.
    Calculates SHA-256(prev_hash + event_data) and persists to DBAuditLog.
    """
    async def _record(session: AsyncSession) -> DBAuditLog:
        # Retrieve the most recent ledger entry to get the previous hash
        stmt = (
            select(DBAuditLog)
            .order_by(DBAuditLog.timestamp.desc(), DBAuditLog.log_id.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        latest_entry = res.scalar_one_or_none()

        prev_hash = latest_entry.entry_hash if latest_entry else GENESIS_HASH

        actual_log_id = log_id or f"log_{int(time.time() * 1000000)}_{uuid.uuid4().hex[:8]}"
        actual_timestamp = timestamp or datetime.utcnow()
        actual_chunk_ids = exposed_chunk_ids or []
        actual_latency = latency_ms if latency_ms is not None else {}

        # Build canonical event payload
        if event_data is not None and isinstance(event_data, dict):
            payload_dict = dict(event_data)
            # Ensure key fields exist
            payload_dict.setdefault("log_id", actual_log_id)
            payload_dict.setdefault("timestamp", actual_timestamp.isoformat() if isinstance(actual_timestamp, datetime) else str(actual_timestamp))
            payload_dict.setdefault("user_id", user_id)
            payload_dict.setdefault("action", action)
            payload_dict.setdefault("query_hash", query_hash or "")
            payload_dict.setdefault("exposed_chunk_ids", actual_chunk_ids)
            payload_dict.setdefault("model_used", model_used or "")
            payload_dict.setdefault("latency_ms", actual_latency)
        else:
            payload_dict = build_event_data(
                log_id=actual_log_id,
                timestamp=actual_timestamp,
                user_id=user_id,
                action=action,
                query_hash=query_hash,
                exposed_chunk_ids=actual_chunk_ids,
                model_used=model_used,
                latency_ms=actual_latency,
            )

        entry_hash = compute_entry_hash(prev_hash, payload_dict)

        audit_entry = DBAuditLog(
            log_id=actual_log_id,
            timestamp=actual_timestamp,
            user_id=user_id,
            action=action,
            query_hash=query_hash,
            exposed_chunk_ids=actual_chunk_ids,
            model_used=model_used,
            latency_ms=actual_latency,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

        session.add(audit_entry)
        await session.commit()
        await session.refresh(audit_entry)
        return audit_entry

    if db is not None:
        return await _record(db)
    else:
        async with AsyncSessionLocal() as session:
            return await _record(session)


async def verify_audit_integrity(db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """
    Verify the cryptographic integrity of all entries in the ledger to detect any post-facto tampering.
    Validates both:
    1. Parent-child chaining: entry[i].prev_hash == entry[i-1].entry_hash
    2. Event content integrity: entry[i].entry_hash == SHA-256(prev_hash + event_data)
    """
    async def _verify(session: AsyncSession) -> Dict[str, Any]:
        stmt = select(DBAuditLog).order_by(DBAuditLog.timestamp.asc(), DBAuditLog.log_id.asc())
        res = await session.execute(stmt)
        entries = res.scalars().all()

        total_records = len(entries)
        tampered_records: List[Dict[str, Any]] = []

        if total_records == 0:
            return {
                "is_valid": True,
                "total_records": 0,
                "tampered_records": [],
                "verified_at": datetime.utcnow(),
                "message": "Audit ledger is empty. Cryptographic integrity intact.",
            }

        expected_prev_hash = GENESIS_HASH

        for idx, entry in enumerate(entries):
            issue = None

            # 1. Check prev_hash linkage
            if entry.prev_hash != expected_prev_hash:
                issue = {
                    "log_id": entry.log_id,
                    "index": idx,
                    "reason": "Broken cryptographic chain link (prev_hash mismatch)",
                    "expected_prev_hash": expected_prev_hash,
                    "actual_prev_hash": entry.prev_hash,
                }

            # 2. Reconstruct event payload and verify hash
            payload = build_event_data(
                log_id=entry.log_id,
                timestamp=entry.timestamp,
                user_id=entry.user_id,
                action=entry.action,
                query_hash=entry.query_hash,
                exposed_chunk_ids=entry.exposed_chunk_ids,
                model_used=entry.model_used,
                latency_ms=entry.latency_ms,
            )
            recalculated_hash = compute_entry_hash(entry.prev_hash, payload)

            if recalculated_hash != entry.entry_hash:
                if issue is None:
                    issue = {
                        "log_id": entry.log_id,
                        "index": idx,
                        "reason": "Tampered entry content (hash recalculation mismatch)",
                        "expected_hash": recalculated_hash,
                        "actual_hash": entry.entry_hash,
                    }
                else:
                    issue["content_tampered"] = True
                    issue["recalculated_hash"] = recalculated_hash

            if issue:
                tampered_records.append(issue)

            # Advance expected_prev_hash to current entry's recorded hash
            expected_prev_hash = entry.entry_hash

        is_valid = len(tampered_records) == 0
        summary_msg = (
            f"Audit ledger integrity verified. All {total_records} records chained successfully."
            if is_valid
            else f"Cryptographic integrity violation detected! {len(tampered_records)} of {total_records} records tampered."
        )

        return {
            "is_valid": is_valid,
            "total_records": total_records,
            "tampered_records": tampered_records,
            "verified_at": datetime.utcnow(),
            "message": summary_msg,
        }

    if db is not None:
        return await _verify(db)
    else:
        async with AsyncSessionLocal() as session:
            return await _verify(session)


class AuditLedger:
    """Cryptographically chained audit ledger service manager."""

    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session

    async def record_event(self, **kwargs) -> DBAuditLog:
        return await record_audit_event(db=self.db, **kwargs)

    async def verify_integrity(self) -> Dict[str, Any]:
        return await verify_audit_integrity(db=self.db)

    async def get_logs(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[DBAuditLog]:
        async def _query(session: AsyncSession) -> List[DBAuditLog]:
            stmt = select(DBAuditLog)
            if user_id:
                stmt = stmt.where(DBAuditLog.user_id == user_id)
            if action:
                stmt = stmt.where(DBAuditLog.action == action)
            stmt = stmt.order_by(DBAuditLog.timestamp.desc(), DBAuditLog.log_id.desc()).offset(offset).limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

        if self.db is not None:
            return await _query(self.db)
        else:
            async with AsyncSessionLocal() as session:
                return await _query(session)

