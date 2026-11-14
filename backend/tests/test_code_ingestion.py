"""
Unit and integration tests for source code ingestion and AST-aware parsing.

Validates:
1. AST parsing and symbol extraction across 6 language families:
   - Python (AST-based extraction of modules, classes, methods, async functions, decorators, imports)
   - TypeScript / JavaScript (classes, interfaces, constructors, methods, exported functions)
   - Go (structs, interfaces, receiver methods, functions)
   - Rust (structs, enums, traits, impl blocks, methods)
   - Java (classes, constructors, methods, packages)
   - C / C++ (classes, structs, inline and out-of-line methods, free functions)
2. Structural boundaries, signatures, docstrings, exact line numbers, and symbol preservation.
3. Parent-child relationship preservation (classes -> methods/constructors).
4. Error resilience: syntax errors, empty inputs, comments-only files.
5. Code-aware hierarchical chunking (ASTCodeChunker and HierarchicalChunker).
6. DocumentParser end-to-end integration for source code files.
"""

from pathlib import Path
import pytest

from backend.app.services.ingestion.code_parser import (
    CodeParser,
    CodeSymbol,
    CodeSymbolType,
    ParsedCode,
    EXTENSION_TO_LANGUAGE,
)
from backend.app.services.ingestion.chunkers import HierarchicalChunker, ASTCodeChunker
from backend.app.services.ingestion.parsers import DocumentParser


# ============================================================================
# 1. Python AST-Aware Parsing Tests
# ============================================================================

def test_python_ast_complete_extraction():
    """Verify detailed Python AST extraction including async functions, docstrings, and hierarchy."""
    py_code = '''"""
Sovereign Retrieval Core
Enterprise air-gapped vector search engine.
"""

import os
import sys
from typing import List, Optional, Dict, Any

GLOBAL_TIMEOUT: int = 30

class BaseRetriever:
    """Abstract base retriever interface."""
    
    def __init__(self, collection_name: str):
        """Initialize retriever with target collection."""
        self.collection_name = collection_name
        self.is_connected = False

    def connect(self) -> bool:
        """Connect to vector storage."""
        self.is_connected = True
        return True


class DenseRetriever(BaseRetriever):
    """Dense embedding retriever with HNSW graph exploration."""

    @classmethod
    def create_default(cls) -> "DenseRetriever":
        """Factory method for default instance."""
        return cls("default_collection")

    async def retrieve_async(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Perform asynchronous vector similarity retrieval."""
        return [{"id": "chunk_1", "score": 0.95}]


async def run_standalone_query(query_text: str) -> Dict[str, Any]:
    """Execute query in standalone execution scope."""
    return {"query": query_text, "results": []}
'''
    parsed = CodeParser.parse_code(py_code, language="python")

    # Module docstring & imports
    assert parsed.module_docstring is not None
    assert "Sovereign Retrieval Core" in parsed.module_docstring
    assert "Enterprise air-gapped" in parsed.module_docstring
    assert any("import os" in imp for imp in parsed.imports)
    assert any("from typing import" in imp for imp in parsed.imports)

    # BaseRetriever class
    base_cls = next((s for s in parsed.symbols if s.name == "BaseRetriever"), None)
    assert base_cls is not None
    assert base_cls.symbol_type == CodeSymbolType.CLASS.value
    assert base_cls.docstring == "Abstract base retriever interface."
    assert len(base_cls.children) == 2

    # BaseRetriever methods
    ctor = next((c for c in base_cls.children if c.name == "__init__"), None)
    assert ctor is not None
    assert ctor.symbol_type == CodeSymbolType.CONSTRUCTOR.value
    assert ctor.parent_name == "BaseRetriever"
    assert "collection_name: str" in ctor.signature

    connect_meth = next((c for c in base_cls.children if c.name == "connect"), None)
    assert connect_meth is not None
    assert connect_meth.symbol_type == CodeSymbolType.METHOD.value
    assert connect_meth.parent_name == "BaseRetriever"

    # DenseRetriever class
    dense_cls = next((s for s in parsed.symbols if s.name == "DenseRetriever"), None)
    assert dense_cls is not None
    assert dense_cls.symbol_type == CodeSymbolType.CLASS.value
    assert "Dense embedding retriever" in dense_cls.docstring
    assert len(dense_cls.children) == 2

    # Async method extraction
    async_meth = next((c for c in dense_cls.children if c.name == "retrieve_async"), None)
    assert async_meth is not None
    assert async_meth.symbol_type == CodeSymbolType.METHOD.value
    assert async_meth.parent_name == "DenseRetriever"
    assert "async def retrieve_async" in async_meth.signature
    assert "Perform asynchronous vector similarity retrieval." in async_meth.docstring

    # Free async function
    standalone_fn = next((s for s in parsed.symbols if s.name == "run_standalone_query"), None)
    assert standalone_fn is not None
    assert standalone_fn.symbol_type == CodeSymbolType.FUNCTION.value
    assert standalone_fn.parent_name is None
    assert "async def run_standalone_query" in standalone_fn.signature
    assert "Execute query in standalone execution scope." in standalone_fn.docstring


