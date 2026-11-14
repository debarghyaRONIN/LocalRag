import hashlib
import json
import uuid
from datetime import datetime, timedelta
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBAuditLog
from backend.app.services.compliance.audit_ledger import (
    record_audit_event,
    verify_audit_integrity,
    compute_entry_hash,
    build_event_data,
    GENESIS_HASH,
    AuditLedger,
)


@pytest.mark.asyncio
async def test_genesis_hash_and_hash_computation():
    """Verify genesis hash format and deterministic SHA-256 calculation."""
    assert len(GENESIS_HASH) == 64
    assert GENESIS_HASH == "0" * 64

    payload = {
        "action": "query",
        "exposed_chunk_ids": ["c1", "c2"],
        "latency_ms": {"total_ms": 12.3},
        "log_id": "log_test_001",
        "model_used": "local-llm",
        "query_hash": "sha256_dummy_hash",
        "timestamp": "2026-11-13T12:00:00",
        "user_id": "test_analyst",
    }
    hash_1 = compute_entry_hash(GENESIS_HASH, payload)
    hash_2 = compute_entry_hash(GENESIS_HASH, payload)

    assert len(hash_1) == 64
    assert hash_1 == hash_2

    # Changing any field must alter the resulting hash
    modified_payload = dict(payload)
    modified_payload["action"] = "admin_export"
    hash_modified = compute_entry_hash(GENESIS_HASH, modified_payload)
    assert hash_modified != hash_1


@pytest.mark.asyncio
async def test_audit_ledger_sequential_chain_integrity():
    """Verify SHA-256 parent-child hash chaining across multiple sequential events."""
    await init_db()

    user_a = f"analyst_{uuid.uuid4().hex[:6]}"
    user_b = f"officer_{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as session:
        # Record event 1
        e1 = await record_audit_event(
            db=session,
            user_id=user_a,
            action="document_ingest",
            query_hash="hash_alpha",
            exposed_chunk_ids=["chunk_1", "chunk_2"],
            model_used="bge-small-en-v1.5",
            latency_ms={"ingest_ms": 45.0},
        )
        assert e1.log_id.startswith("log_")
        assert len(e1.entry_hash) == 64
        assert len(e1.prev_hash) == 64

        # Record event 2
        e2 = await record_audit_event(
            db=session,
            user_id=user_b,
            action="vector_search",
            query_hash="hash_beta",
            exposed_chunk_ids=["chunk_3"],
            model_used="qwen-2.5-7b",
            latency_ms={"retrieval_ms": 12.5},
        )
        assert e2.prev_hash == e1.entry_hash
        assert len(e2.entry_hash) == 64

        # Record event 3
        e3 = await record_audit_event(
            db=session,
            user_id=user_a,
            action="inference_generation",
            query_hash="hash_gamma",
            exposed_chunk_ids=["chunk_1", "chunk_3"],
            model_used="qwen-2.5-7b",
            latency_ms={"generation_ms": 88.0},
        )
        assert e3.prev_hash == e2.entry_hash
        assert len(e3.entry_hash) == 64

        # Verify integrity of complete chain
        report = await verify_audit_integrity(db=session)
        assert report["is_valid"] is True
        assert report["total_records"] >= 3
        assert len(report["tampered_records"]) == 0


