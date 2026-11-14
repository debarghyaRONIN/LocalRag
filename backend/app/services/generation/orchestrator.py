import time
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from backend.app.core.config import settings
from backend.app.core.security import sanitize_query, detect_prompt_injection
from backend.app.domain.models import Citation, QueryResponse, SearchCandidate
from backend.app.services.retrieval.hybrid_engine import HybridRetrievalEngine
from backend.app.services.retrieval.sibling_expander import SiblingContextExpander
from backend.app.services.generation.prompts import build_rag_messages
from backend.app.services.generation.llm_client import VLLMClient


class RAGOrchestrator:
    def __init__(
        self,
        retrieval_engine: Optional[HybridRetrievalEngine] = None,
        llm_client: Optional[VLLMClient] = None,
        sibling_expander: Optional[SiblingContextExpander] = None,
    ):
        self.retrieval_engine = retrieval_engine or HybridRetrievalEngine()
        self.llm_client = llm_client or VLLMClient()
        self.sibling_expander = sibling_expander or SiblingContextExpander()

    def _build_citations(self, candidates: List[SearchCandidate]) -> List[Citation]:
        citations = []
        for idx, cand in enumerate(candidates, start=1):
            citations.append(
                Citation(
                    citation_id=idx,
                    chunk_id=cand.chunk_id,
                    parent_id=cand.parent_id,
                    doc_id=cand.doc_id,
                    filename=cand.filename,
                    page_number=cand.page_number,
                    exact_quote=cand.content,
                    relevance_score=cand.rerank_score or cand.rrf_score,
                    parent_content=cand.parent_content,
                    stitched_context=cand.stitched_context,
                )
            )
        return citations

    async def execute_query(
        self,
        query: str,
        top_k: int = settings.RERANK_TOP_K,
        min_score: float = settings.RERANK_MIN_SCORE,
        chat_history: Optional[List[dict]] = None,
        user_clearance: Optional[int] = None,
        user_departments: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> QueryResponse:
        """Non-streaming query execution with RBAC clearance filtering."""
        t_total_start = time.perf_counter()
        clean_query = sanitize_query(query)

        if detect_prompt_injection(clean_query):
            return QueryResponse(
                query=clean_query,
                answer="Query contains invalid or disallowed prompt patterns.",
                citations=[],
                retrieved_chunks_count=0,
                latency_ms={"total_ms": (time.perf_counter() - t_total_start) * 1000},
                model_used=self.llm_client.model,
            )

        # Retrieve and rerank in worker thread to prevent event loop starvation
        candidates, latency_ms = await asyncio.to_thread(
            self.retrieval_engine.retrieve_and_rerank,
            query=clean_query,
            top_k=top_k,
            min_score=min_score,
            user_clearance=user_clearance,
            user_departments=user_departments,
        )

        # Expand adjacent sibling context (i - 1 and i + 1)
        candidates = await self.sibling_expander.expand_candidates(
            candidates=candidates,
            user_clearance=user_clearance,
            user_departments=user_departments,
        )

        citations = self._build_citations(candidates)
        messages = build_rag_messages(clean_query, candidates, chat_history)

        # Generate
        t_gen_start = time.perf_counter()
        answer = await self.llm_client.complete_chat(messages, model=model)
        latency_ms["generation_ms"] = (time.perf_counter() - t_gen_start) * 1000
        latency_ms["total_ms"] = (time.perf_counter() - t_total_start) * 1000

        return QueryResponse(
            query=clean_query,
            answer=answer,
            citations=citations,
            retrieved_chunks_count=len(candidates),
            latency_ms=latency_ms,
            model_used=model or self.llm_client.model,
        )

    async def stream_query(
        self,
        query: str,
        top_k: int = settings.RERANK_TOP_K,
        min_score: float = settings.RERANK_MIN_SCORE,
        chat_history: Optional[List[dict]] = None,
        user_clearance: Optional[int] = None,
        user_departments: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming query execution emitting SSE data events:
        1. Tokens as generated
        2. Citations payload
        3. Detailed latency breakdown
        """
        t_total_start = time.perf_counter()
        clean_query = sanitize_query(query)

        if detect_prompt_injection(clean_query):
            err_msg = json.dumps({"type": "token", "content": "Query contains invalid or disallowed prompt patterns."})
            yield f"data: {err_msg}\n\n"
            yield "data: [DONE]\n\n"
            return

        # 1. Hybrid Retrieval & Cross-Encoder Reranking in worker thread with RBAC
        candidates, latency_ms = await asyncio.to_thread(
            self.retrieval_engine.retrieve_and_rerank,
            query=clean_query,
            top_k=top_k,
            min_score=min_score,
            user_clearance=user_clearance,
            user_departments=user_departments,
        )

        # Expand adjacent sibling context (i - 1 and i + 1)
        candidates = await self.sibling_expander.expand_candidates(
            candidates=candidates,
            user_clearance=user_clearance,
            user_departments=user_departments,
        )

        citations = self._build_citations(candidates)
        messages = build_rag_messages(clean_query, candidates, chat_history)

        # 2. Stream generation
        t_gen_start = time.perf_counter()
        first_token = True

        async for token in self.llm_client.stream_chat(messages, model=model):
            if first_token:
                ttft_ms = (time.perf_counter() - t_gen_start) * 1000
                latency_ms["ttft_ms"] = ttft_ms
                first_token = False

            event_data = json.dumps({"type": "token", "content": token})
            yield f"data: {event_data}\n\n"

        latency_ms["generation_ms"] = (time.perf_counter() - t_gen_start) * 1000
        latency_ms["total_ms"] = (time.perf_counter() - t_total_start) * 1000

        # 3. Emit structured citations event
        citations_data = [c.model_dump() for c in citations]
        citations_event = json.dumps({"type": "citations", "data": citations_data})
        yield f"data: {citations_event}\n\n"

        # 4. Emit latency metrics event
        latency_event = json.dumps({"type": "latency", "data": latency_ms})
        yield f"data: {latency_event}\n\n"

        yield "data: [DONE]\n\n"

