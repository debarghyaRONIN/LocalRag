import time
import re
from typing import List, Dict, Tuple, Optional
from backend.app.core.config import settings
from backend.app.domain.models import SearchCandidate
from backend.app.services.retrieval.embeddings import EmbeddingEngine
from backend.app.services.retrieval.reranker import RerankerEngine
from backend.app.services.retrieval.vector_store import QdrantVectorStore
from backend.app.services.retrieval.fts_store import FTS5BM25Store


def tokenize_for_bm25(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens for BM25 term matching."""
    return re.findall(r"\b\w+\b", text.lower())


class HybridRetrievalEngine:
    def __init__(
        self,
        vector_store: Optional[QdrantVectorStore] = None,
        embedder: Optional[EmbeddingEngine] = None,
        reranker: Optional[RerankerEngine] = None,
        fts_store: Optional[FTS5BM25Store] = None,
        rrf_k: int = settings.RRF_K,
    ):
        self.vector_store = vector_store or QdrantVectorStore.get_instance()
        self.embedder = embedder or EmbeddingEngine.get_instance()
        self.reranker = reranker or RerankerEngine.get_instance()
        self.fts_store = fts_store or FTS5BM25Store.get_instance()
        self.rrf_k = rrf_k

    def retrieve_and_rerank(
        self,
        query: str,
        top_k: int = settings.RERANK_TOP_K,
        min_score: float = settings.RERANK_MIN_SCORE,
        doc_id: Optional[str] = None,
        user_clearance: Optional[int] = None,
        user_departments: Optional[List[str]] = None,
        user_department: Optional[str] = None,
    ) -> Tuple[List[SearchCandidate], Dict[str, float]]:
        """
        True Dual-Engine Hybrid Retrieval Pipeline:
        1. Query dense embedding + Qdrant cosine vector search (semantic similarity)
        2. SQLite FTS5 BM25 search (exact lexical keywords, acronyms, identifiers)
        3. Reciprocal Rank Fusion (RRF) merging dense and sparse ranked lists
        4. Cross-Encoder reranking with confidence threshold
        Returns: (ranked_candidates, latency_ms_breakdown)
        """
        latencies = {}

        # Stage 1: Dense Embedding
        t0 = time.perf_counter()
        query_vector = []
        try:
            query_vector = self.embedder.embed_query(query)
        except Exception as e:
            logger.warning(f"Dense query embedding failed: {e}")
        latencies["embed_ms"] = (time.perf_counter() - t0) * 1000

        # Stage 2A: Dense Vector Retrieval (Qdrant)
        t1 = time.perf_counter()
        dense_hits = []
        if query_vector:
            try:
                dense_hits = self.vector_store.search_dense(
                    query_vector=query_vector,
                    top_k=settings.RETRIEVAL_TOP_K,
                    doc_id=doc_id,
                    user_clearance=user_clearance,
                    user_departments=user_departments,
                    user_department=user_department,
                )
            except Exception as e:
                logger.warning(f"Dense vector search failed: {e}")

        # Stage 2B: Full-Text BM25 Lexical Retrieval (SQLite FTS5)
        sparse_hits = self.fts_store.search_bm25(
            query=query,
            top_k=settings.RETRIEVAL_TOP_K,
            user_clearance=user_clearance,
            doc_id=doc_id,
        )
        latencies["retrieval_ms"] = (time.perf_counter() - t1) * 1000

        if not dense_hits and not sparse_hits:
            return [], latencies

        # Stage 2C: Reciprocal Rank Fusion (RRF) of Dense + Sparse results
        candidates_map: Dict[str, SearchCandidate] = {}

        # Add Dense hits to RRF pool
        for rank, hit in enumerate(dense_hits):
            cid = hit["chunk_id"]
            dense_rrf = 1.0 / (self.rrf_k + rank + 1)

            candidate = SearchCandidate(
                chunk_id=cid,
                parent_id=hit["parent_id"],
                doc_id=hit["doc_id"],
                filename=hit["filename"],
                page_number=hit["page_number"],
                content=hit["content"],
                parent_content=hit.get("parent_content") or hit["content"],
                clearance_level=hit.get("clearance_level", 1),
                allowed_departments=hit.get("allowed_departments", []),
                dense_score=hit["score"],
                sparse_score=0.0,
                rrf_score=dense_rrf,
            )
            candidates_map[cid] = candidate

        # Merge Sparse BM25 hits into RRF pool
        for rank, s_hit in enumerate(sparse_hits):
            pid = s_hit["parent_id"]
            sparse_rrf = 1.0 / (self.rrf_k + rank + 1)

            # Match against existing candidate by parent_id or chunk_id
            matched_candidate = None
            for c in candidates_map.values():
                if c.parent_id == pid or c.chunk_id == pid:
                    matched_candidate = c
                    break

            if matched_candidate:
                matched_candidate.sparse_score = s_hit["bm25_score"]
                matched_candidate.rrf_score += sparse_rrf
            else:
                # Discovered via BM25 keyword matching (not found in top dense hits!)
                bm25_candidate = SearchCandidate(
                    chunk_id=pid,
                    parent_id=pid,
                    doc_id=s_hit["doc_id"],
                    filename=s_hit["filename"],
                    page_number=1,
                    content=s_hit["content"][:300],
                    parent_content=s_hit["content"],
                    clearance_level=s_hit.get("clearance_level", 1),
                    allowed_departments=[],
                    dense_score=0.0,
                    sparse_score=s_hit["bm25_score"],
                    rrf_score=sparse_rrf,
                )
                candidates_map[pid] = bm25_candidate

        # Sort by unified RRF score and take top candidates for Cross-Encoder
        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda c: c.rrf_score,
            reverse=True
        )[: settings.RETRIEVAL_TOP_K]

        # Stage 3: ONNX Cross-Encoder Reranking
        t2 = time.perf_counter()
        doc_texts = [c.content for c in sorted_candidates]
        ranked_pairs = self.reranker.rank_and_filter(
            query=query,
            documents=doc_texts,
            top_k=top_k,
            min_score=min_score
        )
        latencies["rerank_ms"] = (time.perf_counter() - t2) * 1000

        final_results: List[SearchCandidate] = []
        for idx, score in ranked_pairs:
            cand = sorted_candidates[idx]
            cand.rerank_score = score
            final_results.append(cand)

        return final_results, latencies

