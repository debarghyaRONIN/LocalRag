"""
Sovereign Flywheel Dataset Builder for Local LoRA Fine-Tuning.

Extracts high-faithfulness sessions and expert-verified corrections from the database,
and exports them into standard instruction-tuning formats:
- Alpaca JSON: [{"instruction": "...", "input": "...", "output": "..."}]
- ShareGPT JSONL: {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}]}
"""

from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.db.models import DBChatSession, DBChatMessage, DBFeedback
from backend.app.services.evaluation.rag_triad import evaluate_faithfulness


DEFAULT_SYSTEM_PROMPT = (
    "You are a sovereign, air-gapped AI assistant. Answer the user query "
    "faithfully and accurately using the provided local context."
)


def format_alpaca_entry(
    instruction: str,
    input_text: str = "",
    output: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format a single item into Alpaca instruction-tuning schema."""
    entry: Dict[str, Any] = {
        "instruction": str(instruction).strip(),
        "input": str(input_text).strip() if input_text else "",
        "output": str(output).strip(),
    }
    if metadata:
        entry["metadata"] = metadata
    return entry


def format_sharegpt_entry(
    human_text: str,
    gpt_text: str,
    system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT,
    context_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Format a conversation turn into ShareGPT schema."""
    conversations = []
    if system_prompt:
        conversations.append({"from": "system", "value": system_prompt.strip()})

    human_content = human_text.strip()
    if context_text and context_text.strip():
        human_content = f"Context:\n{context_text.strip()}\n\nQuestion:\n{human_content}"

    conversations.append({"from": "human", "value": human_content})
    conversations.append({"from": "gpt", "value": str(gpt_text).strip()})

    return {"conversations": conversations}


def build_alpaca_dataset(
    training_pairs: List[Dict[str, Any]],
    include_metadata: bool = False
) -> List[Dict[str, Any]]:
    """Convert training pair dicts into standard Alpaca JSON format."""
    dataset = []
    for item in training_pairs:
        instruction = item.get("instruction") or item.get("query") or item.get("prompt") or ""
        input_text = item.get("input") or item.get("context") or ""
        output = item.get("output") or item.get("response") or item.get("correction") or ""

        if not instruction or not output:
            continue

        meta = item.get("metadata") if include_metadata else None
        dataset.append(format_alpaca_entry(instruction, input_text, output, metadata=meta))
    return dataset


def build_sharegpt_dataset(
    training_pairs: List[Dict[str, Any]],
    system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT
) -> List[Dict[str, Any]]:
    """Convert training pair dicts into ShareGPT format."""
    dataset = []
    for item in training_pairs:
        instruction = item.get("instruction") or item.get("query") or item.get("prompt") or ""
        input_text = item.get("input") or item.get("context") or ""
        output = item.get("output") or item.get("response") or item.get("correction") or ""

        if not instruction or not output:
            continue

        dataset.append(format_sharegpt_entry(
            human_text=instruction,
            gpt_text=output,
            system_prompt=system_prompt,
            context_text=input_text
        ))
    return dataset


def serialize_alpaca_json(dataset: List[Dict[str, Any]]) -> str:
    """Serialize Alpaca dataset to formatted JSON string."""
    return json.dumps(dataset, indent=2, ensure_ascii=False)


def serialize_sharegpt_jsonl(dataset: List[Dict[str, Any]]) -> str:
    """Serialize ShareGPT dataset to newline-delimited JSONL string."""
    lines = [json.dumps(record, ensure_ascii=False) for record in dataset]
    return "\n".join(lines) + ("\n" if lines else "")


def export_dataset_to_file(
    dataset: List[Dict[str, Any]],
    output_path: Union[str, Path],
    format_type: str = "alpaca"
) -> Path:
    """Export formatted dataset to disk as either .json or .jsonl."""
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    fmt = format_type.lower().strip()
    if fmt == "sharegpt":
        content = serialize_sharegpt_jsonl(dataset)
        out_p.write_text(content, encoding="utf-8")
    else:
        content = serialize_alpaca_json(dataset)
        out_p.write_text(content, encoding="utf-8")

    return out_p


def _extract_citations_text(citations: Any) -> str:
    """Extract plain text context from citation records."""
    if not citations:
        return ""
    if isinstance(citations, str):
        return citations

    passages = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str):
                passages.append(c)
            elif isinstance(c, dict):
                text = c.get("text") or c.get("content") or c.get("snippet") or c.get("filename", "")
                if text:
                    passages.append(text)
    return "\n\n".join(passages)


