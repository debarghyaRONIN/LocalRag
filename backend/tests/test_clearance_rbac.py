import uuid
import pytest
from pathlib import Path

from backend.app.db.models import ClearanceLevel, DBDocument, DBParentChunk
from backend.app.db.session import AsyncSessionLocal, init_db
from backend.app.domain.models import ChildChunk, ParentChunk
from backend.app.services.retrieval.vector_store import QdrantVectorStore


@pytest.mark.asyncio
async def test_clearance_level_constants_and_model_defaults():
    """Verify clearance level enumeration values and ORM model defaults in SQLite."""
    assert ClearanceLevel.PUBLIC == 1
    assert ClearanceLevel.INTERNAL == 2
    assert ClearanceLevel.CONFIDENTIAL == 3
    assert ClearanceLevel.TOP_SECRET == 4

    await init_db()
    async with AsyncSessionLocal() as session:
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        doc = DBDocument(
            doc_id=doc_id,
            filename="clearance_test_file.txt",
            file_hash=f"hash_{uuid.uuid4().hex[:12]}",
            file_size_bytes=1024,
            mime_type="text/plain",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

        assert doc.clearance_level == ClearanceLevel.PUBLIC
        assert doc.allowed_departments == []

        parent_id = f"p_{uuid.uuid4().hex[:8]}"
        parent = DBParentChunk(
            parent_id=parent_id,
            doc_id=doc_id,
            chunk_index=0,
            content="Parent chunk text with default clearance level",
        )
        session.add(parent)
        await session.commit()
        await session.refresh(parent)

        assert parent.clearance_level == ClearanceLevel.PUBLIC
        assert parent.allowed_departments == []



def test_clearance_level_filtering_and_rbac_exclusion(tmp_path: Path):
    """
    Test clearance level filtering:
    Users must never retrieve any document or chunk above their clearance level.
    """
    store = QdrantVectorStore(storage_path=str(tmp_path / "rbac_clearance_store"))

    child_chunks = [
        ChildChunk(
            chunk_id="chk_lvl1_public",
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="Public safety notices and generic office guidelines.",
            token_count=10,
            clearance_level=ClearanceLevel.PUBLIC,  # 1
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chk_lvl2_internal",
            parent_id="p1",
            doc_id="d1",
            chunk_index=1,
            content="Internal engineering architecture roadmap and sprints.",
            token_count=10,
            clearance_level=ClearanceLevel.INTERNAL,  # 2
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chk_lvl3_confidential",
            parent_id="p1",
            doc_id="d1",
            chunk_index=2,
            content="Confidential financial statements and merger negotiations.",
            token_count=10,
            clearance_level=ClearanceLevel.CONFIDENTIAL,  # 3
            allowed_departments=[],
        ),
        ChildChunk(
            chunk_id="chk_lvl4_top_secret",
            parent_id="p1",
            doc_id="d1",
            chunk_index=3,
            content="Top secret hardware cryptographic key escrow blueprints.",
            token_count=10,
            clearance_level=ClearanceLevel.TOP_SECRET,  # 4
            allowed_departments=[],
        ),
    ]

    parent_map = {
        "p1": ParentChunk(
            parent_id="p1",
            doc_id="d1",
            chunk_index=0,
            content="Master document covering security clearances.",
            token_count=40,
        )
    }

    dummy_vector = [0.15] * store.vector_size
    embeddings = [dummy_vector for _ in child_chunks]

    store.upsert_chunks(
        child_chunks=child_chunks,
        parent_map=parent_map,
        embeddings=embeddings,
        filename="clearance_test_document.pdf",
    )

    # 1. Level 1 (Public): must ONLY retrieve Level 1; Level 2, 3, 4 strictly excluded
    res_l1 = store.search_dense(query_vector=dummy_vector, top_k=10, user_clearance=ClearanceLevel.PUBLIC)
    ids_l1 = {r["chunk_id"] for r in res_l1}
    assert ids_l1 == {"chk_lvl1_public"}
    assert "chk_lvl2_internal" not in ids_l1
    assert "chk_lvl3_confidential" not in ids_l1
    assert "chk_lvl4_top_secret" not in ids_l1

    # 2. Level 2 (Internal): retrieves Level 1 and 2; Level 3 and 4 strictly excluded
    res_l2 = store.search_dense(query_vector=dummy_vector, top_k=10, user_clearance=ClearanceLevel.INTERNAL)
    ids_l2 = {r["chunk_id"] for r in res_l2}
    assert ids_l2 == {"chk_lvl1_public", "chk_lvl2_internal"}
    assert "chk_lvl3_confidential" not in ids_l2
    assert "chk_lvl4_top_secret" not in ids_l2

    # 3. Level 3 (Confidential): retrieves Levels 1, 2, and 3; Level 4 strictly excluded
    res_l3 = store.search_dense(query_vector=dummy_vector, top_k=10, user_clearance=ClearanceLevel.CONFIDENTIAL)
    ids_l3 = {r["chunk_id"] for r in res_l3}
    assert ids_l3 == {"chk_lvl1_public", "chk_lvl2_internal", "chk_lvl3_confidential"}
    assert "chk_lvl4_top_secret" not in ids_l3

    # 4. Level 4 (Top Secret): retrieves all levels
    res_l4 = store.search_dense(query_vector=dummy_vector, top_k=10, user_clearance=ClearanceLevel.TOP_SECRET)
    ids_l4 = {r["chunk_id"] for r in res_l4}
    assert ids_l4 == {
        "chk_lvl1_public",
        "chk_lvl2_internal",
        "chk_lvl3_confidential",
        "chk_lvl4_top_secret",
    }


def test_department_rbac_filtering_and_exclusion(tmp_path: Path):
    """
    Test department-based RBAC filtering:
    - Empty allowed_departments = open to everyone.
    - Department-tagged chunks = only accessible if user belongs to an allowed department.
    """
    store = QdrantVectorStore(storage_path=str(tmp_path / "rbac_dept_store"))

    child_chunks = [
        ChildChunk(
            chunk_id="chk_open_dept",
            parent_id="p_dept",
            doc_id="d_dept",
            chunk_index=0,
            content="Company-wide benefits and leave policies.",
            token_count=10,
            clearance_level=1,
            allowed_departments=[],  # Open to all
        ),
        ChildChunk(
            chunk_id="chk_engineering_only",
            parent_id="p_dept",
            doc_id="d_dept",
            chunk_index=1,
            content="Internal source code repository credentials and CI/CD keys.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["engineering"],
        ),
        ChildChunk(
            chunk_id="chk_finance_only",
            parent_id="p_dept",
            doc_id="d_dept",
            chunk_index=2,
            content="Corporate payroll breakdown and executive equity allocations.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["finance"],
        ),
        ChildChunk(
            chunk_id="chk_legal_and_compliance",
            parent_id="p_dept",
            doc_id="d_dept",
            chunk_index=3,
            content="Litigation risk analysis and regulatory compliance audits.",
            token_count=10,
            clearance_level=1,
            allowed_departments=["legal", "compliance"],
        ),
    ]

    parent_map = {
        "p_dept": ParentChunk(
            parent_id="p_dept",
            doc_id="d_dept",
            chunk_index=0,
            content="Departmental policies parent chunk.",
            token_count=40,
        )
    }

    dummy_vector = [0.25] * store.vector_size
    embeddings = [dummy_vector for _ in child_chunks]

    store.upsert_chunks(
        child_chunks=child_chunks,
        parent_map=parent_map,
        embeddings=embeddings,
        filename="departmental_docs.pdf",
    )

    # 1. User from "engineering": gets open chunk + engineering only; finance and legal excluded
    res_eng = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_department="engineering",
    )
    ids_eng = {r["chunk_id"] for r in res_eng}
    assert "chk_open_dept" in ids_eng
    assert "chk_engineering_only" in ids_eng
    assert "chk_finance_only" not in ids_eng
    assert "chk_legal_and_compliance" not in ids_eng

    # 2. User from "finance": gets open chunk + finance only
    res_fin = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_departments=["finance"],
    )
    ids_fin = {r["chunk_id"] for r in res_fin}
    assert "chk_open_dept" in ids_fin
    assert "chk_finance_only" in ids_fin
    assert "chk_engineering_only" not in ids_fin
    assert "chk_legal_and_compliance" not in ids_fin

    # 3. User with multiple departments ["legal", "sales"]: matches open + legal_and_compliance
    res_legal = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_departments=["legal", "sales"],
    )
    ids_legal = {r["chunk_id"] for r in res_legal}
    assert "chk_open_dept" in ids_legal
    assert "chk_legal_and_compliance" in ids_legal
    assert "chk_engineering_only" not in ids_legal
    assert "chk_finance_only" not in ids_legal

    # 4. User with no department credentials: only gets open chunk
    res_none = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_departments=[],
    )
    ids_none = {r["chunk_id"] for r in res_none}
    assert ids_none == {"chk_open_dept"}


