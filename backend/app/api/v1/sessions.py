import uuid
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.session import get_db
from backend.app.db.models import DBChatSession, DBChatMessage

router = APIRouter()


class SessionResponse(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New Conversation"


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    citations: List[dict] = []
    latency_ms: dict = {}
    timestamp: str


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    """List all conversation sessions ordered by most recently updated."""
    stmt = select(DBChatSession).order_by(DBChatSession.updated_at.desc())
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    return [
        SessionResponse(
            session_id=s.session_id,
            title=s.title,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in sessions
    ]


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    payload: CreateSessionRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a new chat conversation session."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    new_session = DBChatSession(
        session_id=session_id,
        title=payload.title or "New Conversation"
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    return SessionResponse(
        session_id=new_session.session_id,
        title=new_session.title,
        created_at=new_session.created_at.isoformat(),
        updated_at=new_session.updated_at.isoformat(),
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a conversation session and all its messages."""
    stmt = select(DBChatSession).where(DBChatSession.session_id == session_id)
    res = await db.execute(stmt)
    sess = res.scalar_one_or_none()

    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(sess)
    await db.commit()
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/messages", response_model=List[ChatMessageResponse])
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve full chronological conversation message history for a session."""
    stmt = (
        select(DBChatMessage)
        .where(DBChatMessage.session_id == session_id)
        .order_by(DBChatMessage.created_at.asc())
    )
    res = await db.execute(stmt)
    messages = res.scalars().all()
    return [
        ChatMessageResponse(
            id=m.message_id,
            role=m.role,
            content=m.content,
            citations=m.citations or [],
            latency_ms=m.latency_ms or {},
            timestamp=m.created_at.strftime("%H:%M:%S") if m.created_at else "",
        )
        for m in messages
    ]