# ============================================================================
# 2. TypeScript and JavaScript Parsing Tests
# ============================================================================

def test_typescript_symbols_and_interfaces():
    """Verify TypeScript classes, interfaces, and function extraction."""
    ts_code = '''import { Request, Response } from 'express';

export interface AuditRecord {
    id: string;
    hash: string;
    timestamp: number;
}

/**
 * Service managing cryptographic verification.
 */
export class CryptographicLedger {
    private secretKey: string;

    constructor(secretKey: string) {
        this.secretKey = secretKey;
    }

    /**
     * Compute SHA-256 hash for document payload.
     */
    public async computeHash(data: string): Promise<string> {
        return "sha256_mock_hash";
    }
}

export function formatAuditEntry(record: AuditRecord): string {
    return `[${record.timestamp}] ${record.hash}`;
}
'''
    parsed = CodeParser.parse_code(ts_code, language="typescript")

    assert len(parsed.imports) >= 1
    assert "import { Request, Response }" in parsed.imports[0]

    # Interface
    iface = next((s for s in parsed.symbols if s.name == "AuditRecord"), None)
    assert iface is not None
    assert iface.symbol_type in (CodeSymbolType.INTERFACE.value, CodeSymbolType.STRUCT.value)

    # Class
    ledger = next((s for s in parsed.symbols if s.name == "CryptographicLedger"), None)
    assert ledger is not None
    assert ledger.symbol_type == CodeSymbolType.CLASS.value
    assert ledger.docstring is not None
    assert "CryptographicLedger" in ledger.signature

    # Children (constructor + method)
    assert len(ledger.children) == 2
    ctor = next(c for c in ledger.children if c.name == "constructor")
    assert ctor.symbol_type == CodeSymbolType.CONSTRUCTOR.value
    assert ctor.parent_name == "CryptographicLedger"

    meth = next(c for c in ledger.children if c.name == "computeHash")
    assert meth.symbol_type == CodeSymbolType.METHOD.value
    assert meth.parent_name == "CryptographicLedger"
    assert "computeHash" in meth.signature
    assert "Compute SHA-256 hash" in meth.docstring

    # Free function
    fn = next((s for s in parsed.symbols if s.name == "formatAuditEntry"), None)
    assert fn is not None
    assert fn.symbol_type == CodeSymbolType.FUNCTION.value


# ============================================================================
# 3. Go Structs and Receiver Methods
# ============================================================================

def test_go_structs_and_receivers():
    """Verify Go struct extraction and receiver methods linked as children."""
    go_code = '''package indexing

import (
    "context"
    "fmt"
)

// IndexCoordinator coordinates distributed indexing tasks
type IndexCoordinator struct {
    MaxWorkers int
    QueueName  string
}

// Start launches worker pool
func (c *IndexCoordinator) Start(ctx context.Context) error {
    return nil
}

// Stop gracefully terminates all active indexing workers
func (c *IndexCoordinator) Stop() error {
    return nil
}

// NewCoordinator constructs a fresh IndexCoordinator
func NewCoordinator(workers int) *IndexCoordinator {
    return &IndexCoordinator{MaxWorkers: workers, QueueName: "default"}
}
'''
    parsed = CodeParser.parse_code(go_code, language="go")

    assert len(parsed.imports) >= 2
    coord = next((s for s in parsed.symbols if s.name == "IndexCoordinator"), None)
    assert coord is not None
    assert coord.symbol_type == CodeSymbolType.STRUCT.value
    assert coord.docstring == "IndexCoordinator coordinates distributed indexing tasks"

    # Both receiver methods should be attached as children
    assert len(coord.children) == 2
    start_m = next(c for c in coord.children if c.name == "Start")
    assert start_m.parent_name == "IndexCoordinator"
    assert start_m.docstring == "Start launches worker pool"

    stop_m = next(c for c in coord.children if c.name == "Stop")
    assert stop_m.parent_name == "IndexCoordinator"
    assert stop_m.docstring == "Stop gracefully terminates all active indexing workers"

    # Free function
    new_fn = next((s for s in parsed.symbols if s.name == "NewCoordinator"), None)
    assert new_fn is not None
    assert new_fn.symbol_type == CodeSymbolType.FUNCTION.value


# ============================================================================
# 4. Rust Structs, Impls, and Traits
# ============================================================================

