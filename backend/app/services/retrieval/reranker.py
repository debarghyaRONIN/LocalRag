import logging
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from fastembed.rerank.cross_encoder import TextCrossEncoder
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def resolve_fastembed_cache_dir() -> Optional[str]:
    """Finds an existing fastembed model cache folder (repo models/, app payload, or temp)."""
    candidates = [
        settings.FASTEMBED_CACHE_DIR,
        settings.BASE_DIR / "models" / "fastembed_cache",
        settings.DATA_DIR / "models" / "fastembed_cache",
        Path(tempfile.gettempdir()) / "fastembed_cache",
    ]
    for c in candidates:
        if c.exists() and any(c.iterdir()):
            return str(c.resolve())
    return None


class RerankerEngine:
    _instance = None

    def __init__(self, model_name: str = settings.RERANKER_MODEL):
        self.model_name = model_name
        self._model = None
        cache_dir = resolve_fastembed_cache_dir()
        try:
            if cache_dir:
                logger.info(f"Loading TextCrossEncoder ({model_name}) using offline cache at: {cache_dir}")
                self._model = TextCrossEncoder(
                    model_name=self.model_name,
                    cache_dir=cache_dir,
                    local_files_only=settings.AIRGAP_MODE,
                )
            else:
                self._model = TextCrossEncoder(model_name=self.model_name)
        except Exception as e:
            logger.warning(f"Failed to initialize TextCrossEncoder with local cache: {e}. Falling back to default loader...")
            try:
                self._model = TextCrossEncoder(model_name=self.model_name)
            except Exception as e2:
                logger.error(f"TextCrossEncoder initialization failed: {e2}")

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
        if self._model is None:
            # Fallback uniform score when cross-encoder is unavailable
            return [1.0] * len(documents)
        try:
            scores = list(self._model.rerank(query=query, documents=documents))
            return [float(s) for s in scores]
        except Exception as e:
            logger.error(f"Error computing rerank scores: {e}")
            return [1.0] * len(documents)

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