def test_combined_clearance_and_department_rbac(tmp_path: Path):
    """
    Test dual-constraint RBAC:
    Both clearance level AND department match must be satisfied.
    A user with high clearance cannot see documents in an unauthorized department.
    A user in the correct department cannot see documents above their clearance level.
    """
    store = QdrantVectorStore(storage_path=str(tmp_path / "rbac_combined_store"))

    child_chunks = [
        ChildChunk(
            chunk_id="chk_top_secret_eng",
            parent_id="p_comb",
            doc_id="d_comb",
            chunk_index=0,
            content="Top Secret engineering stealth aircraft schematics.",
            token_count=10,
            clearance_level=ClearanceLevel.TOP_SECRET,  # 4
            allowed_departments=["engineering"],
        ),
        ChildChunk(
            chunk_id="chk_internal_eng",
            parent_id="p_comb",
            doc_id="d_comb",
            chunk_index=1,
            content="Internal engineering coding conventions.",
            token_count=10,
            clearance_level=ClearanceLevel.INTERNAL,  # 2
            allowed_departments=["engineering"],
        ),
        ChildChunk(
            chunk_id="chk_top_secret_finance",
            parent_id="p_comb",
            doc_id="d_comb",
            chunk_index=2,
            content="Top Secret finance state treasury reserve balances.",
            token_count=10,
            clearance_level=ClearanceLevel.TOP_SECRET,  # 4
            allowed_departments=["finance"],
        ),
    ]

    parent_map = {
        "p_comb": ParentChunk(
            parent_id="p_comb",
            doc_id="d_comb",
            chunk_index=0,
            content="Combined test parent chunk.",
            token_count=30,
        )
    }

    dummy_vector = [0.35] * store.vector_size
    embeddings = [dummy_vector for _ in child_chunks]

    store.upsert_chunks(
        child_chunks=child_chunks,
        parent_map=parent_map,
        embeddings=embeddings,
        filename="combined_rbac.pdf",
    )

    # Case A: User is Top Secret (4) BUT department is finance:
    # Must NOT see chk_top_secret_eng or chk_internal_eng! Only chk_top_secret_finance.
    res_ts_fin = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.TOP_SECRET,
        user_departments=["finance"],
    )
    ids_ts_fin = {r["chunk_id"] for r in res_ts_fin}
    assert "chk_top_secret_finance" in ids_ts_fin
    assert "chk_top_secret_eng" not in ids_ts_fin
    assert "chk_internal_eng" not in ids_ts_fin

    # Case B: User is Internal (2) in engineering:
    # Must see chk_internal_eng BUT NOT chk_top_secret_eng (clearance too low) and NOT finance!
    res_int_eng = store.search_dense(
        query_vector=dummy_vector,
        top_k=10,
        user_clearance=ClearanceLevel.INTERNAL,
        user_departments=["engineering"],
    )
    ids_int_eng = {r["chunk_id"] for r in res_int_eng}
    assert ids_int_eng == {"chk_internal_eng"}
    assert "chk_top_secret_eng" not in ids_int_eng
    assert "chk_top_secret_finance" not in ids_int_eng
