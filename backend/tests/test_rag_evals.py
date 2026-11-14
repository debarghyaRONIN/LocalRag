import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.db.models import DBFeedback, DBChatSession, DBChatMessage
from backend.app.services.evaluation.rag_triad import (
    evaluate_context_relevance,
    evaluate_faithfulness,
    evaluate_groundedness,
    evaluate_answer_relevance,
    evaluate_rag_triad,
)
from backend.app.services.training.dataset_builder import (
    format_alpaca_entry,
    format_sharegpt_entry,
    build_alpaca_dataset,
    build_sharegpt_dataset,
    serialize_alpaca_json,
    serialize_sharegpt_jsonl,
    export_dataset_to_file,
    extract_training_pairs_from_db,
)


def test_rag_triad_metrics_accuracy():
    query = "What is the primary function of memory paging in operating systems?"
    relevant_chunks = [
        "Memory paging is a memory management scheme that eliminates the need for contiguous allocation of physical memory.",
        "Paging allows the physical address space of a process to be noncontiguous."
    ]
    irrelevant_chunks = [
        "The Roman empire expanded across Europe and the Mediterranean basin.",
        "Photosynthesis in plants converts solar radiation into biochemical energy."
    ]

    faithful_answer = "Memory paging is a memory management scheme allowing noncontiguous physical memory allocation."
    hallucinated_answer = "Memory paging was invented on Mars in 1492 to regulate space shuttle atmospheric entries."

    # 1. Context relevance: relevant chunks should score significantly higher than irrelevant chunks
    rel_score = evaluate_context_relevance(query, relevant_chunks)
    irrel_score = evaluate_context_relevance(query, irrelevant_chunks)
    assert 0.0 <= rel_score <= 1.0
    assert 0.0 <= irrel_score <= 1.0
    assert rel_score > irrel_score

    # 2. Faithfulness / Groundedness: faithful answer must score significantly higher
    faith_high = evaluate_faithfulness(faithful_answer, relevant_chunks)
    faith_low = evaluate_faithfulness(hallucinated_answer, relevant_chunks)
    groundedness = evaluate_groundedness(faithful_answer, relevant_chunks)
    assert 0.0 <= faith_high <= 1.0
    assert 0.0 <= faith_low <= 1.0
    assert faith_high == groundedness
    assert faith_high > faith_low

    # 3. Answer relevance: direct answer must score higher than irrelevant answer
    ans_rel_high = evaluate_answer_relevance(query, faithful_answer)
    ans_rel_low = evaluate_answer_relevance(query, "Photosynthesis converts solar radiation into energy.")
    assert 0.0 <= ans_rel_high <= 1.0
    assert 0.0 <= ans_rel_low <= 1.0
    assert ans_rel_high > ans_rel_low

    # 4. Full Triad dictionary
    triad = evaluate_rag_triad(query, relevant_chunks, faithful_answer)
    assert "context_relevance" in triad
    assert "faithfulness" in triad
    assert "groundedness" in triad
    assert "answer_relevance" in triad
    assert "overall_score" in triad
    assert triad["overall_score"] == round(
        (triad["context_relevance"] + triad["faithfulness"] + triad["answer_relevance"]) / 3.0, 4
    )


def test_rag_triad_edge_cases():
    # Empty inputs return 0.0
    assert evaluate_context_relevance("", ["some context"]) == 0.0
    assert evaluate_context_relevance("query", []) == 0.0
    assert evaluate_faithfulness("", ["some context"]) == 0.0
    assert evaluate_faithfulness("answer", []) == 0.0
    assert evaluate_answer_relevance("", "answer") == 0.0
    assert evaluate_answer_relevance("query", "") == 0.0