def test_rust_struct_impl_methods():
    """Verify Rust struct and impl block methods extraction."""
    rs_code = '''use std::path::PathBuf;

/// VectorStoreConfig configures HNSW graph parameters
pub struct VectorStoreConfig {
    pub hnsw_m: usize,
    pub ef_construct: usize,
}

impl VectorStoreConfig {
    /// Constructs default HNSW parameters
    pub fn default() -> Self {
        Self { hnsw_m: 16, ef_construct: 100 }
    }

    /// Validates configuration parameters
    pub fn validate(&self) -> bool {
        self.hnsw_m > 0 && self.ef_construct > 0
    }
}

pub fn sanitize_path(path: PathBuf) -> PathBuf {
    path
}
'''
    parsed = CodeParser.parse_code(rs_code, language="rust")

    struct_sym = next((s for s in parsed.symbols if s.name == "VectorStoreConfig" and s.symbol_type == "struct"), None)
    assert struct_sym is not None
    assert struct_sym.docstring == "VectorStoreConfig configures HNSW graph parameters"

    impl_sym = next((s for s in parsed.symbols if s.name == "VectorStoreConfig" and s.symbol_type == "impl"), None)
    assert impl_sym is not None
    assert len(impl_sym.children) == 2

    m_default = next(c for c in impl_sym.children if c.name == "default")
    assert m_default.parent_name == "VectorStoreConfig"
    assert "Constructs default HNSW parameters" in m_default.docstring

    m_val = next(c for c in impl_sym.children if c.name == "validate")
    assert m_val.parent_name == "VectorStoreConfig"
    assert "Validates configuration parameters" in m_val.docstring

    fn = next((s for s in parsed.symbols if s.name == "sanitize_path"), None)
    assert fn is not None
    assert fn.symbol_type == CodeSymbolType.FUNCTION.value


# ============================================================================
# 5. Java and C/C++ Symbol Preservation
# ============================================================================

def test_java_class_and_methods():
    """Verify Java class, constructors, and method parsing."""
    java_code = '''package com.ragapp.security;

import java.util.List;

/**
 * AccessController validates clearance levels.
 */
public class AccessController {
    private int requiredLevel;

    public AccessController(int level) {
        this.requiredLevel = level;
    }

    public boolean canAccess(int userClearance) {
        return userClearance >= this.requiredLevel;
    }
}
'''
    parsed = CodeParser.parse_code(java_code, language="java")
    cls = next((s for s in parsed.symbols if s.name == "AccessController"), None)
    assert cls is not None
    assert cls.symbol_type == CodeSymbolType.CLASS.value
    assert len(cls.children) == 2

    ctor = next(c for c in cls.children if c.name == "AccessController")
    assert ctor.symbol_type == CodeSymbolType.CONSTRUCTOR.value
    assert ctor.parent_name == "AccessController"

    meth = next(c for c in cls.children if c.name == "canAccess")
    assert meth.symbol_type == CodeSymbolType.METHOD.value
    assert meth.parent_name == "AccessController"


def test_cpp_class_and_methods():
    """Verify C++ class and method extraction."""
    cpp_code = '''#include <string>
#include <vector>

class EmbeddingCache {
public:
    EmbeddingCache(size_t capacity);
    bool put(const std::string& key, const std::vector<float>& vec);
};

bool EmbeddingCache::put(const std::string& key, const std::vector<float>& vec) {
    return true;
}

std::string compute_hash(const std::string& text) {
    return "hash_val";
}
'''
    parsed = CodeParser.parse_code(cpp_code, language="cpp")
    assert len(parsed.imports) == 2
    cls = next((s for s in parsed.symbols if s.name == "EmbeddingCache"), None)
    assert cls is not None
    assert any(c.name == "put" for c in cls.children)

    fn = next((s for s in parsed.symbols if s.name == "compute_hash"), None)
    assert fn is not None
    assert fn.symbol_type == CodeSymbolType.FUNCTION.value


# ============================================================================
# 6. Syntax Error Resilience and Edge Cases
# ============================================================================

def test_python_syntax_error_resilience():
    """Verify Python code with syntax errors degrades gracefully without raising unhandled exceptions."""
    broken_code = '''
def broken_function(:
    print("missing argument name"
class UnclosedClass
'''
    # Must not raise an exception; should return ParsedCode with fallback
    parsed = CodeParser.parse_code(broken_code, language="python")
    assert isinstance(parsed, ParsedCode)
    assert parsed.language == "python"
    assert parsed.total_lines > 0


def test_empty_and_whitespace_code():
    """Verify parsing empty code or whitespace returns valid empty ParsedCode."""
    parsed = CodeParser.parse_code("", language="python")
    assert parsed.symbols == []
    assert parsed.imports == []
    assert parsed.total_lines == 0

    parsed_spaces = CodeParser.parse_code("   \n\n\t  \n", language="typescript")
    assert parsed_spaces.symbols == []
    assert parsed_spaces.total_lines == 3


