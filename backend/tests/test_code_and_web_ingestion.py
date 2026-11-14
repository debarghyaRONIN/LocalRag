import os
from pathlib import Path
import pytest

from backend.app.services.ingestion.code_parser import CodeParser, CodeSymbolType
from backend.app.services.ingestion.web_parser import WebParser
from backend.app.services.ingestion.parsers import DocumentParser
from backend.app.services.ingestion.chunkers import HierarchicalChunker, ASTCodeChunker


# ============================================================================
# 1. CodeParser Multi-Language Unit Tests
# ============================================================================

def test_code_parser_python():
    py_code = '''"""
Vector Search Module
High performance vector search routines.
"""

import math
from typing import List, Optional

class VectorIndex:
    """In-memory vector similarity index."""

    def __init__(self, dimension: int):
        """Initialize index with embedding dimension."""
        self.dimension = dimension
        self.vectors = []

    def add_vector(self, vector: List[float]) -> int:
        """Add embedding vector to the index."""
        self.vectors.append(vector)
        return len(self.vectors) - 1

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
'''
    parsed = CodeParser.parse_code(py_code, language="python")

    # Module docstring and imports
    assert parsed.module_docstring is not None
    assert "Vector Search Module" in parsed.module_docstring
    assert len(parsed.imports) >= 2
    assert "import math" in parsed.imports[0]

    # Class & Methods
    class_sym = next(s for s in parsed.symbols if s.name == "VectorIndex")
    assert class_sym.symbol_type == CodeSymbolType.CLASS.value
    assert class_sym.docstring == "In-memory vector similarity index."
    assert class_sym.start_line == 9
    assert class_sym.end_line >= 19

    # Children relationship
    assert len(class_sym.children) == 2
    ctor = next(c for c in class_sym.children if c.name == "__init__")
    assert ctor.symbol_type == CodeSymbolType.CONSTRUCTOR.value
    assert ctor.parent_name == "VectorIndex"
    assert ctor.docstring == "Initialize index with embedding dimension."

    add_vec = next(c for c in class_sym.children if c.name == "add_vector")
    assert add_vec.symbol_type == CodeSymbolType.METHOD.value
    assert add_vec.parent_name == "VectorIndex"
    assert "def add_vector" in add_vec.signature

    # Free function
    func_sym = next(s for s in parsed.symbols if s.name == "cosine_similarity")
    assert func_sym.symbol_type == CodeSymbolType.FUNCTION.value
    assert func_sym.parent_name is None
    assert func_sym.docstring == "Compute cosine similarity between two float vectors."


def test_code_parser_typescript_javascript():
    ts_code = '''import { Request, Response } from 'express';
import { Database } from '../db';

/**
 * Controller managing sovereign intelligence feedback.
 */
export class FeedbackController {
    private db: Database;

    constructor(db: Database) {
        this.db = db;
    }

    /**
     * Records expert feedback with citations.
     */
    async submitFeedback(req: Request, res: Response): Promise<void> {
        res.status(200).json({ success: true });
    }
}

export function validatePayload(payload: any): boolean {
    return payload && payload.rating !== undefined;
}
'''
    parsed = CodeParser.parse_code(ts_code, language="typescript")

    assert len(parsed.imports) == 2
    ctrl = next(s for s in parsed.symbols if s.name == "FeedbackController")
    assert ctrl.symbol_type == CodeSymbolType.CLASS.value
    assert ctrl.docstring is not None and "FeedbackController" in ctrl.signature

    # Verify methods inside class
    assert len(ctrl.children) == 2
    ctor = next(c for c in ctrl.children if c.name == "constructor")
    assert ctor.parent_name == "FeedbackController"

    method = next(c for c in ctrl.children if c.name == "submitFeedback")
    assert method.parent_name == "FeedbackController"
    assert method.docstring == "Records expert feedback with citations."

    # Top level function
    val_fn = next(s for s in parsed.symbols if s.name == "validatePayload")
    assert val_fn.symbol_type == CodeSymbolType.FUNCTION.value


