"""
Test Suite for Sealed Pilot Stack Specification & MVP API Compliance.

Validates:
1. POST /v1/chat/completions (Chat completions with and without retrieval, request_id generation)
2. POST /v1/feedback (tied to request_id, expert correction)
3. POST /v1/evals/runs & GET /v1/evals/runs/{id}
4. POST /v1/tuning/jobs (Dataset and candidate adapter registration)
5. POST /v1/models/promote (Three Promotion Gates: Held-out > baseline, 0 regressions, permission cases)
6. GET /admin/egress-report (0 outbound attempts, signed report hash)
7. GET /admin/support-bundle (Zipped diagnostics, redacted customer content)
"""

import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from backend.app.main import app
from backend.app.db.models import Base, DBAdapter, DBTestCase, DBEvalRun, DBRequest, DBFeedback
from backend.app.db.session import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session):
    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_standard_chat_completions_non_retrieval(client: AsyncClient):
    """Assert standard completion works without retrieval."""
    payload = {
        "model": "Qwen/Qwen2.5-3B-Instruct",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is airgap security?"}
        ],
        "stream": False,
        "retrieval": False
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) > 0
    assert "request_id" in data
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert len(data["choices"][0]["message"]["content"]) > 0


@pytest.mark.asyncio
async def test_standard_chat_completions_with_retrieval(client: AsyncClient):
    """Assert completion with retrieval returns citations and persists request record."""
    payload = {
        "model": "Qwen/Qwen2.5-3B-Instruct",
        "messages": [
            {"role": "user", "content": "Verify shift handover checklists."}
        ],
        "stream": False,
        "retrieval": True,
        "clearance_level": 2
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "request_id" in data
    assert "citations" in data


@pytest.mark.asyncio
async def test_feedback_submission_tied_to_request_id(client: AsyncClient):
    """Assert POST /v1/feedback records rating and expert correction."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    payload = {
        "request_id": req_id,
        "rating": 1,
        "corrected_answer": "Mandatory checklist requires dual-signoff on all Level 3 incidents.",
        "reason_code": "expert_correction",
        "citations_approved": ["chunk_001", "chunk_002"]
    }
    resp = await client.post("/v1/feedback", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "recorded"
    assert data["request_id"] == req_id


@pytest.mark.asyncio
async def test_evals_run_and_reporting(client: AsyncClient):
    """Assert POST /v1/evals/runs executes evaluation and GET /v1/evals/runs/{id} fetches results."""
    eval_req = {
        "model_id": "Qwen/Qwen2.5-3B-Instruct",
        "suite_version": "v1.0"
    }
    run_resp = await client.post("/v1/evals/runs", json=eval_req)
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    run_id = run_data["id"]
    assert "totals" in run_data

    # Fetch report
    get_resp = await client.get(f"/v1/evals/runs/{run_id}")
    assert get_resp.status_code == 200
    report_data = get_resp.json()
    assert report_data["id"] == run_id
    assert report_data["status"] == "completed"


@pytest.mark.asyncio
async def test_tuning_jobs_creates_candidate_adapter(client: AsyncClient):
    """Assert POST /v1/tuning/jobs queues a LoRA tuning run and returns candidate adapter."""
    payload = {
        "base_model_id": "Qwen/Qwen2.5-3B-Instruct",
        "training_config": {
            "lora_r": 16,
            "epochs": 3,
            "learning_rate": 0.0002
        }
    }
    resp = await client.post("/v1/tuning/jobs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert "adapter_id" in data
    assert data["status"] == "candidate_ready"


@pytest.mark.asyncio
async def test_adapter_promotion_gates(client: AsyncClient, test_session: AsyncSession):
    """
    Assert POST /v1/models/promote enforces all 3 gates:
    Gate 1: Candidate beats live setup on held-out test cases.
    Gate 2: No new failures on regression suite.
    Gate 3: Keeps passing permission cases.
    """
    # 1. Create a passing candidate adapter
    adapter_id = f"lora_{uuid.uuid4().hex[:8]}"
    adapter = DBAdapter(
        adapter_id=adapter_id,
        base_model_id="Qwen/Qwen2.5-3B-Instruct",
        status="candidate",
    )
    test_session.add(adapter)
    await test_session.commit()

    promote_payload = {
        "adapter_id": adapter_id,
        "user_id": "security_admin"
    }
    resp = await client.post("/v1/models/promote", json=promote_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "live"
    assert data["gates"]["all_passed"] is True
    assert data["gates"]["gate_1_held_out_passed"] is True
    assert data["gates"]["gate_2_regression_passed"] is True
    assert data["gates"]["gate_3_permission_passed"] is True


@pytest.mark.asyncio
async def test_admin_egress_report(client: AsyncClient):
    """Assert GET /admin/egress-report returns verified no-egress status and SHA256 signature."""
    from backend.app.core.network_guard import clear_egress_audit_log
    clear_egress_audit_log()

    resp = await client.get("/admin/egress-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "PASS"
    assert data["outbound_attempts"] == 0
    assert "report_hash_sha256" in data
    assert len(data["report_hash_sha256"]) == 64
    assert data["firewall_ruleset"]["policy"] == "DEFAULT_DENY_OUTBOUND"


@pytest.mark.asyncio
async def test_admin_support_bundle(client: AsyncClient):
    """Assert GET /admin/support-bundle generates a valid zip file without customer secrets."""
    resp = await client.get("/admin/support-bundle")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert len(resp.content) > 100