def test_dataset_builder_formats(tmp_path):
    pairs = [
        {
            "instruction": "Explain zero-egress architecture.",
            "input": "Zero-egress systems completely disable external network interfaces.",
            "output": "A zero-egress architecture prohibits any external internet requests to prevent data leakage.",
        }
    ]

    # Test Alpaca builder
    alpaca = build_alpaca_dataset(pairs)
    assert len(alpaca) == 1
    assert alpaca[0]["instruction"] == "Explain zero-egress architecture."
    assert alpaca[0]["input"] == "Zero-egress systems completely disable external network interfaces."
    assert alpaca[0]["output"].startswith("A zero-egress")

    alpaca_file = tmp_path / "alpaca_dataset.json"
    export_dataset_to_file(alpaca, alpaca_file, format_type="alpaca")
    assert alpaca_file.exists()
    loaded_alpaca = json.loads(alpaca_file.read_text(encoding="utf-8"))
    assert len(loaded_alpaca) == 1
    assert loaded_alpaca[0]["instruction"] == pairs[0]["instruction"]

    # Test ShareGPT builder
    sharegpt = build_sharegpt_dataset(pairs)
    assert len(sharegpt) == 1
    assert "conversations" in sharegpt[0]
    convs = sharegpt[0]["conversations"]
    assert any(c["from"] == "human" for c in convs)
    assert any(c["from"] == "gpt" for c in convs)

    sharegpt_file = tmp_path / "sharegpt_dataset.jsonl"
    export_dataset_to_file(sharegpt, sharegpt_file, format_type="sharegpt")
    assert sharegpt_file.exists()
    lines = [json.loads(line) for line in sharegpt_file.read_text(encoding="utf-8").strip().split("\n")]
    assert len(lines) == 1
    assert lines[0]["conversations"][-1]["value"] == pairs[0]["output"]


@pytest.mark.asyncio
async def test_feedback_api_and_export_lifecycle(tmp_path):
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a session and messages to anchor feedback
        sess_resp = await client.post("/api/v1/sessions", json={"title": "Flywheel Test Session"})
        assert sess_resp.status_code == 200
        session_id = sess_resp.json()["session_id"]

        user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        asst_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        async with AsyncSessionLocal() as db:
            msg_u = DBChatMessage(
                message_id=user_msg_id,
                session_id=session_id,
                role="user",
                content="How do offline LLMs maintain data sovereignty?",
            )
            msg_a = DBChatMessage(
                message_id=asst_msg_id,
                session_id=session_id,
                role="assistant",
                content="Offline LLMs process all weights and activations locally without transmitting data to external servers.",
                citations=[{"citation_id": 1, "text": "Air-gapped models execute inference locally on customer premises."}],
            )
            db.add_all([msg_u, msg_a])
            await db.commit()

        # 2. Submit positive feedback
        fb_pos_payload = {
            "session_id": session_id,
            "message_id": asst_msg_id,
            "rating": 1,
            "feedback_category": "accuracy",
            "citations_approved": [{"citation_id": 1, "text": "Air-gapped models execute inference locally on customer premises."}],
            "is_expert_verified": False,
        }
        resp_pos = await client.post("/api/v1/feedback", json=fb_pos_payload)
        assert resp_pos.status_code == 200
        fb_pos_data = resp_pos.json()
        assert fb_pos_data["rating"] == 1
        assert fb_pos_data["feedback_id"].startswith("fb_")

        # 3. Submit expert-verified correction feedback
        fb_corr_payload = {
            "session_id": session_id,
            "message_id": asst_msg_id,
            "rating": -1,
            "feedback_category": "completeness",
            "expert_correction": "Offline LLMs maintain sovereignty by executing on local hardware with zero network egress and verified air-gapped cryptographic ledgers.",
            "citations_approved": [{"citation_id": 1, "text": "Hardware execution with cryptographic ledgers."}],
            "is_expert_verified": True,
        }
        resp_corr = await client.post("/api/v1/feedback", json=fb_corr_payload)
        assert resp_corr.status_code == 200
        fb_corr_data = resp_corr.json()
        assert fb_corr_data["is_expert_verified"] is True
        assert fb_corr_data["expert_correction"] is not None

        # 4. List feedback
        resp_list = await client.get(f"/api/v1/feedback?session_id={session_id}")
        assert resp_list.status_code == 200
        feedbacks = resp_list.json()
        assert len(feedbacks) >= 2

        # 5. Export training data - Alpaca JSON
        alpaca_export_path = str(tmp_path / "alpaca_export.json")
        resp_alpaca = await client.get(
            f"/api/v1/feedback/export-training-data?format=alpaca&output_path={alpaca_export_path}"
        )
        assert resp_alpaca.status_code == 200
        alpaca_items = resp_alpaca.json()
        assert isinstance(alpaca_items, list)
        assert len(alpaca_items) >= 1
        assert any(item["output"] == fb_corr_payload["expert_correction"] for item in alpaca_items)

        # 6. Export training data - ShareGPT JSONL
        sharegpt_export_path = str(tmp_path / "sharegpt_export.jsonl")
        resp_sharegpt = await client.get(
            f"/api/v1/feedback/export-training-data?format=sharegpt&output_path={sharegpt_export_path}"
        )
        assert resp_sharegpt.status_code == 200
        assert "conversations" in resp_sharegpt.text

        # 7. Test evaluate-triad API endpoint
        triad_payload = {
            "query": "What is air-gap computing?",
            "retrieved_chunks": ["Air-gap computing isolates devices physically and logically from unsecured networks."],
            "answer": "Air-gap computing ensures physical and logical network isolation from external networks."
        }
        triad_resp = await client.post("/api/v1/feedback/evaluate-triad", json=triad_payload)
        assert triad_resp.status_code == 200
        triad_data = triad_resp.json()
        assert 0.0 <= triad_data["context_relevance"] <= 1.0
        assert 0.0 <= triad_data["faithfulness"] <= 1.0
        assert 0.0 <= triad_data["answer_relevance"] <= 1.0
        assert 0.0 <= triad_data["overall_score"] <= 1.0