def test_code_parser_go():
    go_code = '''package ingestion

import (
    "fmt"
    "net/http"
)

// Pipeline manages asynchronous document ingestion
type Pipeline struct {
    Workers int
}

// IngestBatch processes incoming file slices
func (p *Pipeline) IngestBatch(files []string) error {
    return nil
}

func NewPipeline(workers int) *Pipeline {
    return &Pipeline{Workers: workers}
}
'''
    parsed = CodeParser.parse_code(go_code, language="go")

    assert len(parsed.imports) >= 2
    pipe = next(s for s in parsed.symbols if s.name == "Pipeline")
    assert pipe.symbol_type == CodeSymbolType.STRUCT.value
    assert pipe.docstring == "Pipeline manages asynchronous document ingestion"

    # Go receiver method attached as child of Pipeline
    assert len(pipe.children) == 1
    method = pipe.children[0]
    assert method.name == "IngestBatch"
    assert method.parent_name == "Pipeline"
    assert method.docstring == "IngestBatch processes incoming file slices"

    # Free function
    new_fn = next(s for s in parsed.symbols if s.name == "NewPipeline")
    assert new_fn.symbol_type == CodeSymbolType.FUNCTION.value


def test_code_parser_rust():
    rust_code = '''use std::sync::Arc;

/// AuditLedger maintains cryptographically chained records
pub struct AuditLedger {
    genesis: String,
}

impl AuditLedger {
    /// Creates a new audit ledger instance
    pub fn new(genesis: String) -> Self {
        Self { genesis }
    }

    /// Verifies cryptographic hashes
    pub async fn verify_chain(&self) -> bool {
        true
    }
}

pub fn default_genesis() -> String {
    "00000000".to_string()
}
'''
    parsed = CodeParser.parse_code(rust_code, language="rust")

    assert len(parsed.imports) == 1
    struct_sym = next(s for s in parsed.symbols if s.name == "AuditLedger" and s.symbol_type == "struct")
    assert struct_sym.docstring == "AuditLedger maintains cryptographically chained records"

    impl_sym = next(s for s in parsed.symbols if s.name == "AuditLedger" and s.symbol_type == "impl")
    assert len(impl_sym.children) == 2
    m1 = next(c for c in impl_sym.children if c.name == "new")
    assert m1.parent_name == "AuditLedger"
    assert m1.docstring == "Creates a new audit ledger instance"

    free_fn = next(s for s in parsed.symbols if s.name == "default_genesis")
    assert free_fn.symbol_type == CodeSymbolType.FUNCTION.value


def test_code_parser_java():
    java_code = '''package com.sovereign.compliance;

import java.util.List;
import java.security.MessageDigest;

/**
 * Service managing RBAC clearance validation
 */
public class ClearanceService {
    private int defaultClearance;

    public ClearanceService(int defaultClearance) {
        this.defaultClearance = defaultClearance;
    }

    public boolean validateAccess(int userClearance, int requiredClearance) {
        return userClearance >= requiredClearance;
    }
}
'''
    parsed = CodeParser.parse_code(java_code, language="java")

    assert len(parsed.imports) == 2
    svc = next(s for s in parsed.symbols if s.name == "ClearanceService")
    assert svc.symbol_type == CodeSymbolType.CLASS.value
    assert len(svc.children) == 2

    ctor = next(c for c in svc.children if c.name == "ClearanceService")
    assert ctor.symbol_type == CodeSymbolType.CONSTRUCTOR.value
    assert ctor.parent_name == "ClearanceService"

    meth = next(c for c in svc.children if c.name == "validateAccess")
    assert meth.symbol_type == CodeSymbolType.METHOD.value
    assert meth.parent_name == "ClearanceService"


