import json
import uuid
import hashlib
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.domain.models import QueryRequest, QueryResponse
from backend.app.db.session import get_db, AsyncSessionLocal
from backend.app.db.models import DBChatSession, DBChatMessage
from backend.app.services.generation.orchestrator import RAGOrchestrator
from backend.app.services.compliance.audit_ledger import record_audit_event
from backend.app.services.indexing.scheduler import get_resource_scheduler

router = APIRouter()
_orchestrator = None


def get_orchestrator() -> RAGOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RAGOrchestrator()
    return _orchestrator


async def get_session_history(session_id: str, db: AsyncSession) -> list[dict]:
    """Retrieve message history for a given session."""
    if not session_id:
        return []
    stmt = (
        select(DBChatMessage)
        .where(DBChatMessage.session_id == session_id)
        .order_by(DBChatMessage.created_at.asc())
        .limit(10)
    )
    res = await db.execute(stmt)
    messages = res.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Standard non-streaming grounded query endpoint.
    Retrieves, reranks, answers with citations, and returns detailed latency metrics.
    """
    history = []
    if payload.session_id:
        history = await get_session_history(payload.session_id, db)

    async with get_resource_scheduler().priority_chat_scope():
        response = await get_orchestrator().execute_query(
            query=payload.query,
            top_k=payload.top_k or settings.RERANK_TOP_K,
            min_score=payload.min_rerank_score or settings.RERANK_MIN_SCORE,
            chat_history=history,
            user_clearance=payload.user_clearance,
            user_departments=payload.user_departments,
        )
    response.session_id = payload.session_id

    # Record immutable audit event
    try:
        q_hash = hashlib.sha256(payload.query.encode("utf-8")).hexdigest()
        exposed_ids = [c.chunk_id for c in response.citations]
        await record_audit_event(
            db=db,
            user_id=payload.user_id or "anonymous",
            action="query",
            query_hash=q_hash,
            exposed_chunk_ids=exposed_ids,
            model_used=response.model_used,
            latency_ms=response.latency_ms,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to record audit event: {e}")

    # Save to chat history if session_id is active
    if payload.session_id:
        u_msg = DBChatMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            session_id=payload.session_id,
            role="user",
            content=payload.query,
        )
        a_msg = DBChatMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            session_id=payload.session_id,
            role="assistant",
            content=response.answer,
            citations=[c.model_dump() for c in response.citations],
            latency_ms=response.latency_ms,
        )
        db.add_all([u_msg, a_msg])
        await db.commit()

    return response


@router.post("/query/stream")
async def stream_query_documents(
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Streaming SSE query endpoint.
    Emits real-time tokens, citation payloads, and latency breakdowns via text/event-stream,
    and automatically persists both user and assistant turns to the chat session ledger.
    """
    history = []
    if payload.session_id:
        history = await get_session_history(payload.session_id, db)

    generator = get_orchestrator().stream_query(
        query=payload.query,
        top_k=payload.top_k or settings.RERANK_TOP_K,
        min_score=payload.min_rerank_score or settings.RERANK_MIN_SCORE,
        chat_history=history,
        user_clearance=payload.user_clearance,
        user_departments=payload.user_departments,
    )

    async def event_generator_with_persistence():
        tokens_accumulated = []
        citations_accumulated = []
        latency_accumulated = {}
        persisted = False

        async def save_turn():
            nonlocal persisted
            if persisted:
                return
            persisted = True
            try:
                # Record audit log
                q_hash = hashlib.sha256(payload.query.encode("utf-8")).hexdigest()
                exp_ids = [c.get("chunk_id") for c in citations_accumulated if isinstance(c, dict) and "chunk_id" in c]
                await record_audit_event(
                    user_id=payload.user_id or "anonymous",
                    action="query_stream",
                    query_hash=q_hash,
                    exposed_chunk_ids=exp_ids,
                    model_used=settings.VLLM_MODEL,
                    latency_ms=latency_accumulated,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to record stream audit log: {e}")

            if not payload.session_id:
                return
            try:
                async with AsyncSessionLocal() as session:
                    sess_stmt = select(DBChatSession).where(DBChatSession.session_id == payload.session_id)
                    sess_res = await session.execute(sess_stmt)
                    sess = sess_res.scalar_one_or_none()
                    if sess:
                        sess.updated_at = datetime.utcnow()
                        if sess.title in ["New Conversation", "Untitled Session", ""]:
                            words = payload.query.strip().split()
                            sess.title = " ".join(words[:5]) + ("..." if len(words) > 5 else "")

                    u_msg = DBChatMessage(
                        message_id=f"msg_{uuid.uuid4().hex[:12]}",
                        session_id=payload.session_id,
                        role="user",
                        content=payload.query,
                    )
                    a_msg = DBChatMessage(
                        message_id=f"msg_{uuid.uuid4().hex[:12]}",
                        session_id=payload.session_id,
                        role="assistant",
                        content="".join(tokens_accumulated),
                        citations=citations_accumulated,
                        latency_ms=latency_accumulated,
                    )
                    session.add_all([u_msg, a_msg])
                    await session.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to persist streamed messages: {e}")

        async with get_resource_scheduler().priority_chat_scope():
            try:
                async for chunk in generator:
                    if '"type": "token"' in chunk:
                        try:
                            payload_json = json.loads(chunk.replace("data: ", "").strip())
                            tokens_accumulated.append(payload_json.get("content", ""))
                        except Exception:
                            pass
                    elif '"type": "citations"' in chunk:
                        try:
                            payload_json = json.loads(chunk.replace("data: ", "").strip())
                            citations_accumulated = payload_json.get("data", [])
                        except Exception:
                            pass
                    elif '"type": "latency"' in chunk:
                        try:
                            payload_json = json.loads(chunk.replace("data: ", "").strip())
                            latency_accumulated = payload_json.get("data", {})
                        except Exception:
                            pass

                    if "[DONE]" in chunk:
                        await save_turn()

                    yield chunk
            finally:
                await save_turn()

    return StreamingResponse(
        event_generator_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

