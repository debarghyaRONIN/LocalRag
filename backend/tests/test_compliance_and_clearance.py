import pytest
import uuid
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBAuditLog, ClearanceLevel, DBDocument, DBParentChunk
from backend.app.domain.models import ChildChunk, ParentChunk
from backend.app.services.compliance.audit_ledger import (
    record_audit_event,
    verify_audit_integrity,
    compute_entry_hash,
    GENESIS_HASH,
    AuditLedger,
)
from backend.app.services.retrieval.vector_store import QdrantVectorStore


@pytest.mark.asyncio
async def test_cryptographic_audit_ledger_chaining():
    """Verify SHA-256 cryptographic chaining of audit ledger events."""
    await init_db()

    user_a = f"user_{uuid.uuid4().hex[:6]}"
    user_b = f"user_{uuid.uuid4().hex[:6]}"

    async with AsyncSessionLocal() as session:
        # Record first event
        event1 = await record_audit_event(
            db=session,
            user_id=user_a,
            action="query",
            query_hash="hash_alpha",
            exposed_chunk_ids=["chunk_1", "chunk_2"],
            model_used="model_v1",
            latency_ms={"total_ms": 42.5},
        )
        assert event1.log_id.startswith("log_")
        assert len(event1.entry_hash) == 64

        # Record second event chained to first
        event2 = await record_audit_event(
            db=session,
            user_id=user_b,
            action="document_upload",
            query_hash="hash_beta",
            exposed_chunk_ids=["doc_101"],
            model_used="bge-small-en-v1.5",
            latency_ms={"total_ms": 15.0},
        )
        assert event2.prev_hash == event1.entry_hash
        assert len(event2.entry_hash) == 64

        # Record third event chained to second
        event3 = await record_audit_event(
            db=session,
            user_id=user_a,
            action="query_stream",
            query_hash="hash_gamma",
            exposed_chunk_ids=["chunk_3"],
            model_used="model_v1",
            latency_ms={"total_ms": 110.2},
        )
        assert event3.prev_hash == event2.entry_hash

        # Verify cryptographic integrity
        report = await verify_audit_integrity(db=session)
        assert report["is_valid"] is True
        assert report["total_records"] >= 3
        assert len(report["tampered_records"]) == 0


@pytest.mark.asyncio
async def test_tamper_detection_in_audit_ledger():
    """Verify verify_audit_integrity catches content tampering and broken chains."""
    await init_db()

    async with AsyncSessionLocal() as session:
        # Create a dedicated entry
        target_user = f"tamper_test_{uuid.uuid4().hex[:6]}"
        entry = await record_audit_event(
            db=session,
            user_id=target_user,
            action="confidential_access",
            query_hash="valid_hash",
            exposed_chunk_ids=["secret_chunk_99"],
        )

        # Baseline: integrity should be valid
        report_before = await verify_audit_integrity(db=session)
        assert report_before["is_valid"] is True

        # Post-facto tamper with the recorded action
        entry.action = "tampered_fake_action"
        await session.commit()

        # Audit integrity must now flag the tampering
        report_tampered = await verify_audit_integrity(db=session)
        assert report_tampered["is_valid"] is False
        assert any(t["log_id"] == entry.log_id for t in report_tampered["tampered_records"])

        # Restore entry to keep DB clean
        entry.action = "confidential_access"
        await session.commit()

        report_restored = await verify_audit_integrity(db=session)
        assert report_restored["is_valid"] is True


@pytest.mark.asyncio
async def test_vector_store_clearance_filtering(tmp_path: Path):
    """
    Verify RBAC clearance levels:
    1=Public, 2=Internal, 3=Confidential, 4=Top Secret
    Chunks with clearance > user_clearance are filtered out at the vector query stage.
    """
    store = QdrantVectorStore(storage_path=str(tmp_path / "test_clearance_qdrant"))

    child_chunks = [
        ChildChunk(
            chunk_id="chunk_public",
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="Public company policy information.",
            token_count=10,
            clearance_level=ClearanceLevel.PUBLIC,  # 1
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chunk_internal",
            parent_id="p1",
            doc_id="d1",
            chunk_index=1,
            content="Internal team meeting notes and agendas.",
            token_count=10,
            clearance_level=ClearanceLevel.INTERNAL,  # 2
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chunk_confidential",
            parent_id="p1",
            doc_id="d1",
            chunk_index=2,
            content="Confidential financial forecast data.",
            token_count=10,
            clearance_level=ClearanceLevel.CONFIDENTIAL,  # 3
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chunk_top_secret",
            parent_id="p1",
            doc_id="d1",
            chunk_index=3,
            content="Top secret unreleased quantum hardware specifications.",
            token_count=10,
            clearance_level=ClearanceLevel.TOP_SECRET,  # 4
            allowed_departments=[],
        ),
    ]

    parent_map = {
        "p1": ParentChunk(
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="Full document parent content",
            token_count=40,
        )
    }

    dummy_vector = [0.1] * store.vector_size
    embeddings = [dummy_vector for _ in child_chunks]

    store.upsert_chunks(
        child_chunks=child_chunks,
        parent_map=parent_map,
        embeddings=embeddings,
        filename="security_test.pdf",
    )

    # 1. User with Public clearance (level 1)
    hits_public = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.PUBLIC,
    )
    hit_ids_public = {h["chunk_id"] for h in hits_public}
    assert "chunk_public" in hit_ids_public
    assert "chunk_internal" not in hit_ids_public
    assert "chunk_confidential" not in hit_ids_public
    assert "chunk_top_secret" not in hit_ids_public

    # 2. User with Internal clearance (level 2)
    hits_internal = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.INTERNAL,
    )
    hit_ids_internal = {h["chunk_id"] for h in hits_internal}
    assert "chunk_public" in hit_ids_internal
    assert "chunk_internal" in hit_ids_internal
    assert "chunk_confidential" not in hit_ids_internal
    assert "chunk_top_secret" not in hit_ids_internal

    # 3. User with Confidential clearance (level 3)
    hits_conf = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.CONFIDENTIAL,
    )
    hit_ids_conf = {h["chunk_id"] for h in hits_conf}
    assert "chunk_public" in hit_ids_conf
    assert "chunk_internal" in hit_ids_conf
    assert "chunk_confidential" in hit_ids_conf
    assert "chunk_top_secret" not in hit_ids_conf

    # 4. User with Top Secret clearance (level 4)
    hits_ts = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.TOP_SECRET,
    )
    hit_ids_ts = {h["chunk_id"] for h in hits_ts}
    assert "chunk_public" in hit_ids_ts
    assert "chunk_internal" in hit_ids_ts
    assert "chunk_confidential" in hit_ids_ts
    assert "chunk_top_secret" in hit_ids_ts


