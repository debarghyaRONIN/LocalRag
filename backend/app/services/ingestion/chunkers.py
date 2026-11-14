import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend.app.core.config import settings
from backend.app.domain.models import ParentChunk, ChildChunk
from backend.app.services.ingestion.code_parser import CodeParser, CodeSymbol, ParsedCode
from backend.app.services.ingestion.parsers import ParsedPage


def estimate_tokens(text: str) -> int:
    """Fast approximation of token count (~4 characters per token)."""
    return max(1, len(text) // 4)


def split_text_into_windows(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Split text into overlapping windows respecting paragraph and sentence boundaries.
    """
    if len(text) <= chunk_size:
        return [text]

    # Split by double newline first (paragraphs)
    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks = []
    current_chunk = []
    current_length = 0

    for para in paragraphs:
        if current_length + len(para) > chunk_size and current_chunk:
            combined = "".join(current_chunk).strip()
            if combined:
                chunks.append(combined)

            # Retain overlap from trailing portion
            overlap_text = combined[-overlap:] if len(combined) > overlap else ""
            current_chunk = [overlap_text, para]
            current_length = len(overlap_text) + len(para)
        else:
            current_chunk.append(para)
            current_length += len(para)

    if current_chunk:
        combined = "".join(current_chunk).strip()
        if combined:
            chunks.append(combined)

    # Fallback to character-level slicing if any chunk exceeds chunk_size
    final_chunks = []
    step = max(1, chunk_size - overlap)
    for c in chunks:
        if len(c) > chunk_size * 1.5:
            start = 0
            while start < len(c):
                end = min(start + chunk_size, len(c))
                final_chunks.append(c[start:end].strip())
                start += step
        else:
            final_chunks.append(c)

    return [c for c in final_chunks if c]


class ASTCodeChunker:
    """
    AST and language-aware chunker for code repositories.
    Preserves class/method/function boundaries, parent-child relationships,
    signatures, and docstrings across parent and child chunks.
    """

    def __init__(
        self,
        parent_size: int = settings.PARENT_CHUNK_SIZE,
        parent_overlap: int = settings.PARENT_CHUNK_OVERLAP,
        child_size: int = settings.CHILD_CHUNK_SIZE,
        child_overlap: int = settings.CHILD_CHUNK_OVERLAP,
    ):
        self.parent_size = parent_size
        self.parent_overlap = parent_overlap
        self.child_size = child_size
        self.child_overlap = child_overlap

    def chunk_code_file(
        self,
        doc_id: str,
        code: str,
        language: str = "python",
        file_path: Optional[str] = None,
        page_number: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
        parsed_code: Optional[ParsedCode] = None,
    ) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        meta = dict(metadata or {})
        clearance_level = meta.get("clearance_level", 1)
        allowed_departments = meta.get("allowed_departments", [])

        if parsed_code is None:
            parsed_code = CodeParser.parse_code(code, language=language, file_path=file_path)

        parent_chunks: List[ParentChunk] = []
        child_chunks: List[ChildChunk] = []
        parent_idx = 0
        child_idx = 0

        # Step 1: Module overview chunk (Docstring & Imports)
        header_parts = []
        if parsed_code.module_docstring:
            header_parts.append(f"// Module Documentation:\n{parsed_code.module_docstring}")
        if parsed_code.imports:
            imports_str = "\n".join(parsed_code.imports[:30])
            header_parts.append(f"// Imports:\n{imports_str}")

        if header_parts:
            header_text = "\n\n".join(header_parts).strip()
            if header_text:
                p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                p_chunk = ParentChunk(
                    parent_id=p_id,
                    doc_id=doc_id,
                    chunk_index=parent_idx,
                    content=header_text,
                    token_count=estimate_tokens(header_text),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={
                        **meta,
                        "is_code": True,
                        "is_module_header": True,
                        "language": parsed_code.language,
                    },
                )
                parent_chunks.append(p_chunk)
                parent_idx += 1

                c_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
                c_chunk = ChildChunk(
                    chunk_id=c_id,
                    parent_id=p_id,
                    doc_id=doc_id,
                    chunk_index=child_idx,
                    content=header_text,
                    token_count=estimate_tokens(header_text),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={
                        **meta,
                        "is_code": True,
                        "is_module_header": True,
                        "language": parsed_code.language,
                    },
                )
                child_chunks.append(c_chunk)
                child_idx += 1

        # Step 2: Symbol-aware chunking
        if not parsed_code.symbols:
            # Fallback if no structural symbols identified
            p_windows = split_text_into_windows(code, self.parent_size, self.parent_overlap)
            for p_text in p_windows:
                p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                p_chunk = ParentChunk(
                    parent_id=p_id,
                    doc_id=doc_id,
                    chunk_index=parent_idx,
                    content=p_text,
                    token_count=estimate_tokens(p_text),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={**meta, "is_code": True, "language": parsed_code.language},
                )
                parent_chunks.append(p_chunk)
                parent_idx += 1

                c_windows = split_text_into_windows(p_text, self.child_size, self.child_overlap)
                for c_text in c_windows:
                    c_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
                    c_chunk = ChildChunk(
                        chunk_id=c_id,
                        parent_id=p_id,
                        doc_id=doc_id,
                        chunk_index=child_idx,
                        content=c_text,
                        token_count=estimate_tokens(c_text),
                        page_number=page_number,
                        clearance_level=clearance_level,
                        allowed_departments=allowed_departments,
                        metadata={**meta, "is_code": True, "language": parsed_code.language},
                    )
                    child_chunks.append(c_chunk)
                    child_idx += 1

            return parent_chunks, child_chunks

        for symbol in parsed_code.symbols:
            # Container symbols: class, struct, interface, trait, impl
            if symbol.children:
                p_idx, c_idx = self._chunk_container_symbol(
                    doc_id=doc_id,
                    symbol=symbol,
                    parent_chunks=parent_chunks,
                    child_chunks=child_chunks,
                    parent_idx=parent_idx,
                    child_idx=child_idx,
                    page_number=page_number,
                    metadata=meta,
                    language=parsed_code.language,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                )
                parent_idx = p_idx
                child_idx = c_idx

            else:
                # Standalone functions or symbols without children
                p_idx, c_idx = self._chunk_standalone_symbol(
                    doc_id=doc_id,
                    symbol=symbol,
                    parent_chunks=parent_chunks,
                    child_chunks=child_chunks,
                    parent_idx=parent_idx,
                    child_idx=child_idx,
                    page_number=page_number,
                    metadata=meta,
                    language=parsed_code.language,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                )
                parent_idx = p_idx
                child_idx = c_idx

        return parent_chunks, child_chunks

    def _chunk_container_symbol(
        self,
        doc_id: str,
        symbol: CodeSymbol,
        parent_chunks: List[ParentChunk],
        child_chunks: List[ChildChunk],
        parent_idx: int,
        child_idx: int,
        page_number: int,
        metadata: Dict[str, Any],
        language: str,
        clearance_level: int,
        allowed_departments: List[str],
    ) -> Tuple[int, int]:
        container_header = []
        container_header.append(f"// {symbol.symbol_type.capitalize()}: {symbol.name} (Lines {symbol.start_line}-{symbol.end_line})")
        if symbol.signature:
            container_header.append(f"// Signature: {symbol.signature}")
        if symbol.docstring:
            container_header.append(f"// Docstring: {symbol.docstring}")
        header_text = "\n".join(container_header)

        # Check if entire container fits within parent_size
        full_code = f"{header_text}\n\n{symbol.code}".strip()

        if len(full_code) <= self.parent_size:
            p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
            p_chunk = ParentChunk(
                parent_id=p_id,
                doc_id=doc_id,
                chunk_index=parent_idx,
                content=full_code,
                token_count=estimate_tokens(full_code),
                page_number=page_number,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments,
                metadata={
                    **metadata,
                    "is_code": True,
                    "language": language,
                    "symbol_name": symbol.name,
                    "symbol_type": symbol.symbol_type,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                },
            )
            parent_chunks.append(p_chunk)
            parent_idx += 1

            # Build child chunk for each method
            for child_sym in symbol.children:
                c_idx = self._emit_child_chunks_for_symbol(
                    doc_id=doc_id,
                    parent_id=p_id,
                    symbol=child_sym,
                    parent_symbol_name=symbol.name,
                    child_chunks=child_chunks,
                    child_idx=child_idx,
                    page_number=page_number,
                    metadata=metadata,
                    language=language,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                )
                child_idx = c_idx

        else:
            # Large container: group methods into parent chunks <= parent_size
            current_methods_batch: List[CodeSymbol] = []
            current_batch_len = len(header_text)

            for child_sym in symbol.children:
                method_len = len(child_sym.code) + 50
                if current_batch_len + method_len > self.parent_size and current_methods_batch:
                    # Flush batch to a parent chunk
                    batch_code = header_text + "\n\n" + "\n\n".join(m.code for m in current_methods_batch)
                    p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                    p_chunk = ParentChunk(
                        parent_id=p_id,
                        doc_id=doc_id,
                        chunk_index=parent_idx,
                        content=batch_code,
                        token_count=estimate_tokens(batch_code),
                        page_number=page_number,
                        clearance_level=clearance_level,
                        allowed_departments=allowed_departments,
                        metadata={
                            **metadata,
                            "is_code": True,
                            "language": language,
                            "symbol_name": symbol.name,
                            "symbol_type": symbol.symbol_type,
                        },
                    )
                    parent_chunks.append(p_chunk)
                    parent_idx += 1

                    for m in current_methods_batch:
                        child_idx = self._emit_child_chunks_for_symbol(
                            doc_id=doc_id,
                            parent_id=p_id,
                            symbol=m,
                            parent_symbol_name=symbol.name,
                            child_chunks=child_chunks,
                            child_idx=child_idx,
                            page_number=page_number,
                            metadata=metadata,
                            language=language,
                            clearance_level=clearance_level,
                            allowed_departments=allowed_departments,
                        )

                    current_methods_batch = [child_sym]
                    current_batch_len = len(header_text) + method_len
                else:
                    current_methods_batch.append(child_sym)
                    current_batch_len += method_len

            if current_methods_batch:
                batch_code = header_text + "\n\n" + "\n\n".join(m.code for m in current_methods_batch)
                p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                p_chunk = ParentChunk(
                    parent_id=p_id,
                    doc_id=doc_id,
                    chunk_index=parent_idx,
                    content=batch_code,
                    token_count=estimate_tokens(batch_code),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={
                        **metadata,
                        "is_code": True,
                        "language": language,
                        "symbol_name": symbol.name,
                        "symbol_type": symbol.symbol_type,
                    },
                )
                parent_chunks.append(p_chunk)
                parent_idx += 1

                for m in current_methods_batch:
                    child_idx = self._emit_child_chunks_for_symbol(
                        doc_id=doc_id,
                        parent_id=p_id,
                        symbol=m,
                        parent_symbol_name=symbol.name,
                        child_chunks=child_chunks,
                        child_idx=child_idx,
                        page_number=page_number,
                        metadata=metadata,
                        language=language,
                        clearance_level=clearance_level,
                        allowed_departments=allowed_departments,
                    )

        return parent_idx, child_idx

    def _chunk_standalone_symbol(
        self,
        doc_id: str,
        symbol: CodeSymbol,
        parent_chunks: List[ParentChunk],
        child_chunks: List[ChildChunk],
        parent_idx: int,
        child_idx: int,
        page_number: int,
        metadata: Dict[str, Any],
        language: str,
        clearance_level: int,
        allowed_departments: List[str],
    ) -> Tuple[int, int]:
        func_headers = []
        func_headers.append(f"// {symbol.symbol_type.capitalize()}: {symbol.name} (Lines {symbol.start_line}-{symbol.end_line})")
        if symbol.signature:
            func_headers.append(f"// Signature: {symbol.signature}")
        if symbol.docstring:
            func_headers.append(f"// Docstring: {symbol.docstring}")
        header_text = "\n".join(func_headers)

        full_code = f"{header_text}\n\n{symbol.code}".strip()

        if len(full_code) <= self.parent_size:
            p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
            p_chunk = ParentChunk(
                parent_id=p_id,
                doc_id=doc_id,
                chunk_index=parent_idx,
                content=full_code,
                token_count=estimate_tokens(full_code),
                page_number=page_number,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments,
                metadata={
                    **metadata,
                    "is_code": True,
                    "language": language,
                    "symbol_name": symbol.name,
                    "symbol_type": symbol.symbol_type,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                },
            )
            parent_chunks.append(p_chunk)
            parent_idx += 1

            child_idx = self._emit_child_chunks_for_symbol(
                doc_id=doc_id,
                parent_id=p_id,
                symbol=symbol,
                parent_symbol_name=None,
                child_chunks=child_chunks,
                child_idx=child_idx,
                page_number=page_number,
                metadata=metadata,
                language=language,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments,
            )
        else:
            # Sliced parent windows with header preserved
            windows = split_text_into_windows(symbol.code, self.parent_size - len(header_text) - 20, self.parent_overlap)
            for w_idx, win in enumerate(windows):
                p_text = f"{header_text} [Part {w_idx + 1}]\n\n{win}"
                p_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                p_chunk = ParentChunk(
                    parent_id=p_id,
                    doc_id=doc_id,
                    chunk_index=parent_idx,
                    content=p_text,
                    token_count=estimate_tokens(p_text),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={
                        **metadata,
                        "is_code": True,
                        "language": language,
                        "symbol_name": symbol.name,
                        "symbol_type": symbol.symbol_type,
                        "part": w_idx + 1,
                    },
                )
                parent_chunks.append(p_chunk)
                parent_idx += 1

                # Subdivide into child chunks
                c_windows = split_text_into_windows(win, self.child_size - len(header_text) - 20, self.child_overlap)
                for cw in c_windows:
                    c_text = f"{header_text}\n\n{cw}"
                    c_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
                    c_chunk = ChildChunk(
                        chunk_id=c_id,
                        parent_id=p_id,
                        doc_id=doc_id,
                        chunk_index=child_idx,
                        content=c_text,
                        token_count=estimate_tokens(c_text),
                        page_number=page_number,
                        clearance_level=clearance_level,
                        allowed_departments=allowed_departments,
                        metadata={
                            **metadata,
                            "is_code": True,
                            "language": language,
                            "symbol_name": symbol.name,
                            "symbol_type": symbol.symbol_type,
                        },
                    )
                    child_chunks.append(c_chunk)
                    child_idx += 1

        return parent_idx, child_idx

    def _emit_child_chunks_for_symbol(
        self,
        doc_id: str,
        parent_id: str,
        symbol: CodeSymbol,
        parent_symbol_name: Optional[str],
        child_chunks: List[ChildChunk],
        child_idx: int,
        page_number: int,
        metadata: Dict[str, Any],
        language: str,
        clearance_level: int,
        allowed_departments: List[str],
    ) -> int:
        scope = f"{parent_symbol_name}.{symbol.name}" if parent_symbol_name else symbol.name
        headers = []
        headers.append(f"// Scope: {scope} ({symbol.symbol_type}) [Lines {symbol.start_line}-{symbol.end_line}]")
        if symbol.signature:
            headers.append(f"// Signature: {symbol.signature}")
        if symbol.docstring:
            headers.append(f"// Docstring: {symbol.docstring}")
        header_text = "\n".join(headers)

        full_content = f"{header_text}\n\n{symbol.code}".strip()

        if len(full_content) <= self.child_size:
            c_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
            c_chunk = ChildChunk(
                chunk_id=c_id,
                parent_id=parent_id,
                doc_id=doc_id,
                chunk_index=child_idx,
                content=full_content,
                token_count=estimate_tokens(full_content),
                page_number=page_number,
                clearance_level=clearance_level,
                allowed_departments=allowed_departments,
                metadata={
                    **metadata,
                    "is_code": True,
                    "language": language,
                    "symbol_name": symbol.name,
                    "symbol_type": symbol.symbol_type,
                    "parent_name": parent_symbol_name or symbol.parent_name,
                    "signature": symbol.signature,
                    "docstring": symbol.docstring,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                },
            )
            child_chunks.append(c_chunk)
            child_idx += 1
        else:
            # Windowing for long functions/methods, always preserving docstring and signature
            windows = split_text_into_windows(
                symbol.code,
                chunk_size=max(100, self.child_size - len(header_text) - 20),
                overlap=self.child_overlap,
            )
            for w_idx, win in enumerate(windows):
                c_text = f"{header_text} [Part {w_idx + 1}]\n\n{win}"
                c_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
                c_chunk = ChildChunk(
                    chunk_id=c_id,
                    parent_id=parent_id,
                    doc_id=doc_id,
                    chunk_index=child_idx,
                    content=c_text,
                    token_count=estimate_tokens(c_text),
                    page_number=page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata={
                        **metadata,
                        "is_code": True,
                        "language": language,
                        "symbol_name": symbol.name,
                        "symbol_type": symbol.symbol_type,
                        "parent_name": parent_symbol_name or symbol.parent_name,
                        "signature": symbol.signature,
                        "docstring": symbol.docstring,
                        "part": w_idx + 1,
                    },
                )
                child_chunks.append(c_chunk)
                child_idx += 1

        return child_idx


class HierarchicalChunker:
    """
    Produces Parent-Child chunks:
    - Small child chunks are embedded into the vector database for high semantic precision.
    - Large parent chunks are retrieved and provided to the LLM to preserve complete context.
    - Automatically applies AST / code-aware chunking for source code documents.
    """

    def __init__(
        self,
        parent_size: int = settings.PARENT_CHUNK_SIZE,
        parent_overlap: int = settings.PARENT_CHUNK_OVERLAP,
        child_size: int = settings.CHILD_CHUNK_SIZE,
        child_overlap: int = settings.CHILD_CHUNK_OVERLAP,
    ):
        self.parent_size = parent_size
        self.parent_overlap = parent_overlap
        self.child_size = child_size
        self.child_overlap = child_overlap
        self.ast_chunker = ASTCodeChunker(
            parent_size=parent_size,
            parent_overlap=parent_overlap,
            child_size=child_size,
            child_overlap=child_overlap,
        )

    def chunk_code(
        self,
        doc_id: str,
        code: str,
        language: str = "python",
        file_path: Optional[str] = None,
        page_number: int = 1,
        metadata: Optional[dict] = None,
        parsed_code: Optional[ParsedCode] = None,
    ) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        """
        Direct entry point for AST-aware code chunking.
        """
        return self.ast_chunker.chunk_code_file(
            doc_id=doc_id,
            code=code,
            language=language,
            file_path=file_path,
            page_number=page_number,
            metadata=metadata,
            parsed_code=parsed_code,
        )

    def chunk_document(
        self,
        doc_id: str,
        pages: List[ParsedPage],
        metadata: dict = None,
    ) -> Tuple[List[ParentChunk], List[ChildChunk]]:
        parent_chunks: List[ParentChunk] = []
        child_chunks: List[ChildChunk] = []
        parent_idx = 0
        child_idx = 0
        doc_meta = dict(metadata or {})
        clearance_level = doc_meta.get("clearance_level", 1)
        allowed_departments = doc_meta.get("allowed_departments", [])

        for page in pages:
            raw_text = page.text.strip()
            if not raw_text:
                continue

            page_meta = {**doc_meta, **getattr(page, "metadata", {})}

            # If document page represents source code, invoke AST-aware chunking
            if page_meta.get("is_code"):
                code_lang = page_meta.get("language", "python")
                parsed_data = page_meta.get("parsed_code")
                parsed_code = None
                if isinstance(parsed_data, dict):
                    # Reconstruct ParsedCode object or let ast_chunker re-parse
                    parsed_code = CodeParser.parse_code(raw_text, language=code_lang)

                p_chunks, c_chunks = self.ast_chunker.chunk_code_file(
                    doc_id=doc_id,
                    code=raw_text,
                    language=code_lang,
                    page_number=page.page_number,
                    metadata=page_meta,
                    parsed_code=parsed_code,
                )

                # Re-index to ensure contiguous chunk_index across pages
                for p in p_chunks:
                    p.chunk_index = parent_idx
                    parent_chunks.append(p)
                    parent_idx += 1

                for c in c_chunks:
                    c.chunk_index = child_idx
                    child_chunks.append(c)
                    child_idx += 1

                continue

            # Default text windowing for non-code documents (PDF, DOCX, CSV, Web, Markdown)
            parent_texts = split_text_into_windows(
                raw_text,
                chunk_size=self.parent_size,
                overlap=self.parent_overlap,
            )

            for p_text in parent_texts:
                parent_id = f"{doc_id}_p{parent_idx}_{uuid.uuid4().hex[:8]}"
                p_chunk = ParentChunk(
                    parent_id=parent_id,
                    doc_id=doc_id,
                    chunk_index=parent_idx,
                    content=p_text,
                    token_count=estimate_tokens(p_text),
                    page_number=page.page_number,
                    clearance_level=clearance_level,
                    allowed_departments=allowed_departments,
                    metadata=page_meta,
                )
                parent_chunks.append(p_chunk)
                parent_idx += 1

                # Step 2: Create child chunks within each parent chunk
                child_texts = split_text_into_windows(
                    p_text,
                    chunk_size=self.child_size,
                    overlap=self.child_overlap,
                )

                for c_text in child_texts:
                    child_id = f"{doc_id}_c{child_idx}_{uuid.uuid4().hex[:8]}"
                    c_chunk = ChildChunk(
                        chunk_id=child_id,
                        parent_id=parent_id,
                        doc_id=doc_id,
                        chunk_index=child_idx,
                        content=c_text,
                        token_count=estimate_tokens(c_text),
                        page_number=page.page_number,
                        clearance_level=clearance_level,
                        allowed_departments=allowed_departments,
                        metadata=page_meta,
                    )
                    child_chunks.append(c_chunk)
                    child_idx += 1

        return parent_chunks, child_chunks
