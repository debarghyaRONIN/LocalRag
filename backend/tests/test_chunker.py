from backend.app.services.ingestion.chunkers import HierarchicalChunker, split_text_into_windows
from backend.app.services.ingestion.parsers import ParsedPage


def test_split_text_into_windows():
    text = (
        "Paragraph 1: Production RAG systems require deterministic chunking.\n\n"
        "Paragraph 2: Hybrid retrieval combines dense embeddings with sparse lexical search.\n\n"
        "Paragraph 3: Cross-encoder reranking eliminates false positive context chunks."
    )
    windows = split_text_into_windows(text, chunk_size=100, overlap=20)
    assert len(windows) >= 1
    # Verify all content is represented
    combined = " ".join(windows)
    assert "Production RAG" in combined
    assert "Cross-encoder" in combined


def test_hierarchical_chunker_parent_child_mapping():
    chunker = HierarchicalChunker(
        parent_size=200,
        parent_overlap=30,
        child_size=80,
        child_overlap=15
    )

    doc_id = "test_doc_001"
    sample_text = (
        "Retrieval-Augmented Generation (RAG) is an AI framework that retrieves relevant facts "
        "from an external knowledge base to ground Large Language Models (LLMs). This mitigates "
        "hallucinations and ensures factual reliability in high-stakes enterprise workflows. "
        "When implemented on local hardware, privacy is preserved completely offline."
    )

    pages = [ParsedPage(page_number=1, text=sample_text)]
    parents, children = chunker.chunk_document(doc_id, pages)

    assert len(parents) > 0
    assert len(children) > 0

    # Verify every child has a valid parent_id linking to a parent chunk
    parent_ids = {p.parent_id for p in parents}
    for child in children:
        assert child.parent_id in parent_ids
        assert child.doc_id == doc_id
        assert child.page_number == 1
        assert len(child.content) > 0


def test_split_text_with_overlap_edge_case():
    # When overlap equals chunk_size, it must not hang or loop infinitely
    text = "A" * 500
    windows = split_text_into_windows(text, chunk_size=50, overlap=50)
    assert len(windows) > 0
    assert windows[0] == "A" * 50

