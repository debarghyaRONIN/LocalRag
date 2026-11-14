import logging
import tempfile
from pathlib import Path
from typing import List, Optional
from fastembed import TextEmbedding
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


class EmbeddingEngine:
    _instance = None

    def __init__(self, model_name: str = settings.EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None
        cache_dir = resolve_fastembed_cache_dir()
        try:
            if cache_dir:
                logger.info(f"Loading TextEmbedding ({model_name}) using offline cache at: {cache_dir}")
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=cache_dir,
                    local_files_only=settings.AIRGAP_MODE,
                )
            else:
                self._model = TextEmbedding(model_name=self.model_name)
        except Exception as e:
            logger.warning(f"Failed to initialize TextEmbedding with local cache: {e}. Falling back to default loader...")
            try:
                self._model = TextEmbedding(model_name=self.model_name)
            except Exception as e2:
                logger.error(f"TextEmbedding initialization failed: {e2}")

    @classmethod
    def get_instance(cls) -> "EmbeddingEngine":
        if cls._instance is None:
            cls._instance = EmbeddingEngine()
        return cls._instance

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of text strings into dense vector representations.
        Returns a list of float vectors.
        """
        if not texts or self._model is None:
            return []
        try:
            embeddings = list(self._model.embed(texts))
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            logger.error(f"Error computing text embeddings: {e}")
            return []

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single query string.
        """
        if not query or self._model is None:
            return []
        try:
            embeddings = list(self._model.embed([query]))
            return embeddings[0].tolist() if embeddings else []
        except Exception as e:
            logger.error(f"Error computing query embedding: {e}")
            return []