@pytest.mark.asyncio
async def test_audit_ledger_tamper_detection_content_modification():
    """Verify that tampering with an audit record's content is immediately detected."""
    await init_db()

    async with AsyncSessionLocal() as session:
        user_x = f"suspect_{uuid.uuid4().hex[:6]}"
        entry = await record_audit_event(
            db=session,
            user_id=user_x,
            action="classified_access",
            query_hash="q_secret_123",
            exposed_chunk_ids=["top_secret_chunk_999"],
            model_used="secure_llm",
        )

        # Baseline: integrity must be valid
        report_initial = await verify_audit_integrity(db=session)
        assert report_initial["is_valid"] is True

        # Tamper 1: modify action
        original_action = entry.action
        entry.action = "public_general_inquiry"
        await session.commit()

        report_tampered = await verify_audit_integrity(db=session)
        assert report_tampered["is_valid"] is False
        assert any(t["log_id"] == entry.log_id for t in report_tampered["tampered_records"])

        # Revert modification
        entry.action = original_action
        await session.commit()

        report_restored = await verify_audit_integrity(db=session)
        assert report_restored["is_valid"] is True

        # Tamper 2: modify exposed_chunk_ids
        entry.exposed_chunk_ids = ["fake_chunk"]
        await session.commit()

        report_tampered_chunks = await verify_audit_integrity(db=session)
        assert report_tampered_chunks["is_valid"] is False
        assert any(t["log_id"] == entry.log_id for t in report_tampered_chunks["tampered_records"])

        # Revert modification
        entry.exposed_chunk_ids = ["top_secret_chunk_999"]
        await session.commit()
        report_clean = await verify_audit_integrity(db=session)
        assert report_clean["is_valid"] is True


@pytest.mark.asyncio
async def test_audit_ledger_tamper_detection_chain_break():
    """Verify that breaking the hash chain (forging prev_hash) is caught."""
    await init_db()

    async with AsyncSessionLocal() as session:
        user_y = f"break_chain_{uuid.uuid4().hex[:6]}"
        e1 = await record_audit_event(
            db=session,
            user_id=user_y,
            action="test_action_1",
            query_hash="hash_1",
        )
        e2 = await record_audit_event(
            db=session,
            user_id=user_y,
            action="test_action_2",
            query_hash="hash_2",
        )

        # Forge prev_hash on e2
        original_prev_hash = e2.prev_hash
        e2.prev_hash = "f" * 64
        await session.commit()

        report = await verify_audit_integrity(db=session)
        assert report["is_valid"] is False
        assert any("prev_hash mismatch" in str(t.get("reason", "")) for t in report["tampered_records"])

        # Revert
        e2.prev_hash = original_prev_hash
        await session.commit()
        report_ok = await verify_audit_integrity(db=session)
        assert report_ok["is_valid"] is True


@pytest.mark.asyncio
async def test_audit_ledger_service_class():
    """Verify the AuditLedger service manager class methods."""
    ledger = AuditLedger()

    test_uid = f"svc_user_{uuid.uuid4().hex[:6]}"
    event = await ledger.record_event(
        user_id=test_uid,
        action="service_class_action",
        query_hash="svc_hash",
        exposed_chunk_ids=["svc_chunk_1"],
    )
    assert event.log_id.startswith("log_")
    assert event.user_id == test_uid

    logs = await ledger.get_logs(user_id=test_uid, limit=10)
    assert len(logs) >= 1
    assert logs[0].action == "service_class_action"

    integrity = await ledger.verify_integrity()
    assert integrity["is_valid"] is True
    assert integrity["total_records"] >= 1


@pytest.mark.asyncio
async def test_compliance_api_verification_and_logs():
    """Verify REST API endpoints: GET /compliance/audit-logs and GET /compliance/verify-integrity."""
    await init_db()

    test_uid = f"api_user_{uuid.uuid4().hex[:6]}"
    await record_audit_event(
        user_id=test_uid,
        action="rest_api_audit_test",
        query_hash="api_hash_123",
        exposed_chunk_ids=["api_chunk_x", "api_chunk_y"],
        model_used="airgap-llm-v1",
        latency_ms={"total_ms": 33.3},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test audit logs endpoint
        resp_logs = await client.get("/api/v1/compliance/audit-logs", params={"user_id": test_uid})
        assert resp_logs.status_code == 200
        logs = resp_logs.json()
        assert len(logs) >= 1
        assert logs[0]["user_id"] == test_uid
        assert logs[0]["action"] == "rest_api_audit_test"
        assert len(logs[0]["entry_hash"]) == 64
        assert len(logs[0]["prev_hash"]) == 64

        # 2. Test verify-integrity endpoint
        resp_verify = await client.get("/api/v1/compliance/verify-integrity")
        assert resp_verify.status_code == 200
        report = resp_verify.json()
        assert report["is_valid"] is True
        assert report["total_records"] >= 1
        assert "verified_at" in report

