from typing import List
from fastembed import TextEmbedding
from backend.app.core.config import settings


class EmbeddingEngine:
    _instance = None

    def __init__(self, model_name: str = settings.EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = TextEmbedding(model_name=self.model_name)

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
        if not texts:
            return []
        embeddings = list(self._model.embed(texts))
        return [emb.tolist() for emb in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single query string.
        """
        embeddings = list(self._model.embed([query]))
        return embeddings[0].tolist()

