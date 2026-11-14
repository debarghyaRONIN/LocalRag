import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBChatSession, DBChatMessage


@pytest.mark.asyncio
async def test_session_lifecycle_and_messages():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a session
        resp = await client.post("/api/v1/sessions", json={"title": "Test Chat Session"})
        assert resp.status_code == 200
        sess_data = resp.json()
        session_id = sess_data["session_id"]
        assert session_id.startswith("sess_")
        assert sess_data["title"] == "Test Chat Session"

        # 2. Add sample messages directly via DB session
        async with AsyncSessionLocal() as db:
            msg_user = DBChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                role="user",
                content="What is vLLM PagedAttention?",
            )
            msg_assistant = DBChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                role="assistant",
                content="PagedAttention is an attention algorithm designed to reduce memory fragmentation.",
                citations=[{"citation_id": 1, "filename": "vllm_paper.pdf", "page_number": 3}],
                latency_ms={"generation_ms": 120.5},
            )
            db.add_all([msg_user, msg_assistant])
            await db.commit()

        # 3. Retrieve messages via GET /sessions/{session_id}/messages
        resp_msgs = await client.get(f"/api/v1/sessions/{session_id}/messages")
        assert resp_msgs.status_code == 200
        messages = resp_msgs.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is vLLM PagedAttention?"
        assert messages[1]["role"] == "assistant"
        assert len(messages[1]["citations"]) == 1
        assert messages[1]["citations"][0]["filename"] == "vllm_paper.pdf"
        assert messages[1]["latency_ms"]["generation_ms"] == 120.5

        # 4. Delete session and verify messages are purged
        del_resp = await client.delete(f"/api/v1/sessions/{session_id}")
        assert del_resp.status_code == 200

        # Query messages again -> should be empty
        resp_msgs_after = await client.get(f"/api/v1/sessions/{session_id}/messages")
        assert resp_msgs_after.status_code == 200
        assert len(resp_msgs_after.json()) == 0