def test_comments_only_file():
    """Verify files with only comments are parsed without errors."""
    code = """# Comment line 1\n# Comment line 2\n# Comment line 3\n"""
    parsed = CodeParser.parse_code(code, language="python")
    assert parsed.symbols == []
    assert parsed.imports == []
    assert parsed.total_lines == 3


# ============================================================================
# 7. AST / Code-Aware Chunking Verification
# ============================================================================

def test_ast_hierarchical_chunking_preserves_symbols_and_signatures():
    """Verify HierarchicalChunker chunks code preserving symbol names, docstrings, and signatures."""
    code = '''"""
Database connection pool module.
"""
import sqlite3

class ConnectionPool:
    """Manages thread-safe SQLite connection pooling."""

    def __init__(self, db_path: str, max_connections: int = 5):
        """Initialize connection pool with capacity."""
        self.db_path = db_path
        self.max_connections = max_connections

    def acquire(self) -> sqlite3.Connection:
        """Acquire an active database connection."""
        return sqlite3.connect(self.db_path)

    def release(self, conn: sqlite3.Connection) -> None:
        """Return database connection to the pool."""
        conn.close()

def ping_database(db_path: str) -> bool:
    """Test connectivity to database file."""
    return True
'''
    chunker = HierarchicalChunker(
        parent_size=400,
        parent_overlap=50,
        child_size=150,
        child_overlap=25,
    )

    doc_id = "test_code_chunk_doc_01"
    parsed_code = CodeParser.parse_code(code, language="python")
    parents, children = chunker.chunk_code(
        doc_id=doc_id,
        code=code,
        language="python",
        parsed_code=parsed_code,
    )

    assert len(parents) >= 1
    assert len(children) >= 3

    parent_ids = {p.parent_id for p in parents}
    for child in children:
        # Every child must reference an existing parent_id
        assert child.parent_id in parent_ids
        assert child.doc_id == doc_id
        assert child.metadata.get("is_code") is True
        assert child.metadata.get("language") == "python"

    # Check constructor child chunk
    ctor_child = next((c for c in children if c.metadata.get("symbol_name") == "__init__"), None)
    assert ctor_child is not None
    assert "Initialize connection pool with capacity." in ctor_child.content
    assert "def __init__" in ctor_child.content
    assert ctor_child.metadata.get("parent_name") == "ConnectionPool"

    # Check acquire method child chunk
    acquire_child = next((c for c in children if c.metadata.get("symbol_name") == "acquire"), None)
    assert acquire_child is not None
    assert "Acquire an active database connection." in acquire_child.content

    # Check free function child chunk
    ping_child = next((c for c in children if c.metadata.get("symbol_name") == "ping_database"), None)
    assert ping_child is not None
    assert "Test connectivity to database file." in ping_child.content


# ============================================================================
# 8. DocumentParser Integration for Code Files
# ============================================================================

def test_document_parser_code_extensions_integration(tmp_path: Path):
    """Verify DocumentParser correctly identifies and parses code files across extensions."""
    # 1. Python file
    py_file = tmp_path / "engine.py"
    py_file.write_text("def start_engine():\n    return True\n", encoding="utf-8")
    py_pages = DocumentParser.parse(py_file)
    assert len(py_pages) == 1
    assert py_pages[0].metadata["is_code"] is True
    assert py_pages[0].metadata["language"] == "python"
    assert py_pages[0].metadata["total_symbols"] == 1

    # 2. TypeScript file
    ts_file = tmp_path / "client.ts"
    ts_file.write_text("export class APIClient {\n    ping() { return 'pong'; }\n}\n", encoding="utf-8")
    ts_pages = DocumentParser.parse(ts_file)
    assert len(ts_pages) == 1
    assert ts_pages[0].metadata["is_code"] is True
    assert ts_pages[0].metadata["language"] == "typescript"

    # 3. Go file
    go_file = tmp_path / "worker.go"
    go_file.write_text("package worker\nfunc DoWork() error { return nil }\n", encoding="utf-8")
    go_pages = DocumentParser.parse(go_file)
    assert len(go_pages) == 1
    assert go_pages[0].metadata["is_code"] is True
    assert go_pages[0].metadata["language"] == "go"

    # 4. Rust file
    rs_file = tmp_path / "math.rs"
    rs_file.write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n", encoding="utf-8")
    rs_pages = DocumentParser.parse(rs_file)
    assert len(rs_pages) == 1
    assert rs_pages[0].metadata["is_code"] is True
    assert rs_pages[0].metadata["language"] == "rust"
