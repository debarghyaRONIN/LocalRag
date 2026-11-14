from pathlib import Path
from typing import Dict, List, Optional
import uuid
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.domain.models import DocumentMetadata, ParentChunk
from backend.app.db.models import DBDocument, DBParentChunk
from backend.app.services.ingestion.hasher import compute_file_hash
from backend.app.services.ingestion.parsers import DocumentParser
from backend.app.services.ingestion.chunkers import HierarchicalChunker
from backend.app.services.retrieval.embeddings import EmbeddingEngine
from backend.app.services.retrieval.vector_store import QdrantVectorStore
from backend.app.services.retrieval.fts_store import FTS5BM25Store


class IngestionPipeline:
    def __init__(
        self,
        embedder: Optional[EmbeddingEngine] = None,
        vector_store: Optional[QdrantVectorStore] = None,
        chunker: Optional[HierarchicalChunker] = None,
        fts_store: Optional[FTS5BM25Store] = None,
    ):
        self.embedder = embedder or EmbeddingEngine.get_instance()
        self.vector_store = vector_store or QdrantVectorStore.get_instance()
        self.chunker = chunker or HierarchicalChunker()
        self.fts_store = fts_store or FTS5BM25Store.get_instance()

    async def ingest_file(
        self,
        file_path: Path,
        db_session: AsyncSession,
        filename: Optional[str] = None,
        clearance_level: int = 1,
        allowed_departments: Optional[List[str]] = None,
    ) -> DocumentMetadata:
        """
        Idempotent document ingestion pipeline:
        1. Compute SHA-256 hash. If document already indexed, return cached record.
        2. Extract layout & text page-by-page.
        3. Split into hierarchical Parent-Child chunks.
        4. Compute ONNX dense embeddings for child chunks.
        5. Save parent chunks in relational DB with clearance and RBAC metadata.
        6. Batch upsert child vectors into Qdrant.
        """
        clean_filename = filename or file_path.name
        file_hash = compute_file_hash(file_path)
        file_size = file_path.stat().st_size
        actual_departments = allowed_departments or []

        # Check for existing document by content hash
        stmt = select(DBDocument).where(DBDocument.file_hash == file_hash)
        result = await db_session.execute(stmt)
        existing_doc = result.scalar_one_or_none()

        if existing_doc:
            return DocumentMetadata(
                doc_id=existing_doc.doc_id,
                filename=existing_doc.filename,
                file_hash=existing_doc.file_hash,
                file_size_bytes=existing_doc.file_size_bytes,
                mime_type=existing_doc.mime_type,
                total_pages=existing_doc.total_pages,
                total_parent_chunks=existing_doc.total_parent_chunks,
                total_child_chunks=existing_doc.total_child_chunks,
                clearance_level=getattr(existing_doc, "clearance_level", 1),
                allowed_departments=getattr(existing_doc, "allowed_departments", []) or [],
                created_at=existing_doc.created_at,
            )

        # 1. Parse document pages in worker thread
        pages = await asyncio.to_thread(DocumentParser.parse, file_path)
        total_pages = max(1, len(pages))
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"

        # 2. Hierarchical Chunking in worker thread
        parent_chunks, child_chunks = await asyncio.to_thread(
            self.chunker.chunk_document,
            doc_id=doc_id,
            pages=pages,
            metadata={"filename": clean_filename, "hash": file_hash, "clearance_level": clearance_level, "allowed_departments": actual_departments}
        )

        parent_map: Dict[str, ParentChunk] = {p.parent_id: p for p in parent_chunks}

        # 3. Dense ONNX Embeddings for child chunks in worker thread
        child_texts = [c.content for c in child_chunks]
        if child_texts:
            embeddings = await asyncio.to_thread(self.embedder.embed_texts, child_texts)
        else:
            embeddings = []

        # 4. Save Parent Chunks to Relational DB
        db_parents = [
            DBParentChunk(
                parent_id=p.parent_id,
                doc_id=doc_id,
                chunk_index=p.chunk_index,
                content=p.content,
                token_count=p.token_count,
                page_number=p.page_number,
                meta_info=p.metadata,
                clearance_level=getattr(p, "clearance_level", clearance_level),
                allowed_departments=getattr(p, "allowed_departments", actual_departments),
            )
            for p in parent_chunks
        ]
        db_session.add_all(db_parents)

        # 5. Upsert Child Vectors to Qdrant in worker thread with clearance
        if child_chunks and embeddings:
            await asyncio.to_thread(
                self.vector_store.upsert_chunks,
                child_chunks=child_chunks,
                parent_map=parent_map,
                embeddings=embeddings,
                filename=clean_filename,
                clearance_level=clearance_level,
                allowed_departments=actual_departments,
            )

        # 5b. Upsert Parent Chunks to FTS5 for BM25 keyword search
        if parent_chunks:
            await asyncio.to_thread(
                self.fts_store.upsert_fts_chunks,
                parent_chunks=parent_chunks,
                filename=clean_filename,
                clearance_level=clearance_level,
            )

        # 6. Record Document in Relational DB with rollback guarantee
        suffix = file_path.suffix.lower().lstrip(".")
        db_doc = DBDocument(
            doc_id=doc_id,
            filename=clean_filename,
            file_hash=file_hash,
            file_size_bytes=file_size,
            mime_type=f"application/{suffix}",
            total_pages=total_pages,
            total_parent_chunks=len(parent_chunks),
            total_child_chunks=len(child_chunks),
            clearance_level=clearance_level,
            allowed_departments=actual_departments,
        )
        db_session.add(db_doc)

        try:
            await db_session.commit()
            await db_session.refresh(db_doc)
        except Exception as e:
            await db_session.rollback()
            # Clean up vector store and FTS5 to avoid orphaned vector records
            try:
                await asyncio.to_thread(self.vector_store.delete_by_document, doc_id)
                await asyncio.to_thread(self.fts_store.delete_by_doc, doc_id)
            except Exception:
                pass
            raise e

        return DocumentMetadata(
            doc_id=db_doc.doc_id,
            filename=db_doc.filename,
            file_hash=db_doc.file_hash,
            file_size_bytes=db_doc.file_size_bytes,
            mime_type=db_doc.mime_type,
            total_pages=db_doc.total_pages,
            total_parent_chunks=db_doc.total_parent_chunks,
            total_child_chunks=db_doc.total_child_chunks,
            clearance_level=db_doc.clearance_level,
            allowed_departments=db_doc.allowed_departments or [],
            created_at=db_doc.created_at,
        )

