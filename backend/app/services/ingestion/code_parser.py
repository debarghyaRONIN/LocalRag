"""
Language-aware source code parser for multi-source knowledge engine ingestion.

Extracts functions, classes, methods, imports, module docstrings, and symbol names
with structural boundaries, signatures, and exact line numbers while preserving
parent-child relationships between classes, methods, and inner functions across
Python, JavaScript, TypeScript, Java, Go, Rust, C, and C++.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union


class CodeSymbolType(str, Enum):
    MODULE_DOCSTRING = "module_docstring"
    IMPORT = "import"
    CLASS = "class"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    FUNCTION = "function"
    STRUCT = "struct"
    INTERFACE = "interface"
    ENUM = "enum"
    TRAIT = "trait"
    IMPL = "impl"
    NAMESPACE = "namespace"
    TYPE_ALIAS = "type"


@dataclass
class CodeSymbol:
    name: str
    symbol_type: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    docstring: Optional[str] = None
    code: str = ""
    parent_name: Optional[str] = None
    children: List["CodeSymbol"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
            "code": self.code,
            "parent_name": self.parent_name,
            "children": [c.to_dict() for c in self.children],
            "metadata": self.metadata,
        }


@dataclass
class ParsedCode:
    file_path: Optional[str]
    language: str
    module_docstring: Optional[str]
    imports: List[str]
    symbols: List[CodeSymbol]
    raw_code: str
    total_lines: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "module_docstring": self.module_docstring,
            "imports": self.imports,
            "symbols": [s.to_dict() for s in self.symbols],
            "total_lines": self.total_lines,
        }


EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".c++": "cpp",
    ".h++": "cpp",
}


def find_matching_brace(text: str, start_brace_pos: int) -> int:
    """
    Find index of matching closing brace '}' for the opening brace '{' at start_brace_pos.
    Properly skips braces within single/double/backtick quotes, line comments, and block comments.
    """
    depth = 0
    i = start_brace_pos
    n = len(text)
    in_string = None
    in_line_comment = False
    in_block_comment = False

    while i < n:
        c = text[i]
        c2 = text[i:i + 2] if i + 1 < n else ""

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if c2 == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_string is not None:
            if c == "\\":
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue

        if c2 == "//":
            in_line_comment = True
            i += 2
            continue

        if c2 == "/*":
            in_block_comment = True
            i += 2
            continue

        if c in ('"', "'", "`"):
            in_string = c
            i += 1
            continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i

        i += 1

    return -1


def extract_preceding_comment(lines: List[str], decl_line_idx: int) -> Tuple[Optional[str], int]:
    """
    Look upward from line index `decl_line_idx` to collect docstrings and comment headers.
    Returns (cleaned_comment_text, start_line_idx_0_based).
    """
    comment_lines = []
    i = decl_line_idx - 1
    while i >= 0:
        line = lines[i].strip()
        if not line:
            # Stop if empty line separates comment from declaration
            break
        if (
            line.startswith("//")
            or line.startswith("///")
            or line.startswith("/*")
            or line.startswith("*")
            or line.endswith("*/")
        ):
            comment_lines.append(line)
            i -= 1
        elif line.startswith("@"):
            # Annotation / decorator in Java/TS
            i -= 1
        else:
            break

    if comment_lines:
        comment_lines.reverse()
        cleaned = []
        for cl in comment_lines:
            cl = cl.lstrip("/*").rstrip("*/").lstrip("/").strip()
            if cl.startswith("*"):
                cl = cl[1:].strip()
            if cl:
                cleaned.append(cl)
        return "\n".join(cleaned), i + 1

    return None, decl_line_idx


def extract_module_docstring_fallback(code: str) -> Optional[str]:
    """
    Extract top-of-file comments (lines 1..N before declarations) for non-Python languages.
    """
    lines = code.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None

    first = lines[i].strip()
    doc_lines = []
    if first.startswith("/*"):
        while i < len(lines):
            line = lines[i].strip()
            doc_lines.append(line)
            if "*/" in line:
                break
            i += 1
        cleaned = [
            l.lstrip("/*").rstrip("*/").lstrip("*").strip()
            for l in doc_lines
            if l.strip()
        ]
        return "\n".join(cleaned)
    elif first.startswith("//") or first.startswith("///"):
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("//") or line.startswith("///"):
                doc_lines.append(line.lstrip("/").strip())
                i += 1
            else:
                break
        return "\n".join(doc_lines)
    return None


class PythonCodeParser:
    """AST-based code parser for Python."""

    @staticmethod
    def parse(code: str, file_path: Optional[str] = None) -> ParsedCode:
        lines = code.splitlines()
        total_lines = len(lines)
        imports: List[str] = []
        symbols: List[CodeSymbol] = []
        module_docstring: Optional[str] = None

        try:
            tree = ast.parse(code)
            module_docstring = ast.get_docstring(tree)

            # Collect imports and top-level definitions
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imp = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
                        imports.append(f"import {imp}")
                elif isinstance(node, ast.ImportFrom):
                    names = ", ".join(
                        a.name if not a.asname else f"{a.name} as {a.asname}"
                        for a in node.names
                    )
                    dots = "." * (node.level or 0)
                    mod = node.module or ""
                    imports.append(f"from {dots}{mod} import {names}")

                elif isinstance(node, ast.ClassDef):
                    class_start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                    class_end = getattr(node, "end_lineno", node.lineno)
                    class_doc = ast.get_docstring(node)
                    class_sig = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else f"class {node.name}:"
                    class_code = "\n".join(lines[class_start - 1 : class_end])

                    class_symbol = CodeSymbol(
                        name=node.name,
                        symbol_type=CodeSymbolType.CLASS.value,
                        start_line=class_start,
                        end_line=class_end,
                        signature=class_sig,
                        docstring=class_doc,
                        code=class_code,
                        parent_name=None,
                        children=[],
                        metadata={"bases": [ast.unparse(b) for b in node.bases]},
                    )

                    # Methods and nested items
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            m_start = item.decorator_list[0].lineno if item.decorator_list else item.lineno
                            m_end = getattr(item, "end_lineno", item.lineno)
                            m_doc = ast.get_docstring(item)
                            m_sig = lines[item.lineno - 1].strip() if item.lineno <= len(lines) else f"def {item.name}(...):"
                            m_code = "\n".join(lines[m_start - 1 : m_end])
                            is_ctor = item.name == "__init__"

                            method_symbol = CodeSymbol(
                                name=item.name,
                                symbol_type=CodeSymbolType.CONSTRUCTOR.value if is_ctor else CodeSymbolType.METHOD.value,
                                start_line=m_start,
                                end_line=m_end,
                                signature=m_sig,
                                docstring=m_doc,
                                code=m_code,
                                parent_name=node.name,
                                children=[],
                                metadata={
                                    "is_async": isinstance(item, ast.AsyncFunctionDef),
                                    "is_constructor": is_ctor,
                                },
                            )
                            class_symbol.children.append(method_symbol)

                        elif isinstance(item, ast.ClassDef):
                            # Nested class
                            nc_start = item.decorator_list[0].lineno if item.decorator_list else item.lineno
                            nc_end = getattr(item, "end_lineno", item.lineno)
                            nc_symbol = CodeSymbol(
                                name=item.name,
                                symbol_type=CodeSymbolType.CLASS.value,
                                start_line=nc_start,
                                end_line=nc_end,
                                signature=lines[item.lineno - 1].strip() if item.lineno <= len(lines) else f"class {item.name}:",
                                docstring=ast.get_docstring(item),
                                code="\n".join(lines[nc_start - 1 : nc_end]),
                                parent_name=node.name,
                                children=[],
                            )
                            class_symbol.children.append(nc_symbol)

                    symbols.append(class_symbol)

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f_start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                    f_end = getattr(node, "end_lineno", node.lineno)
                    f_doc = ast.get_docstring(node)
                    f_sig = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else f"def {node.name}(...):"
                    f_code = "\n".join(lines[f_start - 1 : f_end])

                    func_symbol = CodeSymbol(
                        name=node.name,
                        symbol_type=CodeSymbolType.FUNCTION.value,
                        start_line=f_start,
                        end_line=f_end,
                        signature=f_sig,
                        docstring=f_doc,
                        code=f_code,
                        parent_name=None,
                        children=[],
                        metadata={"is_async": isinstance(node, ast.AsyncFunctionDef)},
                    )

                    # Look for inner functions
                    for inner in node.body:
                        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            in_start = inner.decorator_list[0].lineno if inner.decorator_list else inner.lineno
                            in_end = getattr(inner, "end_lineno", inner.lineno)
                            inner_sym = CodeSymbol(
                                name=inner.name,
                                symbol_type=CodeSymbolType.FUNCTION.value,
                                start_line=in_start,
                                end_line=in_end,
                                signature=lines[inner.lineno - 1].strip() if inner.lineno <= len(lines) else f"def {inner.name}(...):",
                                docstring=ast.get_docstring(inner),
                                code="\n".join(lines[in_start - 1 : in_end]),
                                parent_name=node.name,
                                children=[],
                            )
                            func_symbol.children.append(inner_sym)

                    symbols.append(func_symbol)

        except SyntaxError:
            # Fallback regex extraction if code contains Python syntax errors
            module_docstring = extract_module_docstring_fallback(code)
            symbols = GenericRegexCodeParser.extract_symbols(code, language="python")

        return ParsedCode(
            file_path=file_path,
            language="python",
            module_docstring=module_docstring,
            imports=imports,
            symbols=symbols,
            raw_code=code,
            total_lines=total_lines,
        )


class GenericRegexCodeParser:
    """
    Structural brace-matching and signature parser for C-family & brace languages:
    JS, TS, Java, Go, Rust, C, C++.
    """

    @classmethod
    def extract_imports(cls, code: str, language: str) -> List[str]:
        imports: List[str] = []
        if language in ("javascript", "typescript"):
            # ES6 imports & requires
            for m in re.finditer(r"import\s+[^;]+from\s+['\"][^'\"]+['\"];?", code):
                imports.append(m.group(0).strip())
            for m in re.finditer(r"(?:const|let|var)\s+.*?=\s*require\(['\"][^'\"]+['\"]\);?", code):
                imports.append(m.group(0).strip())
        elif language == "java":
            for m in re.finditer(r"import\s+(?:static\s+)?([a-zA-Z0-9_.*]+);", code):
                imports.append(m.group(0).strip())
        elif language == "go":
            # Single imports
            for m in re.finditer(r'import\s+"([^"]+)"', code):
                imports.append(f'import "{m.group(1)}"')
            # Grouped imports: import ( ... )
            for m in re.finditer(r'import\s*\(\s*([^)]+)\)', code):
                block = m.group(1)
                for line in block.splitlines():
                    clean_line = line.strip()
                    if clean_line and not clean_line.startswith("//"):
                        imports.append(f"import {clean_line}")
        elif language == "rust":
            for m in re.finditer(r"use\s+([^;]+);", code):
                imports.append(m.group(0).strip())
        elif language in ("c", "cpp"):
            for m in re.finditer(r'#include\s*([<"][^>"]+[>"])', code):
                imports.append(m.group(0).strip())
        return imports

    @classmethod
    def extract_symbols(cls, code: str, language: str) -> List[CodeSymbol]:
        lines = code.splitlines()
        symbols: List[CodeSymbol] = []
        symbols_by_name: Dict[str, CodeSymbol] = {}

        # 1. Container patterns (classes, structs, interfaces, traits, impls)
        container_regexes = []
        if language in ("javascript", "typescript"):
            container_regexes.append((
                re.compile(r"(?:export\s+(?:default\s+)?)?class\s+([A-Za-z0-9_$]+)[^{]*\{"),
                CodeSymbolType.CLASS.value
            ))
            container_regexes.append((
                re.compile(r"(?:export\s+)?interface\s+([A-Za-z0-9_$]+)[^{]*\{"),
                CodeSymbolType.INTERFACE.value
            ))
        elif language == "java":
            container_regexes.append((
                re.compile(r"(?:(?:public|protected|private|static|final|abstract)\s+)*class\s+([A-Za-z0-9_$]+)[^{]*\{"),
                CodeSymbolType.CLASS.value
            ))
            container_regexes.append((
                re.compile(r"(?:(?:public|protected|private)\s+)*interface\s+([A-Za-z0-9_$]+)[^{]*\{"),
                CodeSymbolType.INTERFACE.value
            ))
            container_regexes.append((
                re.compile(r"(?:(?:public|protected|private)\s+)*enum\s+([A-Za-z0-9_$]+)[^{]*\{"),
                CodeSymbolType.ENUM.value
            ))
        elif language == "go":
            container_regexes.append((
                re.compile(r"type\s+([A-Za-z0-9_]+)\s+struct\s*\{"),
                CodeSymbolType.STRUCT.value
            ))
            container_regexes.append((
                re.compile(r"type\s+([A-Za-z0-9_]+)\s+interface\s*\{"),
                CodeSymbolType.INTERFACE.value
            ))
        elif language == "rust":
            container_regexes.append((
                re.compile(r"(?:pub(?:\([^)]+\))?\s+)?struct\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.STRUCT.value
            ))
            container_regexes.append((
                re.compile(r"(?:pub(?:\([^)]+\))?\s+)?enum\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.ENUM.value
            ))
            container_regexes.append((
                re.compile(r"(?:pub(?:\([^)]+\))?\s+)?trait\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.TRAIT.value
            ))
            container_regexes.append((
                re.compile(r"impl(?:<[^>]+>)?(?:\s+[A-Za-z0-9_]+\s+for)?\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.IMPL.value
            ))
        elif language in ("c", "cpp"):
            container_regexes.append((
                re.compile(r"(?:class)\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.CLASS.value
            ))
            container_regexes.append((
                re.compile(r"(?:struct)\s+([A-Za-z0-9_]+)[^{]*\{"),
                CodeSymbolType.STRUCT.value
            ))
            container_regexes.append((
                re.compile(r"(?:namespace)\s+([A-Za-z0-9_]+)\s*\{"),
                CodeSymbolType.NAMESPACE.value
            ))

        # Track character ranges occupied by containers so we don't duplicate top-level symbols
        container_ranges: List[Tuple[int, int]] = []

        # Find and extract containers
        for pattern, sym_type in container_regexes:
            for match in pattern.finditer(code):
                name = match.group(1)
                match_start = match.start()
                brace_pos = match.end() - 1
                brace_end = find_matching_brace(code, brace_pos)
                if brace_end == -1:
                    continue

                decl_line_idx = code.count("\n", 0, match_start)
                end_line_idx = code.count("\n", 0, brace_end)
                docstring, doc_start_line_idx = extract_preceding_comment(lines, decl_line_idx)

                container_ranges.append((match_start, brace_end))

                start_line = doc_start_line_idx + 1
                end_line = end_line_idx + 1
                sig_line = lines[decl_line_idx].strip() if decl_line_idx < len(lines) else match.group(0).strip()
                container_code = "\n".join(lines[start_line - 1 : end_line])

                container_sym = CodeSymbol(
                    name=name,
                    symbol_type=sym_type,
                    start_line=start_line,
                    end_line=end_line,
                    signature=sig_line,
                    docstring=docstring,
                    code=container_code,
                    parent_name=None,
                    children=[],
                )

                # Extract methods inside container
                body_text = code[brace_pos + 1 : brace_end]
                body_start_offset = brace_pos + 1

                cls._extract_methods_in_container(
                    container_sym=container_sym,
                    body_text=body_text,
                    body_start_offset=body_start_offset,
                    full_code=code,
                    lines=lines,
                    language=language,
                )

                symbols.append(container_sym)
                symbols_by_name[name] = container_sym

        # 2. Language-specific out-of-line methods / receivers
        if language == "go":
            cls._extract_go_receiver_methods(code, lines, symbols, symbols_by_name)
        elif language in ("c", "cpp"):
            cls._extract_cpp_out_of_line_methods(code, lines, symbols, symbols_by_name, container_ranges)

        # 3. Top-level free functions
        cls._extract_top_level_functions(code, lines, symbols, container_ranges, language)

        return symbols

    @classmethod
    def _extract_methods_in_container(
        cls,
        container_sym: CodeSymbol,
        body_text: str,
        body_start_offset: int,
        full_code: str,
        lines: List[str],
        language: str,
    ):
        method_patterns = []

        if language in ("javascript", "typescript"):
            # Methods and constructor
            method_patterns.append(re.compile(
                r"(?:(?:public|private|protected|static|async|get|set)\s+)*([A-Za-z0-9_$]+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{"
            ))
            # Arrow property methods: foo = async () => {
            method_patterns.append(re.compile(
                r"([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[^=>]+)?=>\s*\{"
            ))

        elif language == "java":
            # Java methods and constructors
            method_patterns.append(re.compile(
                r"(?:(?:public|protected|private|static|final|abstract|synchronized|native)\s+)*(?:<[^>]+>\s+)?(?:([A-Za-z0-9_$<>[\]]+)\s+)?([A-Za-z0-9_$]+)\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\{"
            ))

        elif language == "rust":
            method_patterns.append(re.compile(
                r"(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*\([^)]*\)(?:\s*->\s*[^{]+)?\s*\{"
            ))

        elif language in ("c", "cpp"):
            method_patterns.append(re.compile(
                r"(?:(?:virtual|static|inline|explicit)\s+)*([A-Za-z0-9_&*:<>[\]]+)\s+([A-Za-z0-9_~]+)\s*\([^)]*\)(?:\s*const)?(?:\s*override)?\s*\{"
            ))

        for pattern in method_patterns:
            for match in pattern.finditer(body_text):
                # Distinguish groups
                if language == "java" and match.lastindex and match.lastindex >= 2:
                    name = match.group(2)
                elif language in ("c", "cpp") and match.lastindex and match.lastindex >= 2:
                    name = match.group(2)
                else:
                    name = match.group(1)

                if name in ("if", "for", "while", "switch", "catch", "else", "do", "try", "finally"):
                    continue

                rel_brace_pos = match.end() - 1
                abs_brace_pos = body_start_offset + rel_brace_pos
                abs_brace_end = find_matching_brace(full_code, abs_brace_pos)
                if abs_brace_end == -1:
                    continue

                abs_match_start = body_start_offset + match.start()
                decl_line_idx = full_code.count("\n", 0, abs_match_start)
                end_line_idx = full_code.count("\n", 0, abs_brace_end)

                docstring, doc_start_line_idx = extract_preceding_comment(lines, decl_line_idx)
                start_line = doc_start_line_idx + 1
                end_line = end_line_idx + 1

                is_ctor = name == "constructor" or name == container_sym.name
                sig_line = lines[decl_line_idx].strip() if decl_line_idx < len(lines) else match.group(0).strip()
                method_code = "\n".join(lines[start_line - 1 : end_line])

                method_sym = CodeSymbol(
                    name=name,
                    symbol_type=CodeSymbolType.CONSTRUCTOR.value if is_ctor else CodeSymbolType.METHOD.value,
                    start_line=start_line,
                    end_line=end_line,
                    signature=sig_line,
                    docstring=docstring,
                    code=method_code,
                    parent_name=container_sym.name,
                    children=[],
                    metadata={"is_constructor": is_ctor},
                )
                container_sym.children.append(method_sym)

    @classmethod
    def _extract_go_receiver_methods(
        cls,
        code: str,
        lines: List[str],
        symbols: List[CodeSymbol],
        symbols_by_name: Dict[str, CodeSymbol],
    ):
        pattern = re.compile(
            r"func\s+\(\s*(?:[A-Za-z0-9_]+\s+)?\*?([A-Za-z0-9_]+)\s*\)\s+([A-Za-z0-9_]+)\s*\([^)]*\)(?:\s*(?:\([^)]*\)|[A-Za-z0-9_*.]*))?\s*\{"
        )
        for match in pattern.finditer(code):
            receiver_name = match.group(1)
            method_name = match.group(2)
            brace_pos = match.end() - 1
            brace_end = find_matching_brace(code, brace_pos)
            if brace_end == -1:
                continue

            decl_line_idx = code.count("\n", 0, match.start())
            end_line_idx = code.count("\n", 0, brace_end)
            docstring, doc_start_line_idx = extract_preceding_comment(lines, decl_line_idx)

            start_line = doc_start_line_idx + 1
            end_line = end_line_idx + 1
            sig_line = lines[decl_line_idx].strip() if decl_line_idx < len(lines) else match.group(0).strip()
            method_code = "\n".join(lines[start_line - 1 : end_line])

            method_sym = CodeSymbol(
                name=method_name,
                symbol_type=CodeSymbolType.METHOD.value,
                start_line=start_line,
                end_line=end_line,
                signature=sig_line,
                docstring=docstring,
                code=method_code,
                parent_name=receiver_name,
                children=[],
            )

            # If receiver struct exists in symbols, link as child
            if receiver_name in symbols_by_name:
                symbols_by_name[receiver_name].children.append(method_sym)
            else:
                symbols.append(method_sym)

    @classmethod
    def _extract_cpp_out_of_line_methods(
        cls,
        code: str,
        lines: List[str],
        symbols: List[CodeSymbol],
        symbols_by_name: Dict[str, CodeSymbol],
        container_ranges: List[Tuple[int, int]],
    ):
        pattern = re.compile(
            r"([A-Za-z0-9_&*:<>[\]]+)\s+([A-Za-z0-9_]+)::([A-Za-z0-9_~]+)\s*\([^)]*\)(?:\s*const)?\s*\{"
        )
        for match in pattern.finditer(code):
            m_start = match.start()
            if any(start <= m_start <= end for start, end in container_ranges):
                continue

            parent_class = match.group(2)
            method_name = match.group(3)
            brace_pos = match.end() - 1
            brace_end = find_matching_brace(code, brace_pos)
            if brace_end == -1:
                continue

            decl_line_idx = code.count("\n", 0, m_start)
            end_line_idx = code.count("\n", 0, brace_end)
            docstring, doc_start_line_idx = extract_preceding_comment(lines, decl_line_idx)

            start_line = doc_start_line_idx + 1
            end_line = end_line_idx + 1
            sig_line = lines[decl_line_idx].strip() if decl_line_idx < len(lines) else match.group(0).strip()
            method_code = "\n".join(lines[start_line - 1 : end_line])

            is_ctor = method_name == parent_class or method_name == f"~{parent_class}"
            method_sym = CodeSymbol(
                name=method_name,
                symbol_type=CodeSymbolType.CONSTRUCTOR.value if is_ctor else CodeSymbolType.METHOD.value,
                start_line=start_line,
                end_line=end_line,
                signature=sig_line,
                docstring=docstring,
                code=method_code,
                parent_name=parent_class,
                children=[],
            )

            if parent_class in symbols_by_name:
                symbols_by_name[parent_class].children.append(method_sym)
            else:
                symbols.append(method_sym)

    @classmethod
    def _extract_top_level_functions(
        cls,
        code: str,
        lines: List[str],
        symbols: List[CodeSymbol],
        container_ranges: List[Tuple[int, int]],
        language: str,
    ):
        func_patterns = []
        if language in ("javascript", "typescript"):
            func_patterns.append(re.compile(
                r"(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{]+)?\{"
            ))
            func_patterns.append(re.compile(
                r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*(?::\s*[^=>]+)?=>\s*\{"
            ))
        elif language == "go":
            func_patterns.append(re.compile(
                r"func\s+([A-Za-z0-9_]+)\s*\([^)]*\)(?:\s*(?:\([^)]*\)|[A-Za-z0-9_*.]*))?\s*\{"
            ))
        elif language == "rust":
            func_patterns.append(re.compile(
                r"(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*\([^)]*\)(?:\s*->\s*[^{]+)?\s*\{"
            ))
        elif language in ("c", "cpp"):
            func_patterns.append(re.compile(
                r"(?:(?:static|inline)\s+)*([A-Za-z0-9_&*:<>[\]]+)\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*\{"
            ))

        for pattern in func_patterns:
            for match in pattern.finditer(code):
                m_start = match.start()
                # Skip if inside a class/struct/container
                if any(start <= m_start <= end for start, end in container_ranges):
                    continue

                if language in ("c", "cpp") and match.lastindex and match.lastindex >= 2:
                    name = match.group(2)
                else:
                    name = match.group(1)

                if name in ("if", "for", "while", "switch", "catch", "else", "do", "try", "finally", "struct", "class"):
                    continue

                brace_pos = match.end() - 1
                brace_end = find_matching_brace(code, brace_pos)
                if brace_end == -1:
                    continue

                decl_line_idx = code.count("\n", 0, m_start)
                end_line_idx = code.count("\n", 0, brace_end)
                docstring, doc_start_line_idx = extract_preceding_comment(lines, decl_line_idx)

                start_line = doc_start_line_idx + 1
                end_line = end_line_idx + 1
                sig_line = lines[decl_line_idx].strip() if decl_line_idx < len(lines) else match.group(0).strip()
                func_code = "\n".join(lines[start_line - 1 : end_line])

                func_sym = CodeSymbol(
                    name=name,
                    symbol_type=CodeSymbolType.FUNCTION.value,
                    start_line=start_line,
                    end_line=end_line,
                    signature=sig_line,
                    docstring=docstring,
                    code=func_code,
                    parent_name=None,
                    children=[],
                )
                symbols.append(func_sym)


class CodeParser:
    """
    Main language-aware code parser API for repository & multi-source code ingestion.
    """

    @staticmethod
    def detect_language(file_path: Union[str, Path]) -> str:
        suffix = Path(file_path).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(suffix, "text")

    @staticmethod
    def is_code_file(file_path: Union[str, Path]) -> bool:
        suffix = Path(file_path).suffix.lower()
        return suffix in EXTENSION_TO_LANGUAGE

    @classmethod
    def parse_code(
        cls,
        code: str,
        language: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> ParsedCode:
        lang = (language or "python").lower()

        if lang == "python":
            return PythonCodeParser.parse(code, file_path=file_path)

        lines = code.splitlines()
        module_docstring = extract_module_docstring_fallback(code)
        imports = GenericRegexCodeParser.extract_imports(code, lang)
        symbols = GenericRegexCodeParser.extract_symbols(code, lang)

        return ParsedCode(
            file_path=file_path,
            language=lang,
            module_docstring=module_docstring,
            imports=imports,
            symbols=symbols,
            raw_code=code,
            total_lines=len(lines),
        )

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> ParsedCode:
        path = Path(file_path)
        lang = cls.detect_language(path)
        code = path.read_text(encoding="utf-8", errors="replace")
        return cls.parse_code(code, language=lang, file_path=str(path))
