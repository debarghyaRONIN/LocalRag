import uuid
from datetime import datetime
from typing import List, Optional, Any, Union
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.session import get_db
from backend.app.db.models import DBFeedback
from backend.app.services.training.dataset_builder import (
    DatasetBuilder,
    build_alpaca_dataset,
    build_sharegpt_dataset,
    serialize_sharegpt_jsonl,
    extract_training_pairs_from_db,
    export_dataset_to_file,
)
from backend.app.services.evaluation.rag_triad import (
    evaluate_context_relevance,
    evaluate_faithfulness,
    evaluate_answer_relevance,
    evaluate_rag_triad,
)

router = APIRouter()


class FeedbackCreate(BaseModel):
    message_id: Optional[str] = Field(None, description="Target assistant message ID")
    session_id: Optional[str] = Field(None, description="Conversation session ID")
    rating: int = Field(..., description="Rating score: 1 (positive) or -1 (negative)")
    feedback_category: Optional[str] = Field(None, description="Category (e.g. accuracy, hallucination, citations)")
    expert_correction: Optional[str] = Field(None, description="Verified human expert correction")
    citations_approved: Optional[List[Any]] = Field(default_factory=list, description="List of approved citations")
    is_expert_verified: Optional[bool] = Field(False, description="Whether flagged as expert verified")


class FeedbackResponse(BaseModel):
    feedback_id: str
    message_id: Optional[str]
    session_id: Optional[str]
    rating: int
    feedback_category: Optional[str]
    expert_correction: Optional[str]
    citations_approved: List[Any]
    is_expert_verified: bool
    created_at: str


class EvaluateTriadRequest(BaseModel):
    query: str
    retrieved_chunks: List[str]
    answer: str


class EvaluateTriadResponse(BaseModel):
    context_relevance: float
    faithfulness: float
    groundedness: float
    answer_relevance: float
    overall_score: float


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit user feedback, thumbs up/down rating, and optional expert correction.
    """
    feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
    created_dt = datetime.utcnow()

    feedback = DBFeedback(
        feedback_id=feedback_id,
        message_id=payload.message_id,
        session_id=payload.session_id,
        rating=payload.rating,
        feedback_category=payload.feedback_category,
        expert_correction=payload.expert_correction,
        citations_approved=payload.citations_approved or [],
        is_expert_verified=payload.is_expert_verified or (bool(payload.expert_correction and payload.expert_correction.strip())),
        created_at=created_dt,
    )

    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        feedback_id=feedback.feedback_id,
        message_id=feedback.message_id,
        session_id=feedback.session_id,
        rating=feedback.rating,
        feedback_category=feedback.feedback_category,
        expert_correction=feedback.expert_correction,
        citations_approved=feedback.citations_approved or [],
        is_expert_verified=feedback.is_expert_verified,
        created_at=feedback.created_at.isoformat() if feedback.created_at else created_dt.isoformat(),
    )


@router.get("/feedback", response_model=List[FeedbackResponse])
async def list_feedback(
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List submitted feedback entries with optional filtering."""
    stmt = select(DBFeedback).order_by(DBFeedback.created_at.desc())
    if session_id:
        stmt = stmt.where(DBFeedback.session_id == session_id)
    if message_id:
        stmt = stmt.where(DBFeedback.message_id == message_id)

    res = await db.execute(stmt)
    records = res.scalars().all()

    return [
        FeedbackResponse(
            feedback_id=f.feedback_id,
            message_id=f.message_id,
            session_id=f.session_id,
            rating=f.rating,
            feedback_category=f.feedback_category,
            expert_correction=f.expert_correction,
            citations_approved=f.citations_approved or [],
            is_expert_verified=f.is_expert_verified,
            created_at=f.created_at.isoformat() if f.created_at else "",
        )
        for f in records
    ]


@router.get("/feedback/export-training-data")
async def export_training_data(
    format: str = Query("alpaca", pattern="^(alpaca|sharegpt)$", description="Format: alpaca or sharegpt"),
    min_faithfulness: float = Query(0.7, ge=0.0, le=1.0, description="Minimum faithfulness threshold"),
    only_verified: bool = Query(False, description="Export only expert-verified records"),
    output_path: Optional[str] = Query(None, description="Optional local file path to write export"),
    db: AsyncSession = Depends(get_db)
):
    """
    Export verified expert corrections and high-faithfulness conversations into
    standard instruction-tuning datasets (Alpaca JSON or ShareGPT JSONL) for local LoRA fine-tuning.
    """
    pairs = await extract_training_pairs_from_db(
        db=db,
        min_faithfulness=min_faithfulness,
        only_verified=only_verified,
    )

    fmt = format.lower().strip()
    if fmt == "sharegpt":
        sharegpt_records = build_sharegpt_dataset(pairs)
        jsonl_content = serialize_sharegpt_jsonl(sharegpt_records)
        if output_path:
            export_dataset_to_file(sharegpt_records, output_path, format_type="sharegpt")
        return Response(content=jsonl_content, media_type="application/x-ndjson")

    # Default: Alpaca JSON
    alpaca_records = build_alpaca_dataset(pairs)
    if output_path:
        export_dataset_to_file(alpaca_records, output_path, format_type="alpaca")
    return JSONResponse(content=alpaca_records)


@router.post("/feedback/evaluate-triad", response_model=EvaluateTriadResponse)
async def evaluate_triad_endpoint(payload: EvaluateTriadRequest):
    """
    Offline evaluation of Context Relevance, Faithfulness, and Answer Relevance.
    """
    results = evaluate_rag_triad(
        query=payload.query,
        retrieved_chunks=payload.retrieved_chunks,
        answer=payload.answer,
    )
    return EvaluateTriadResponse(**results)
