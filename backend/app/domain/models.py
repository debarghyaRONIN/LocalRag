from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    doc_id: str
    filename: str
    file_hash: str
    file_size_bytes: int
    mime_type: str
    total_pages: int = 1
    total_parent_chunks: int = 0
    total_child_chunks: int = 0
    clearance_level: int = 1
    allowed_departments: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ParentChunk(BaseModel):
    parent_id: str
    doc_id: str
    chunk_index: int
    content: str
    token_count: int
    page_number: int = 1
    clearance_level: int = 1
    allowed_departments: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChildChunk(BaseModel):
    chunk_id: str
    parent_id: str
    doc_id: str
    chunk_index: int
    content: str
    token_count: int
    page_number: int = 1
    clearance_level: int = 1
    allowed_departments: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchCandidate(BaseModel):
    chunk_id: str
    parent_id: str
    doc_id: str
    filename: str
    page_number: int
    content: str  # Child chunk content
    parent_content: Optional[str] = None  # Full parent chunk content for LLM context
    parent_index: Optional[int] = None
    preceding_context: Optional[str] = None
    following_context: Optional[str] = None
    stitched_context: Optional[str] = None
    clearance_level: int = 1
    allowed_departments: List[str] = Field(default_factory=list)
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None


class Citation(BaseModel):
    citation_id: int
    chunk_id: str
    parent_id: str
    doc_id: str
    filename: str
    page_number: int
    exact_quote: str
    relevance_score: float
    parent_content: Optional[str] = None
    stitched_context: Optional[str] = None


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    user_id: Optional[str] = "anonymous"
    user_clearance: Optional[int] = None
    user_departments: Optional[List[str]] = None
    top_k: int = 5
    min_rerank_score: Optional[float] = None
    stream: bool = True


class AuditLogEntry(BaseModel):
    log_id: str
    timestamp: datetime
    user_id: str
    action: str
    query_hash: Optional[str] = None
    exposed_chunk_ids: List[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    latency_ms: Optional[Any] = None
    prev_hash: str
    entry_hash: str

    model_config = {"from_attributes": True}


class AuditIntegrityReport(BaseModel):
    is_valid: bool
    total_records: int
    tampered_records: List[Dict[str, Any]] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=datetime.utcnow)
    message: str


class QueryResponse(BaseModel):
    query: str
    answer: str
    citations: List[Citation]
    retrieved_chunks_count: int
    latency_ms: Dict[str, float]
    model_used: str
    session_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    app_version: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    gpu_memory_used_mb: Optional[int] = None
    gpu_memory_total_mb: Optional[int] = None
    vector_db_ready: bool
    vllm_ready: bool = False
    vllm_model: Optional[str] = None
    total_indexed_documents: int
    total_indexed_chunks: int


class IndexingJobResponse(BaseModel):
    job_id: str
    job_type: str
    source_path: str
    total_files: int
    processed_files: int
    total_chunks: int
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    progress_percent: float = 0.0

    model_config = {"from_attributes": True}


class IngestFolderRequest(BaseModel):
    folder_path: str = Field(..., description="Absolute or relative path to the folder")
    clearance_level: int = Field(1, ge=1, le=4, description="Clearance level (1-4)")
    allowed_departments: Optional[List[str]] = Field(default_factory=list, description="Allowed department codes")
    recursive: bool = Field(True, description="Whether to scan recursively")


class IngestRepoRequest(BaseModel):
    repo_path: str = Field(..., description="Absolute or relative path to the git or code repository")
    clearance_level: int = Field(1, ge=1, le=4, description="Clearance level (1-4)")
    allowed_departments: Optional[List[str]] = Field(default_factory=list, description="Allowed department codes")
    branch_or_commit: Optional[str] = Field(None, description="Optional branch or commit reference")

