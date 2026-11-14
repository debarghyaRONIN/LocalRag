from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Boolean,
    event,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ClearanceLevel:
    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    TOP_SECRET = 4


class DBDocument(Base):
    __tablename__ = "documents"

    doc_id = Column(String(64), primary_key=True)
    filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), unique=True, nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(64), nullable=False)
    total_pages = Column(Integer, default=1)
    total_parent_chunks = Column(Integer, default=0)
    total_child_chunks = Column(Integer, default=0)
    clearance_level = Column(Integer, default=1, nullable=False)
    allowed_departments = Column(JSON, default=list)
    owner = Column(String(64), default="default_user", nullable=False)
    status = Column(String(32), default="indexed", nullable=False)
    source_path = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    parents = relationship("DBParentChunk", back_populates="document", cascade="all, delete-orphan")


class DBParentChunk(Base):
    __tablename__ = "parent_chunks"

    parent_id = Column(String(64), primary_key=True)
    doc_id = Column(String(64), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0)
    page_number = Column(Integer, default=1)
    meta_info = Column(JSON, default=dict)
    clearance_level = Column(Integer, default=1, nullable=False)
    allowed_departments = Column(JSON, default=list)

    document = relationship("DBDocument", back_populates="parents")


class DBChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String(64), primary_key=True)
    title = Column(String(255), default="New Conversation")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("DBChatMessage", back_populates="session", cascade="all, delete-orphan")


class DBChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id = Column(String(64), primary_key=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    latency_ms = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("DBChatSession", back_populates="messages")


class DBFeedback(Base):
    __tablename__ = "feedbacks"

    feedback_id = Column(String(64), primary_key=True)
    request_id = Column(String(64), nullable=True, index=True)
    message_id = Column(String(64), nullable=True, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 1 or -1
    feedback_category = Column(String(64), nullable=True)
    reason_code = Column(String(64), nullable=True)
    expert_correction = Column(Text, nullable=True)
    citations_approved = Column(JSON, default=list)
    is_expert_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBRequest(Base):
    """Stores every question, user context, retrieved passages, model/adapter, and response for audit and feedback."""
    __tablename__ = "requests"

    request_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), default="default_operator", nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    passages_used = Column(JSON, default=list)
    answer = Column(Text, nullable=False)
    model_id = Column(String(128), default="Qwen/Qwen2.5-3B-Instruct", nullable=False)
    adapter_id = Column(String(64), nullable=True)
    latency_ms = Column(JSON, default=dict)
    retrieval_enabled = Column(Boolean, default=True)
    clearance_level = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class DBTestCase(Base):
    """Test cases defining the customer's definition of better across held-out, regression, and permission suites."""
    __tablename__ = "test_cases"

    case_id = Column(String(64), primary_key=True)
    suite = Column(String(64), default="core_workflow", nullable=False, index=True)
    input_text = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=True)
    rubric = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    suite_version = Column(String(32), default="v1.0", nullable=False)
    is_held_out = Column(Boolean, default=False)
    is_regression = Column(Boolean, default=False)
    is_permission_case = Column(Boolean, default=False)
    required_clearance = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBEvalRun(Base):
    """Comparison runs across model and adapter pairs."""
    __tablename__ = "eval_runs"

    run_id = Column(String(64), primary_key=True)
    suite_version = Column(String(32), default="v1.0", nullable=False)
    model_id = Column(String(128), nullable=False)
    adapter_id = Column(String(64), nullable=True)
    per_case_scores = Column(JSON, default=list)
    totals = Column(JSON, default=dict)
    passed_held_out = Column(Boolean, default=True)
    passed_regression = Column(Boolean, default=True)
    passed_permission = Column(Boolean, default=True)
    status = Column(String(32), default="completed", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBDataset(Base):
    """Reproducible, model-agnostic training inputs generated from verified feedback."""
    __tablename__ = "datasets"

    dataset_id = Column(String(64), primary_key=True)
    version = Column(String(32), nullable=False, unique=True, index=True)
    source_feedback_ids = Column(JSON, default=list)
    format = Column(String(32), default="alpaca", nullable=False)  # "alpaca", "sharegpt", "dpo"
    total_samples = Column(Integer, default=0, nullable=False)
    export_path = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBAdapter(Base):
    """Tuned LoRA adapters, their lineage, eval runs, and lifecycle status (draft, candidate, live, retired)."""
    __tablename__ = "adapters"

    adapter_id = Column(String(64), primary_key=True)
    base_model_id = Column(String(128), nullable=False)
    dataset_id = Column(String(64), nullable=True)
    training_config = Column(JSON, default=dict)
    eval_run_id = Column(String(64), nullable=True)
    status = Column(String(32), default="draft", nullable=False, index=True)  # draft, candidate, live, retired
    artifact_path = Column(Text, nullable=True)
    promoted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DBAuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(String(64), primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    query_hash = Column(String(64), nullable=True)
    exposed_chunk_ids = Column(JSON, default=list)
    model_used = Column(String(128), nullable=True)
    latency_ms = Column(JSON, default=dict)
    prev_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False, index=True)


class IndexingJobStatus:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class DBIndexingJob(Base):
    __tablename__ = "indexing_jobs"

    job_id = Column(String(64), primary_key=True)
    job_type = Column(String(32), nullable=False)  # "folder", "repo", "file", etc.
    source_path = Column(Text, nullable=False)
    total_files = Column(Integer, default=0, nullable=False)
    processed_files = Column(Integer, default=0, nullable=False)
    total_chunks = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default=IndexingJobStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)