@pytest.mark.asyncio
async def test_vector_store_department_filtering(tmp_path: Path):
    """
    Verify RBAC department filtering in Qdrant:
    Chunks with non-matching departments are filtered out.
    Empty allowed_departments means accessible to all departments.
    """
    store = QdrantVectorStore(storage_path=str(tmp_path / "test_dept_qdrant"))

    child_chunks = [
        ChildChunk(
            chunk_id="chunk_all_depts",
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="General company handbook.",
            token_count=10,
            clearance_level=1,
            allowed_departments=[],  # Accessible by everyone
        ),
        ChildChunk(
            chunk_id="chunk_eng",
            parent_id="p1",
            doc_id="d1",
            chunk_index=1,
            content="Engineering architecture design document.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["engineering"],
        ),
        ChildChunk(
            chunk_id="chunk_finance",
            parent_id="p1",
            doc_id="d1",
            chunk_index=2,
            content="Quarterly balance sheet for finance team.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["finance"],
        ),
        ChildChunk(
            chunk_id="chunk_multi",
            parent_id="p1",
            doc_id="d1",
            chunk_index=3,
            content="Budget planning for engineering and operations.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["engineering", "operations"],
        ),
    ]

    parent_map = {
        "p1": ParentChunk(
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="Parent content",
            token_count=40,
        )
    }

    dummy_vector = [0.2] * store.vector_size
    embeddings = [dummy_vector for _ in child_chunks]

    store.upsert_chunks(
        child_chunks=child_chunks,
        parent_map=parent_map,
        embeddings=embeddings,
        filename="dept_test.txt",
    )

    # 1. User from "engineering" department
    hits_eng = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_department="engineering",
    )
    hit_ids_eng = {h["chunk_id"] for h in hits_eng}
    assert "chunk_all_depts" in hit_ids_eng
    assert "chunk_eng" in hit_ids_eng
    assert "chunk_multi" in hit_ids_eng
    assert "chunk_finance" not in hit_ids_eng

    # 2. User from "finance" department
    hits_fin = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_departments=["finance"],
    )
    hit_ids_fin = {h["chunk_id"] for h in hits_fin}
    assert "chunk_all_depts" in hit_ids_fin
    assert "chunk_finance" in hit_ids_fin
    assert "chunk_eng" not in hit_ids_fin
    assert "chunk_multi" not in hit_ids_fin

    # 3. User with no department memberships
    hits_none = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_departments=[],
    )
    hit_ids_none = {h["chunk_id"] for h in hits_none}
    assert "chunk_all_depts" in hit_ids_none
    assert "chunk_eng" not in hit_ids_none
    assert "chunk_finance" not in hit_ids_none
    assert "chunk_multi" not in hit_ids_none


@pytest.mark.asyncio
async def test_compliance_api_endpoints():
    """Verify GET /api/v1/compliance/audit-logs and GET /api/v1/compliance/verify-integrity."""
    await init_db()

    # Pre-populate an audit log event
    test_user = f"api_test_user_{uuid.uuid4().hex[:6]}"
    await record_audit_event(
        user_id=test_user,
        action="api_compliance_test",
        query_hash="api_test_hash",
        exposed_chunk_ids=["chunk_test_api"],
        model_used="test_model",
        latency_ms={"total_ms": 25.0},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test audit logs endpoint
        resp_logs = await client.get("/api/v1/compliance/audit-logs", params={"limit": 20})
        assert resp_logs.status_code == 200
        logs = resp_logs.json()
        assert isinstance(logs, list)
        assert len(logs) >= 1

        matched = [entry for entry in logs if entry["user_id"] == test_user]
        assert len(matched) >= 1
        entry = matched[0]
        assert entry["action"] == "api_compliance_test"
        assert entry["query_hash"] == "api_test_hash"
        assert "chunk_test_api" in entry["exposed_chunk_ids"]
        assert len(entry["prev_hash"]) == 64
        assert len(entry["entry_hash"]) == 64

        # 2. Test verify integrity endpoint
        resp_verify = await client.get("/api/v1/compliance/verify-integrity")
        assert resp_verify.status_code == 200
        report = resp_verify.json()
        assert report["is_valid"] is True
        assert report["total_records"] >= 1
        assert "verified_at" in report
        assert "Audit ledger integrity verified" in report["message"]