def test_code_parser_cpp():
    cpp_code = '''#include <iostream>
#include <string>
#include <vector>

class StorageEngine {
public:
    StorageEngine(const std::string& path) {}
    bool flush();
};

bool StorageEngine::flush() {
    return true;
}

int calculate_checksum(const std::string& data) {
    return 42;
}
'''
    parsed = CodeParser.parse_code(cpp_code, language="cpp")

    assert len(parsed.imports) == 3
    engine = next(s for s in parsed.symbols if s.name == "StorageEngine")
    assert engine.symbol_type == CodeSymbolType.CLASS.value

    # Out of line method attached to StorageEngine
    assert any(c.name == "flush" and c.parent_name == "StorageEngine" for c in engine.children)

    # Free function
    chk_fn = next(s for s in parsed.symbols if s.name == "calculate_checksum")
    assert chk_fn.symbol_type == CodeSymbolType.FUNCTION.value


# ============================================================================
# 2. WebParser Unit Tests
# ============================================================================

def test_web_parser_strips_noise_and_extracts_markdown():
    html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <title>Air-Gapped Sovereign AI Architecture</title>
    <meta name="description" content="Technical guide for zero-egress RAG architectures." />
    <meta name="author" content="DeepMind" />
</head>
<body>
    <header class="top-nav">
        <nav><a href="/">Home</a><a href="/login">Login</a></nav>
    </header>
    <aside class="sidebar-wrapper">
        <div class="ad-banner">Sponsored Ad: Cloud GPUs</div>
    </aside>
    <main>
        <h1>Air-Gapped Sovereign AI Architecture</h1>
        <p>Enterprise workloads require strict <strong>isolation</strong> from third-party APIs.</p>
        <h2>Key Requirements</h2>
        <ul>
            <li>Zero internet egress</li>
            <li>Local vector store persistence</li>
            <li>Deterministic audit ledger</li>
        </ul>
        <h3>Hardware Specifications</h3>
        <table>
            <thead>
                <tr><th>Component</th><th>Recommended</th></tr>
            </thead>
            <tbody>
                <tr><td>GPU VRAM</td><td>16 GB+</td></tr>
                <tr><td>RAM</td><td>32 GB+</td></tr>
            </tbody>
        </table>
        <pre><code>python scripts/package_airgap.py</code></pre>
    </main>
    <footer class="footer-section">
        <div class="cookie-notice">We use tracking cookies.</div>
        <p>&copy; 2026 Sovereign Corp.</p>
    </footer>
</body>
</html>
'''
    content = WebParser.parse_html(html_content)

    # Metadata extraction
    assert content.title == "Air-Gapped Sovereign AI Architecture"
    assert content.description == "Technical guide for zero-egress RAG architectures."
    assert content.metadata["author"] == "DeepMind"

    # Headings extracted
    headings_text = [h.text for h in content.headings]
    assert "Air-Gapped Sovereign AI Architecture" in headings_text
    assert "Key Requirements" in headings_text
    assert "Hardware Specifications" in headings_text

    # Verify noise stripped
    md = content.main_content_markdown
    assert "Sponsored Ad" not in md
    assert "tracking cookies" not in md
    assert "Login" not in md

    # Verify structured elements converted to Markdown
    assert "## Key Requirements" in md
    assert "- Zero internet egress" in md
    assert "- Local vector store persistence" in md
    assert "| Component | Recommended |" in md
    assert "| GPU VRAM | 16 GB+ |" in md
    assert "```\npython scripts/package_airgap.py\n```" in md


# ============================================================================
# 3. DocumentParser Integration Tests (.py, .ts, .go, .rs, .html)
# ============================================================================

def test_document_parser_code_files(tmp_path: Path):
    # Test Python file
    py_path = tmp_path / "service.py"
    py_path.write_text("class DemoService:\n    def run(self):\n        return True\n", encoding="utf-8")
    py_pages = DocumentParser.parse(py_path)
    assert len(py_pages) == 1
    assert py_pages[0].metadata["is_code"] is True
    assert py_pages[0].metadata["language"] == "python"
    assert py_pages[0].metadata["total_symbols"] == 1

    # Test Go file
    go_path = tmp_path / "server.go"
    go_path.write_text("package main\nfunc Main() {}\n", encoding="utf-8")
    go_pages = DocumentParser.parse(go_path)
    assert len(go_pages) == 1
    assert go_pages[0].metadata["is_code"] is True
    assert go_pages[0].metadata["language"] == "go"

    # Test Rust file
    rs_path = tmp_path / "lib.rs"
    rs_path.write_text("pub fn calculate() -> i32 { 100 }\n", encoding="utf-8")
    rs_pages = DocumentParser.parse(rs_path)
    assert len(rs_pages) == 1
    assert rs_pages[0].metadata["is_code"] is True
    assert rs_pages[0].metadata["language"] == "rust"


def test_document_parser_html_file(tmp_path: Path):
    html_path = tmp_path / "page.html"
    html_path.write_text(
        "<html><head><title>Test Page</title><meta name='description' content='Desc'/></head>"
        "<body><main><h1>Main Article</h1><p>Body content here.</p></main></body></html>",
        encoding="utf-8"
    )
    pages = DocumentParser.parse(html_path)
    assert len(pages) == 1
    assert pages[0].metadata["is_web"] is True
    assert pages[0].metadata["title"] == "Test Page"
    assert "Main Article" in pages[0].text
    assert "Body content here." in pages[0].text


# ============================================================================
# 4. AST / Code-Aware Chunking Unit Tests
# ============================================================================

def test_hierarchical_chunker_ast_code():
    code = '''"""
Cryptography utilities for Sovereign Intelligence.
"""
import hashlib

