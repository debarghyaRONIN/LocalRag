from typing import List, Tuple
from fastembed.rerank.cross_encoder import TextCrossEncoder
from backend.app.core.config import settings


class RerankerEngine:
    _instance = None

    def __init__(self, model_name: str = settings.RERANKER_MODEL):
        self.model_name = model_name
        self._model = TextCrossEncoder(model_name=self.model_name)

    @classmethod
    def get_instance(cls) -> "RerankerEngine":
        if cls._instance is None:
            cls._instance = RerankerEngine()
        return cls._instance

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        """
        Compute cross-encoder relevance scores for (query, document) pairs.
        Returns a list of float scores corresponding to each document.
        """
        if not documents:
            return []
        scores = list(self._model.rerank(query=query, documents=documents))
        return [float(s) for s in scores]

    def rank_and_filter(
        self,
        query: str,
        documents: List[str],
        top_k: int = settings.RERANK_TOP_K,
        min_score: float = settings.RERANK_MIN_SCORE
    ) -> List[Tuple[int, float]]:
        """
        Reranks documents, filters out candidates below min_score,
        and returns list of (original_index, score) sorted by score descending.
        """
        if not documents:
            return []

        scores = self.rerank(query, documents)
        scored_pairs = [
            (idx, score)
            for idx, score in enumerate(scores)
            if score >= min_score
        ]

        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return scored_pairs[:top_k]

