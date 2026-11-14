from backend.app.domain.models import SearchCandidate
from backend.app.services.generation.prompts import format_rag_context, build_rag_messages


def test_format_rag_context():
    candidates = [
        SearchCandidate(
            chunk_id="c1",
            parent_id="p1",
            doc_id="d1",
            filename="architecture.pdf",
            page_number=2,
            content="Child text",
            parent_content="Complete section on VRAM memory management and streaming.",
            dense_score=0.92,
            rerank_score=0.88,
        )
    ]

    formatted = format_rag_context(candidates)
    assert '<source id="1"' in formatted
    assert 'file="architecture.pdf"' in formatted
    assert 'page="2"' in formatted
    assert 'Complete section on VRAM memory management' in formatted


def test_build_rag_messages():
    candidates = [
        SearchCandidate(
            chunk_id="c1",
            parent_id="p1",
            doc_id="d1",
            filename="doc.txt",
            page_number=1,
            content="FastEmbed uses ONNX.",
            parent_content="FastEmbed uses ONNX for high-efficiency CPU and GPU inference.",
            dense_score=0.95,
        )
    ]

    messages = build_rag_messages("How does FastEmbed run?", candidates)
    assert len(messages) >= 2
    assert messages[0]["role"] == "system"
    assert "strictly in local enterprise documentation" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "How does FastEmbed run?" in messages[1]["content"]

