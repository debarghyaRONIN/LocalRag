import pytest
import uuid
from backend.app.domain.models import SearchCandidate
from backend.app.db.models import DBDocument, DBParentChunk
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.services.retrieval.sibling_expander import SiblingContextExpander
from backend.app.services.generation.prompts import format_rag_context


@pytest.mark.asyncio
async def test_sibling_expansion_basic():
    await init_db()

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    parent0_id = f"p0_{uuid.uuid4().hex[:8]}"
    parent1_id = f"p1_{uuid.uuid4().hex[:8]}"
    parent2_id = f"p2_{uuid.uuid4().hex[:8]}"

    # Populate 3 consecutive parent chunks in SQLite
    async with AsyncSessionLocal() as session:
        doc = DBDocument(
            doc_id=doc_id,
            filename="protocol_spec.txt",
            file_hash=uuid.uuid4().hex,
            file_size_bytes=1024,
            mime_type="text/plain",
            clearance_level=1,
        )
        p0 = DBParentChunk(
            parent_id=parent0_id,
            doc_id=doc_id,
            chunk_index=0,
            content="Section 1: Initial Handshake. The node establishes TLS connection.",
            token_count=15,
            clearance_level=1,
        )
        p1 = DBParentChunk(
            parent_id=parent1_id,
            doc_id=doc_id,
            chunk_index=1,
            content="Section 2: Authentication Core. Ephemeral tokens expire in 60 seconds.",
            token_count=16,
            clearance_level=1,
        )
        p2 = DBParentChunk(
            parent_id=parent2_id,
            doc_id=doc_id,
            chunk_index=2,
            content="Section 3: Teardown. All session keys are scrubbed from RAM.",
            token_count=15,
            clearance_level=1,
        )
        session.add_all([doc, p0, p1, p2])
        await session.commit()

    # Candidate retrieved is Chunk 1
    cand = SearchCandidate(
        chunk_id=f"c1_{uuid.uuid4().hex[:8]}",
        parent_id=parent1_id,
        doc_id=doc_id,
        filename="protocol_spec.txt",
        page_number=1,
        content="Ephemeral tokens expire in 60 seconds.",
        parent_content="Section 2: Authentication Core. Ephemeral tokens expire in 60 seconds.",
        clearance_level=1,
        dense_score=0.92,
        rrf_score=0.033,
    )

    expander = SiblingContextExpander()
    results = await expand_expander_test(expander, [cand], clearance=1)

    assert len(results) == 1
    c = results[0]
    assert c.preceding_context is not None
    assert "Section 1: Initial Handshake" in c.preceding_context
    assert c.following_context is not None
    assert "Section 3: Teardown" in c.following_context
    assert "Section 2: Authentication Core" in c.stitched_context

    # Verify formatted context utilizes stitched context
    formatted = format_rag_context([c])
    assert "Preceding Context" in formatted
    assert "Following Context" in formatted


@pytest.mark.asyncio
async def test_sibling_clearance_rbac():
    await init_db()

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    parent0_id = f"p0_{uuid.uuid4().hex[:8]}"
    parent1_id = f"p1_{uuid.uuid4().hex[:8]}"
    parent2_id = f"p2_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as session:
        doc = DBDocument(
            doc_id=doc_id,
            filename="classified_briefing.txt",
            file_hash=uuid.uuid4().hex,
            file_size_bytes=1024,
            mime_type="text/plain",
            clearance_level=4,
        )
        p0 = DBParentChunk(
            parent_id=parent0_id,
            doc_id=doc_id,
            chunk_index=0,
            content="Public Introduction.",
            clearance_level=1,
        )
        p1 = DBParentChunk(
            parent_id=parent1_id,
            doc_id=doc_id,
            chunk_index=1,
            content="Public Details.",
            clearance_level=1,
        )
        p2 = DBParentChunk(
            parent_id=parent2_id,
            doc_id=doc_id,
            chunk_index=2,
            content="TOP SECRET: Nuclear launch facility coordinates.",
            clearance_level=4,  # Level 4 classified
        )
        session.add_all([doc, p0, p1, p2])
        await session.commit()

    cand = SearchCandidate(
        chunk_id="c1",
        parent_id=parent1_id,
        doc_id=doc_id,
        filename="classified_briefing.txt",
        page_number=1,
        content="Public Details.",
        parent_content="Public Details.",
        clearance_level=1,
    )

    expander = SiblingContextExpander()
    # User with clearance 1 should NOT receive chunk 2 (clearance 4) in following context
    results = await expand_expander_test(expander, [cand], clearance=1)
    c = results[0]
    assert c.following_context is None
    assert "TOP SECRET" not in (c.stitched_context or "")


@pytest.mark.asyncio
async def test_sibling_deduplication():
    await init_db()

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    p0_id = f"p0_{uuid.uuid4().hex[:8]}"
    p1_id = f"p1_{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as session:
        doc = DBDocument(
            doc_id=doc_id,
            filename="doc_dedup.txt",
            file_hash=uuid.uuid4().hex,
            file_size_bytes=1024,
            mime_type="text/plain",
            clearance_level=1,
        )
        p0 = DBParentChunk(parent_id=p0_id, doc_id=doc_id, chunk_index=0, content="Content A", clearance_level=1)
        p1 = DBParentChunk(parent_id=p1_id, doc_id=doc_id, chunk_index=1, content="Content B", clearance_level=1)
        session.add_all([doc, p0, p1])
        await session.commit()

    cand0 = SearchCandidate(chunk_id="c0", parent_id=p0_id, doc_id=doc_id, filename="doc_dedup.txt", page_number=1, content="A", parent_content="Content A")
    cand1 = SearchCandidate(chunk_id="c1", parent_id=p1_id, doc_id=doc_id, filename="doc_dedup.txt", page_number=1, content="B", parent_content="Content B")

    expander = SiblingContextExpander()
    # Both candidates are in the retrieval set
    results = await expand_expander_test(expander, [cand0, cand1], clearance=1)

    # cand0 should NOT include cand1 as following context because cand1 is already a primary result
    assert results[0].following_context is None
    # cand1 should NOT include cand0 as preceding context
    assert results[1].preceding_context is None


async def expand_expander_test(expander, cands, clearance):
    return await expander.expand_candidates(candidates=cands, user_clearance=clearance)

