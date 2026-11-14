import shutil
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from backend.app.core.config import settings
from backend.app.domain.models import DocumentMetadata
from backend.app.db.session import get_db
from pydantic import BaseModel
import re
from backend.app.db.models import DBDocument, DBParentChunk
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.services.retrieval.vector_store import QdrantVectorStore
from backend.app.services.compliance.audit_ledger import record_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()
_pipeline = None


def get_pipeline() -> IngestionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = IngestionPipeline()
    return _pipeline


@router.post("/documents/upload", response_model=DocumentMetadata)
async def upload_document(
    file: UploadFile = File(...),
    clearance_level: int = Form(1),
    allowed_departments: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a document, parse it, chunk it hierarchically, and index it into Qdrant & DB.
    Supports RBAC clearance levels (1=Public, 2=Internal, 3=Confidential, 4=Top Secret)
    and allowed department filtering.
    Idempotent: Identical files return existing record without re-indexing.
    """
    clean_name = Path(file.filename or "").name
    if not clean_name:
        raise HTTPException(status_code=400, detail="Invalid or empty filename provided")
    save_path = settings.UPLOADS_DIR / clean_name

    try:
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    depts: List[str] = []
    if allowed_departments:
        clean_depts = allowed_departments.strip()
        if clean_depts.startswith("["):
            try:
                depts = json.loads(clean_depts)
            except Exception:
                depts = [d.strip() for d in clean_depts.split(",") if d.strip()]
        else:
            depts = [d.strip() for d in clean_depts.split(",") if d.strip()]

    try:
        pipeline = get_pipeline()
        doc_metadata = await pipeline.ingest_file(
            file_path=save_path,
            db_session=db,
            filename=clean_name,
            clearance_level=clearance_level,
            allowed_departments=depts,
        )

        # Audit ledger record
        try:
            await record_audit_event(
                db=db,
                user_id="system",
                action="document_upload",
                query_hash=doc_metadata.file_hash,
                exposed_chunk_ids=[doc_metadata.doc_id],
                model_used=settings.EMBEDDING_MODEL if hasattr(settings, "EMBEDDING_MODEL") else "bge-small-en-v1.5",
                latency_ms={},
            )
        except Exception as e:
            logger.warning(f"Failed to record upload audit event: {e}")

        return doc_metadata
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.get("/documents", response_model=List[DocumentMetadata])
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all indexed documents with page, chunk, and clearance metrics."""
    stmt = select(DBDocument).order_by(DBDocument.created_at.desc())
    res = await db.execute(stmt)
    docs = res.scalars().all()

    return [
        DocumentMetadata(
            doc_id=d.doc_id,
            filename=d.filename,
            file_hash=d.file_hash,
            file_size_bytes=d.file_size_bytes,
            mime_type=d.mime_type,
            total_pages=d.total_pages,
            total_parent_chunks=d.total_parent_chunks,
            total_child_chunks=d.total_child_chunks,
            clearance_level=getattr(d, "clearance_level", 1),
            allowed_departments=getattr(d, "allowed_departments", []) or [],
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.post("/documents/purge-all")
@router.delete("/documents")
async def purge_all_documents(db: AsyncSession = Depends(get_db)):
    """
    Completely purge all documents, parent-child vector embeddings, FTS5 full-text index,
    and uploaded physical files. Restores the knowledge base to a 100% pristine, zero-document state.
    """
    res = await db.execute(select(DBDocument.doc_id, DBDocument.filename))
    docs_to_delete = res.all()
    count = len(docs_to_delete)

    # 1. Purge Qdrant vector collection
    try:
        vector_store = QdrantVectorStore.get_instance()
        await asyncio.to_thread(vector_store.purge_all)
    except Exception as e:
        logger.warning(f"Error purging Qdrant vector store: {e}")

    # 2. Purge FTS5 index
    try:
        from backend.app.services.retrieval.fts_store import FTS5BM25Store
        await asyncio.to_thread(FTS5BM25Store.get_instance().purge_all)
    except Exception as e:
        logger.warning(f"Error purging FTS5: {e}")

    # 3. Clean physical files from uploads directory
    try:
        if settings.UPLOADS_DIR.exists():
            for f in settings.UPLOADS_DIR.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                    except Exception:
                        pass
    except Exception:
        pass

    # 4. Fast bulk delete from SQLite DB
    await db.execute(delete(DBParentChunk))
    await db.execute(delete(DBDocument))
    await db.commit()

    # 5. Record compliance audit event
    try:
        await record_audit_event(
            db=db,
            user_id="system",
            action="corpus_purge_all",
            query_hash=None,
            exposed_chunk_ids=[],
            latency_ms={},
        )
    except Exception:
        pass

    return {"status": "purged", "deleted_count": count}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    """Delete document and purge all its vectors from Qdrant, FTS5, disk, and relational database."""
    stmt = select(DBDocument).where(DBDocument.doc_id == doc_id)
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()

    if not doc:
        # Also ensure orphan points in Qdrant are wiped even if DB record is missing
        try:
            vector_store = QdrantVectorStore.get_instance()
            await asyncio.to_thread(vector_store.delete_by_document, doc_id)
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Document not found")

    filename = doc.filename
    source_path = doc.source_path

    # 1. Purge points from Qdrant and FTS5 in worker thread
    try:
        vector_store = QdrantVectorStore.get_instance()
        await asyncio.to_thread(vector_store.delete_by_document, doc_id)
    except Exception as e:
        logger.warning(f"Failed to delete Qdrant vectors for {doc_id}: {e}")

    try:
        from backend.app.services.retrieval.fts_store import FTS5BM25Store
        await asyncio.to_thread(FTS5BM25Store.get_instance().delete_by_doc, doc_id)
    except Exception as e:
        logger.warning(f"Failed to delete FTS5 chunks for {doc_id}: {e}")

    # 2. Delete file from uploads directory or source_path if exists
    try:
        for candidate_path in [settings.UPLOADS_DIR / filename, Path(source_path) if source_path else None]:
            if candidate_path and candidate_path.exists() and candidate_path.is_file():
                try:
                    candidate_path.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Fast bulk delete from DB (chunks first, then document)
    await db.execute(delete(DBParentChunk).where(DBParentChunk.doc_id == doc_id))
    await db.delete(doc)
    await db.commit()

    # 4. Audit ledger record
    try:
        await record_audit_event(
            db=db,
            user_id="system",
            action="document_delete",
            query_hash=None,
            exposed_chunk_ids=[doc_id],
            latency_ms={},
        )
    except Exception as e:
        logger.warning(f"Failed to record delete audit event: {e}")

    return {"status": "deleted", "doc_id": doc_id, "filename": filename}


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(doc_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve all hierarchical parent chunks and metadata for a specific document."""
    stmt = (
        select(DBParentChunk)
        .where(DBParentChunk.doc_id == doc_id)
        .order_by(DBParentChunk.chunk_index.asc())
    )
    res = await db.execute(stmt)
    chunks = res.scalars().all()
    if not chunks:
        doc = await db.get(DBDocument, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return []

    return [
        {
            "parent_id": c.parent_id,
            "doc_id": c.doc_id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "token_count": c.token_count,
            "page_number": c.page_number,
            "clearance_level": c.clearance_level,
            "metadata": c.meta_info or {},
        }
        for c in chunks
    ]


class IngestUrlPayload(BaseModel):
    url: str
    clearance_level: int = 1
    allowed_departments: Optional[List[str]] = None


@router.post("/documents/ingest-url", response_model=DocumentMetadata)
async def ingest_web_url(
    payload: IngestUrlPayload,
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest a web or intranet URL, extract clean markdown headings and content,
    and index it hierarchically with zero boilerplate.
    """
    import urllib.request
    from backend.app.services.ingestion.web_parser import WebParser

    try:
        req = urllib.request.Request(
            payload.url,
            headers={"User-Agent": "Sealed-Sovereign-Indexer/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_content = resp.read().decode("utf-8", errors="replace")

        parsed = WebParser.parse_html(html_content, base_url=payload.url)
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', parsed.title or "web_page")[:50] + ".md"
        save_path = settings.UPLOADS_DIR / safe_name
        save_path.write_text(parsed.formatted_text, encoding="utf-8")

        pipeline = get_pipeline()
        doc_metadata = await pipeline.ingest_file(
            file_path=save_path,
            db_session=db,
            filename=safe_name,
            clearance_level=payload.clearance_level,
            allowed_departments=payload.allowed_departments or [],
        )
        return doc_metadata
    except Exception as e:
        logger.error(f"Failed to ingest URL {payload.url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Web URL ingestion failed: {str(e)}")