async def extract_training_pairs_from_db(
    db: AsyncSession,
    min_faithfulness: float = 0.70,
    only_verified: bool = False,
    min_rating: int = 1
) -> List[Dict[str, Any]]:
    """
    Extract high-faithfulness training pairs and verified expert corrections
    directly from DBFeedback, DBChatMessage, and DBChatSession.
    """
    training_pairs: List[Dict[str, Any]] = []

    # 1. Fetch Feedback records
    fb_stmt = select(DBFeedback).order_by(DBFeedback.created_at.desc())
    fb_res = await db.execute(fb_stmt)
    all_feedbacks = fb_res.scalars().all()

    # Cache messages to find user instructions and assistant context
    message_ids = [fb.message_id for fb in all_feedbacks if fb.message_id]
    messages_map: Dict[str, DBChatMessage] = {}
    if message_ids:
        msg_stmt = select(DBChatMessage).where(DBChatMessage.message_id.in_(message_ids))
        msg_res = await db.execute(msg_stmt)
        for msg in msg_res.scalars().all():
            messages_map[msg.message_id] = msg

    # Cache sessions to locate preceding user prompts
    session_ids = list({fb.session_id for fb in all_feedbacks if fb.session_id})
    all_session_messages: Dict[str, List[DBChatMessage]] = {}
    if session_ids:
        sess_msgs_stmt = (
            select(DBChatMessage)
            .where(DBChatMessage.session_id.in_(session_ids))
            .order_by(DBChatMessage.created_at.asc())
        )
        s_res = await db.execute(sess_msgs_stmt)
        for m in s_res.scalars().all():
            all_session_messages.setdefault(m.session_id, []).append(m)

    for fb in all_feedbacks:
        # Check verified filter
        if only_verified and not fb.is_expert_verified:
            continue

        target_msg = messages_map.get(fb.message_id) if fb.message_id else None
        session_id = fb.session_id or (target_msg.session_id if target_msg else None)

        # Locate preceding user prompt
        instruction = ""
        context_text = _extract_citations_text(fb.citations_approved)

        if session_id and session_id in all_session_messages:
            s_msgs = all_session_messages[session_id]
            if target_msg:
                # Find the user message immediately preceding target_msg
                for i, m in enumerate(s_msgs):
                    if m.message_id == target_msg.message_id and i > 0:
                        prev = s_msgs[i - 1]
                        if prev.role == "user":
                            instruction = prev.content
                            break
            if not instruction:
                # Fallback to first user message in session
                for m in s_msgs:
                    if m.role == "user":
                        instruction = m.content
                        break

        if not context_text and target_msg and target_msg.citations:
            context_text = _extract_citations_text(target_msg.citations)

        # A: Expert Correction present -> Ground Truth Gold Sample
        if fb.expert_correction and fb.expert_correction.strip():
            output_text = fb.expert_correction.strip()
            training_pairs.append({
                "instruction": instruction or "Answer the query based on context.",
                "input": context_text,
                "output": output_text,
                "source": "expert_correction",
                "is_expert_verified": True,
                "rating": fb.rating,
                "feedback_id": fb.feedback_id,
            })
            continue

        # B: Positive feedback rating (thumbs up) or verified assistant message
        if fb.rating >= min_rating or fb.is_expert_verified:
            output_text = target_msg.content if target_msg else ""
            if output_text and instruction:
                # Evaluate faithfulness score on the fly if citations exist
                chunks = [context_text] if context_text else []
                faith_score = evaluate_faithfulness(output_text, chunks) if chunks else 1.0

                if faith_score >= min_faithfulness:
                    training_pairs.append({
                        "instruction": instruction,
                        "input": context_text,
                        "output": output_text,
                        "source": "positive_feedback",
                        "faithfulness": faith_score,
                        "is_expert_verified": fb.is_expert_verified,
                        "rating": fb.rating,
                        "feedback_id": fb.feedback_id,
                    })

    # 2. Also harvest high-faithfulness session turns that haven't received negative feedback
    # (If no feedback or negative feedback not attached)
    negative_msg_ids = {fb.message_id for fb in all_feedbacks if fb.rating < 0}
    positive_fb_msg_ids = {fb.message_id for fb in all_feedbacks if fb.rating > 0 or fb.is_expert_verified}

    if not only_verified:
        sess_stmt = select(DBChatSession.session_id).order_by(DBChatSession.created_at.desc()).limit(50)
        s_res = await db.execute(sess_stmt)
        sess_ids = s_res.scalars().all()

        if sess_ids:
            all_m_stmt = (
                select(DBChatMessage)
                .where(DBChatMessage.session_id.in_(sess_ids))
                .order_by(DBChatMessage.created_at.asc())
            )
            all_m_res = await db.execute(all_m_stmt)
            all_msgs = all_m_res.scalars().all()

            # Group by session_id in memory (1 batch query instead of N queries)
            grouped_msgs: Dict[str, List[DBChatMessage]] = {}
            for m in all_msgs:
                grouped_msgs.setdefault(m.session_id, []).append(m)

            for sid, msgs in grouped_msgs.items():
                for i in range(len(msgs) - 1):
                    user_m = msgs[i]
                    asst_m = msgs[i + 1]
                    if user_m.role == "user" and asst_m.role == "assistant":
                        if asst_m.message_id in negative_msg_ids or asst_m.message_id in positive_fb_msg_ids:
                            continue  # Already handled in feedback branch

                        ctx = _extract_citations_text(asst_m.citations)
                        if ctx:
                            faith = evaluate_faithfulness(asst_m.content, [ctx])
                            if faith >= min_faithfulness:
                                training_pairs.append({
                                    "instruction": user_m.content,
                                    "input": ctx,
                                    "output": asst_m.content,
                                    "source": "high_faithfulness_session",
                                    "faithfulness": faith,
                                    "is_expert_verified": False,
                                    "session_id": sid,
                                })

    return training_pairs


class DatasetBuilder:
    """Convenience builder class for creating and exporting LoRA training datasets."""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    async def export_training_data(
        self,
        format_type: str = "alpaca",
        min_faithfulness: float = 0.70,
        only_verified: bool = False,
        output_path: Optional[Union[str, Path]] = None,
    ) -> Union[List[Dict[str, Any]], str]:
        """
        Extract from DB and export into the requested format (alpaca or sharegpt).
        """
        if self.db is None:
            raise ValueError("AsyncSession required to extract from database.")

        pairs = await extract_training_pairs_from_db(
            self.db,
            min_faithfulness=min_faithfulness,
            only_verified=only_verified,
        )

        fmt = format_type.lower().strip()
        if fmt == "sharegpt":
            dataset = build_sharegpt_dataset(pairs)
            content = serialize_sharegpt_jsonl(dataset)
            if output_path:
                export_dataset_to_file(dataset, output_path, format_type="sharegpt")
            return content
        else:
            dataset = build_alpaca_dataset(pairs)
            if output_path:
                export_dataset_to_file(dataset, output_path, format_type="alpaca")
            return dataset

