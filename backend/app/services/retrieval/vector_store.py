import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    Range,
    HnswConfigDiff,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
)
from backend.app.core.config import settings
from backend.app.domain.models import ChildChunk, ParentChunk


class QdrantVectorStore:
    _instance = None

    def __init__(
        self,
        client: Optional[QdrantClient] = None,
        storage_path: Optional[str] = None,
        hnsw_m: Optional[int] = None,
        hnsw_ef_construct: Optional[int] = None,
        enable_quantization: Optional[bool] = None,
        on_disk: Optional[bool] = None,
    ):
        if client:
            self.client = client
        elif settings.QDRANT_URL:
            self.client = QdrantClient(url=settings.QDRANT_URL)
        else:
            path = storage_path or str(settings.QDRANT_STORAGE_DIR)
            self.client = QdrantClient(path=path)

        self.collection_name = settings.QDRANT_COLLECTION
        self.vector_size = settings.QDRANT_VECTOR_SIZE
        self.hnsw_m = hnsw_m if hnsw_m is not None else getattr(settings, "QDRANT_HNSW_M", 16)
        self.hnsw_ef_construct = hnsw_ef_construct if hnsw_ef_construct is not None else getattr(settings, "QDRANT_HNSW_EF_CONSTRUCT", 100)
        self.enable_quantization = (
            enable_quantization
            if enable_quantization is not None
            else getattr(settings, "QDRANT_ENABLE_SCALAR_QUANTIZATION", True)
        )
        self.on_disk = on_disk if on_disk is not None else getattr(settings, "QDRANT_ON_DISK", True)
        self._ensure_collection()

    @classmethod
    def get_instance(cls) -> "QdrantVectorStore":
        if cls._instance is None:
            cls._instance = QdrantVectorStore()
        return cls._instance

    def _ensure_collection(self):
        """
        Create Qdrant collection if it doesn't already exist.
        Configured with HNSW parameters (m=16, ef_construct=100) and scalar quantization
        for high-efficiency indexing and retrieval of 1M-10M vectors on consumer SSDs.
        """
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            hnsw_config = HnswConfigDiff(
                m=self.hnsw_m,
                ef_construct=self.hnsw_ef_construct,
                on_disk=self.on_disk,
            )
            quantization_config = None
            if self.enable_quantization:
                quantization_config = ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    )
                )

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE,
                    on_disk=self.on_disk,
                    quantization_config=quantization_config,
                ),
                hnsw_config=hnsw_config,
                quantization_config=quantization_config,
                on_disk_payload=self.on_disk,
            )

    def close(self):
        """Cleanly close client connection and release underlying file locks."""
        try:
            if hasattr(self.client, "close"):
                self.client.close()
        except Exception:
            pass

    def upsert_chunks(
        self,
        child_chunks: List[ChildChunk],
        parent_map: Dict[str, ParentChunk],
        embeddings: List[List[float]],
        filename: str,
        clearance_level: Optional[int] = None,
        allowed_departments: Optional[List[str]] = None,
    ):
        """
        Batch upsert child chunks with embeddings, security clearance, and contextual payload.
        Includes parent_content directly inside payload for zero-join retrieval!
        """
        if not child_chunks:
            return

        points = []
        for child, vector in zip(child_chunks, embeddings):
            parent = parent_map.get(child.parent_id)
            parent_content = parent.content if parent else child.content

            # Determine clearance level
            c_level = 1
            if clearance_level is not None:
                c_level = clearance_level
            elif getattr(child, "clearance_level", None) is not None:
                c_level = getattr(child, "clearance_level")
            elif parent and getattr(parent, "clearance_level", None) is not None:
                c_level = getattr(parent, "clearance_level")
            elif getattr(child, "metadata", None) and "clearance_level" in child.metadata:
                c_level = child.metadata["clearance_level"]
            elif parent and getattr(parent, "metadata", None) and "clearance_level" in parent.metadata:
                c_level = parent.metadata["clearance_level"]

            # Determine allowed departments
            depts = []
            if allowed_departments is not None:
                depts = list(allowed_departments)
            elif getattr(child, "allowed_departments", None):
                depts = list(getattr(child, "allowed_departments"))
            elif parent and getattr(parent, "allowed_departments", None):
                depts = list(getattr(parent, "allowed_departments"))
            elif getattr(child, "metadata", None) and "allowed_departments" in child.metadata:
                depts = list(child.metadata["allowed_departments"])
            elif parent and getattr(parent, "metadata", None) and "allowed_departments" in parent.metadata:
                depts = list(parent.metadata["allowed_departments"])

            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, child.chunk_id))
            payload = {
                "chunk_id": child.chunk_id,
                "parent_id": child.parent_id,
                "doc_id": child.doc_id,
                "filename": filename,
                "page_number": child.page_number,
                "content": child.content,
                "parent_content": parent_content,
                "token_count": child.token_count,
                "chunk_index": child.chunk_index,
                "clearance_level": int(c_level),
                "allowed_departments": depts,
            }

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )
            )

        # Batch upload to Qdrant
        batch_size = 64
        for i in range(0, len(points), batch_size):
            self.client.upsert(
                collection_name=self.collection_name,
                points=points[i:i + batch_size]
            )

    def search_dense(
        self,
        query_vector: List[float],
        top_k: int = settings.RETRIEVAL_TOP_K,
        doc_id: Optional[str] = None,
        user_clearance: Optional[int] = None,
        user_departments: Optional[List[str]] = None,
        user_department: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute dense cosine vector search in Qdrant with clearance and RBAC filtering.
        Chunks with clearance > user_clearance or non-matching departments are filtered
        out directly at the vector query stage.
        """
        must_conditions = []
        if doc_id:
            must_conditions.append(
                FieldCondition(
                    key="doc_id",
                    match=MatchValue(value=doc_id)
                )
            )

        # Clearance level filtering (clearance_level <= user_clearance)
        if user_clearance is not None:
            must_conditions.append(
                FieldCondition(
                    key="clearance_level",
                    range=Range(lte=user_clearance)
                )
            )

        # Department filtering
        active_departments = []
        if user_departments is not None:
            active_departments.extend([d for d in user_departments if d])
        if user_department and user_department not in active_departments:
            active_departments.append(user_department)

        if user_departments is not None or user_department is not None:
            if active_departments:
                must_conditions.append(
                    Filter(
                        should=[
                            FieldCondition(key="allowed_departments", is_empty=True),
                            FieldCondition(key="allowed_departments", match=MatchAny(any=active_departments)),
                        ]
                    )
                )
            else:
                must_conditions.append(
                    FieldCondition(key="allowed_departments", is_empty=True)
                )

        query_filter = Filter(must=must_conditions) if must_conditions else None

        # In qdrant-client >= 1.10, search / query_points
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True
        ).points

        hits = []
        for res in results:
            hits.append({
                "chunk_id": res.payload.get("chunk_id"),
                "parent_id": res.payload.get("parent_id"),
                "doc_id": res.payload.get("doc_id"),
                "filename": res.payload.get("filename"),
                "page_number": res.payload.get("page_number", 1),
                "content": res.payload.get("content", ""),
                "parent_content": res.payload.get("parent_content", ""),
                "clearance_level": res.payload.get("clearance_level", 1),
                "allowed_departments": res.payload.get("allowed_departments", []),
                "score": res.score,
            })

        return hits

    def delete_by_document(self, doc_id: str):
        """
        Delete all vectors associated with a specific document ID.
        """
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id",
                            match=MatchValue(value=doc_id)
                        )
                    ]
                )
            )
        except Exception as e:
            logger.warning(f"Error deleting vectors for document {doc_id}: {e}")

    def purge_all(self):
        """
        Purge all points from the collection and recreate a pristine empty HNSW index.
        """
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._ensure_collection()

    def count(self) -> int:
        """Return total number of points in collection."""
        try:
            return self.client.count(collection_name=self.collection_name).count
        except Exception:
            return 0

