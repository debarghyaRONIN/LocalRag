import logging
from typing import List, Dict, Optional, Set
from sqlalchemy import select
from backend.app.core.config import settings
from backend.app.domain.models import SearchCandidate
from backend.app.db.models import DBParentChunk
from backend.app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class SiblingContextExpander:
    """
    Adjacent Sibling Context Expansion Service.
    Stitches preceding (i - 1) and following (i + 1) parent chunk context into retrieved candidates
    with boundary deduplication, RBAC clearance enforcement, and token budget management.
    """

    def __init__(self, max_sibling_chars: int = 600):
        self.max_sibling_chars = max_sibling_chars

    async def expand_candidates(
        self,
        candidates: List[SearchCandidate],
        user_clearance: Optional[int] = None,
        user_departments: Optional[List[str]] = None,
    ) -> List[SearchCandidate]:
        """
        Enrich search candidates with preceding and succeeding adjacent sibling chunks.
        Prevents context fragmentation across chunk boundaries while preserving strict air-gap RBAC.
        """
        if not candidates:
            return []

        # Group candidates by document ID
        doc_candidates: Dict[str, List[SearchCandidate]] = {}
        candidate_parent_ids: Set[str] = set()

        for c in candidates:
            doc_candidates.setdefault(c.doc_id, []).append(c)
            candidate_parent_ids.add(c.parent_id)

        effective_clearance = user_clearance if user_clearance is not None else 1
        user_dept_set = set(user_departments or [])

        async with AsyncSessionLocal() as session:
            for doc_id, cands in doc_candidates.items():
                try:
                    # 1. Fetch current parent chunk records to identify chunk_index
                    parent_ids = [c.parent_id for c in cands]
                    stmt = select(DBParentChunk).where(
                        DBParentChunk.doc_id == doc_id,
                        DBParentChunk.parent_id.in_(parent_ids)
                    )
                    res = await session.execute(stmt)
                    current_parents = {p.parent_id: p for p in res.scalars().all()}

                    # 2. Determine target sibling indices
                    indices_to_fetch = set()
                    cand_to_index: Dict[str, int] = {}
                    for c in cands:
                        p_record = current_parents.get(c.parent_id)
                        if p_record is not None:
                            idx = p_record.chunk_index
                            cand_to_index[c.parent_id] = idx
                            c.parent_index = idx
                            if idx > 0:
                                indices_to_fetch.add(idx - 1)
                            indices_to_fetch.add(idx + 1)

                    if not indices_to_fetch:
                        for c in cands:
                            c.stitched_context = c.parent_content or c.content
                        continue

                    # 3. Query all potential sibling chunks in one batch
                    sibling_stmt = select(DBParentChunk).where(
                        DBParentChunk.doc_id == doc_id,
                        DBParentChunk.chunk_index.in_(indices_to_fetch)
                    )
                    sib_res = await session.execute(sibling_stmt)
                    sibling_map: Dict[int, DBParentChunk] = {
                        p.chunk_index: p for p in sib_res.scalars().all()
                    }

                    # Set of chunk indices already represented in primary search candidates
                    primary_indices = set(cand_to_index.values())

                    # 4. Stitch adjacent context into each candidate
                    for c in cands:
                        curr_idx = cand_to_index.get(c.parent_id)
                        if curr_idx is None:
                            c.stitched_context = c.parent_content or c.content
                            continue

                        prev_idx = curr_idx - 1
                        next_idx = curr_idx + 1

                        preceding_text = ""
                        following_text = ""

                        # Evaluate preceding sibling (i - 1)
                        # Avoid duplicating if another retrieved candidate is already chunk i - 1
                        if prev_idx >= 0 and prev_idx not in primary_indices and prev_idx in sibling_map:
                            prev_chunk = sibling_map[prev_idx]
                            # Check RBAC
                            if prev_chunk.clearance_level <= effective_clearance:
                                p_depts = prev_chunk.allowed_departments or []
                                if not p_depts or not user_dept_set or bool(set(p_depts) & user_dept_set):
                                    raw_prev = prev_chunk.content.strip()
                                    if len(raw_prev) > self.max_sibling_chars:
                                        preceding_text = "... " + raw_prev[-self.max_sibling_chars:]
                                    else:
                                        preceding_text = raw_prev

                        # Evaluate following sibling (i + 1)
                        # Avoid duplicating if another retrieved candidate is already chunk i + 1
                        if next_idx not in primary_indices and next_idx in sibling_map:
                            next_chunk = sibling_map[next_idx]
                            # Check RBAC
                            if next_chunk.clearance_level <= effective_clearance:
                                n_depts = next_chunk.allowed_departments or []
                                if not n_depts or not user_dept_set or bool(set(n_depts) & user_dept_set):
                                    raw_next = next_chunk.content.strip()
                                    if len(raw_next) > self.max_sibling_chars:
                                        following_text = raw_next[:self.max_sibling_chars] + " ..."
                                    else:
                                        following_text = raw_next

                        c.preceding_context = preceding_text or None
                        c.following_context = following_text or None

                        # Assemble stitched context
                        stitched_parts = []
                        if preceding_text:
                            stitched_parts.append(f"[Preceding Context - Section {prev_idx + 1}]\n{preceding_text}")

                        core_text = c.parent_content or c.content
                        stitched_parts.append(f"[Core Retrieved Section {curr_idx + 1}]\n{core_text}")

                        if following_text:
                            stitched_parts.append(f"[Following Context - Section {next_idx + 1}]\n{following_text}")

                        c.stitched_context = "\n\n".join(stitched_parts)

                except Exception as e:
                    logger.warning(f"Sibling expansion failed for doc {doc_id}: {e}")
                    for c in cands:
                        if not c.stitched_context:
                            c.stitched_context = c.parent_content or c.content

        return candidates