@pytest.mark.asyncio
async def test_extract_training_pairs_direct():
    """Directly test extract_training_pairs_from_db function."""
    await init_db()
    sess_id = f"sess_pairs_{uuid.uuid4().hex[:8]}"
    u_msg_id = f"msg_u_{uuid.uuid4().hex[:8]}"
    a_msg_id = f"msg_a_{uuid.uuid4().hex[:8]}"
    fb_id = f"fb_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as session:
        chat_sess = DBChatSession(session_id=sess_id, title="Extraction Test")
        u_msg = DBChatMessage(
            message_id=u_msg_id,
            session_id=sess_id,
            role="user",
            content="How does offline embedding generation function?",
        )
        a_msg = DBChatMessage(
            message_id=a_msg_id,
            session_id=sess_id,
            role="assistant",
            content="Offline embedding generation uses local ONNX weights stored in models/embeddings.",
            citations=[{"text": "Local ONNX weights stored in models/embeddings for offline embedding generation."}],
        )
        fb = DBFeedback(
            feedback_id=fb_id,
            message_id=a_msg_id,
            session_id=sess_id,
            rating=1,
            feedback_category="accuracy",
            expert_correction="Offline embedding generation uses local ONNX weights stored in models/embeddings without external network egress.",
            citations_approved=[{"text": "Local ONNX weights stored in models/embeddings for offline embedding generation."}],
            is_expert_verified=True,
        )
        session.add_all([chat_sess, u_msg, a_msg, fb])
        await session.commit()

        pairs = await extract_training_pairs_from_db(session, only_verified=True)
        assert len(pairs) >= 1
        matched = [p for p in pairs if p.get("feedback_id") == fb_id]
        assert len(matched) == 1
        assert matched[0]["instruction"] == "How does offline embedding generation function?"
        assert "without external network egress" in matched[0]["output"]
        assert "models/embeddings" in matched[0]["input"]