class HashEngine:
    """Computes cryptographic hashes."""

    def __init__(self, algorithm: str = "sha256"):
        """Initialize algorithm."""
        self.algorithm = algorithm

    def hash_bytes(self, data: bytes) -> str:
        """Hash binary payload."""
        return hashlib.sha256(data).hexdigest()

def compute_string_hash(text: str) -> str:
    """Helper to hash string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
'''
    chunker = HierarchicalChunker(
        parent_size=500,
        parent_overlap=50,
        child_size=200,
        child_overlap=30,
    )

    doc_id = "doc_code_test_01"
    parsed_code = CodeParser.parse_code(code, language="python")
    parents, children = chunker.chunk_code(
        doc_id=doc_id,
        code=code,
        language="python",
        parsed_code=parsed_code,
    )

    assert len(parents) >= 2
    assert len(children) >= 3

    # All children must link to a valid parent_id
    parent_ids = {p.parent_id for p in parents}
    for child in children:
        assert child.parent_id in parent_ids
        assert child.doc_id == doc_id
        assert child.metadata["is_code"] is True

    # Check that method child chunks preserve signature and docstring
    ctor_child = next((c for c in children if c.metadata.get("symbol_name") == "__init__"), None)
    assert ctor_child is not None
    assert "Initialize algorithm." in ctor_child.content
    assert "def __init__" in ctor_child.content
    assert ctor_child.metadata["parent_name"] == "HashEngine"

    hash_child = next((c for c in children if c.metadata.get("symbol_name") == "hash_bytes"), None)
    assert hash_child is not None
    assert "Hash binary payload." in hash_child.content
    assert "def hash_bytes" in hash_child.content
    assert hash_child.metadata["parent_name"] == "HashEngine"

    func_child = next((c for c in children if c.metadata.get("symbol_name") == "compute_string_hash"), None)
    assert func_child is not None
    assert "Helper to hash string." in func_child.content


def test_chunker_document_code_metadata_dispatch(tmp_path: Path):
    py_file = tmp_path / "models.py"
    py_file.write_text(
        "class UserModel:\n"
        "    '''Represents database user.'''\n"
        "    def get_id(self):\n"
        "        '''Returns user id.'''\n"
        "        return 1\n",
        encoding="utf-8"
    )

    pages = DocumentParser.parse(py_file)
    chunker = HierarchicalChunker()
    parents, children = chunker.chunk_document("doc_py_001", pages)

    assert len(parents) >= 1
    assert len(children) >= 1
    assert any(c.metadata.get("symbol_name") == "get_id" for c in children)
    assert any("Returns user id." in c.content for c in children)
