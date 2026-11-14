import csv
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import fitz  # PyMuPDF
import docx

from backend.app.services.ingestion.code_parser import CodeParser
from backend.app.services.ingestion.web_parser import WebParser
from backend.app.services.ingestion.universal_parser import UniversalParser, get_ocr_engine


class ParsedPage:
    def __init__(self, page_number: int, text: str, metadata: Dict[str, Any] = None):
        self.page_number = page_number
        self.text = text
        self.metadata = metadata or {}


class DocumentParser:
    @staticmethod
    def parse_pdf(file_path: Path) -> List[ParsedPage]:
        """
        Extract text page-by-page from a PDF using PyMuPDF.
        Preserves layout structure and page numbers for exact citation grounding.
        If a page is scanned or has sparse text (< 20 chars), falls back to RapidOCR.
        """
        doc = fitz.open(file_path)
        pages: List[ParsedPage] = []
        ocr = None

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            ocr_applied = False

            # Scanned PDF RapidOCR fallback
            if len(text) < 20:
                try:
                    if ocr is None:
                        ocr = get_ocr_engine()
                    if ocr is not None:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        ocr_res, _ = ocr(img_bytes)
                        if ocr_res:
                            extracted_lines = [
                                item[1].strip() for item in ocr_res if len(item) >= 2 and item[1].strip()
                            ]
                            if extracted_lines:
                                text = "\n".join(extracted_lines)
                                ocr_applied = True
                except Exception:
                    pass

            if text:
                pages.append(
                    ParsedPage(
                        page_number=page_idx + 1,
                        text=text,
                        metadata={
                            "total_pages": len(doc),
                            "ocr_applied": ocr_applied,
                        }
                    )
                )

        doc.close()
        return pages

    @staticmethod
    def parse_docx(file_path: Path) -> List[ParsedPage]:
        """
        Extract text from a Word .docx document including paragraphs and tables.
        Falls back gracefully if the file is legacy binary doc or invalid XML.
        """
        try:
            doc = docx.Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                if para.text.strip():
                    full_text.append(para.text.strip())

            for table in doc.tables:
                for row in table.rows:
                    row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_data:
                        full_text.append(" | ".join(row_data))

            combined_text = "\n\n".join(full_text)
            return [ParsedPage(page_number=1, text=combined_text)]
        except Exception:
            return DocumentParser.parse_text(file_path)

    @staticmethod
    def parse_rtf(file_path: Path) -> List[ParsedPage]:
        """
        Extract clean text from Rich Text Format (.rtf) by stripping RTF control sequences.
        """
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        # Strip RTF control groups and backslash sequences
        text = re.sub(r"\{\*?\\[^{}]+;\}", "", raw)
        text = re.sub(r"\\[a-zA-Z0-9]+(-?\d+)?\s?", " ", text)
        text = text.replace("{", "").replace("}", "").strip()
        # Collapse excessive whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        return [ParsedPage(page_number=1, text=text, metadata={"format": "rtf"})]

    @staticmethod
    def parse_text(file_path: Path) -> List[ParsedPage]:
        """
        Extract text from Markdown, TXT, or plain text files.
        """
        content = file_path.read_text(encoding="utf-8", errors="replace").strip()
        return [ParsedPage(page_number=1, text=content)]

    @staticmethod
    def parse_csv(file_path: Path) -> List[ParsedPage]:
        """
        Convert tabular CSV into structured row representations.
        """
        rows = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for idx, row in enumerate(reader):
                        row_str = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
                        if row_str:
                            rows.append(f"Row {idx + 1}: {row_str}")
                else:
                    f.seek(0)
                    for line in f:
                        if line.strip():
                            rows.append(line.strip())
        except Exception:
            return DocumentParser.parse_text(file_path)

        text = "\n".join(rows)
        return [ParsedPage(page_number=1, text=text)]

    @staticmethod
    def parse_code(file_path: Path) -> List[ParsedPage]:
        """
        Extract code AST/structural symbols, signatures, and docstrings using CodeParser.
        Supports Python, JS/TS, Java, Go, Rust, C/C++.
        """
        parsed = CodeParser.parse_file(file_path)
        metadata = {
            "language": parsed.language,
            "is_code": True,
            "module_docstring": parsed.module_docstring,
            "imports": parsed.imports,
            "total_lines": parsed.total_lines,
            "total_symbols": len(parsed.symbols),
            "symbols": [s.to_dict() for s in parsed.symbols],
            "parsed_code": parsed.to_dict(),
        }
        return [ParsedPage(page_number=1, text=parsed.raw_code, metadata=metadata)]

    @staticmethod
    def parse_html(file_path: Path) -> List[ParsedPage]:
        """
        Extract clean markdown headings, title, meta description, and main content using WebParser
        while stripping navigation, scripts, ads, headers, and footers.
        """
        web_page = WebParser.parse_file(file_path)
        metadata = {
            "title": web_page.title,
            "description": web_page.description,
            "headings": [h.to_dict() for h in web_page.headings],
            "is_web": True,
            **web_page.metadata,
        }
        return [ParsedPage(page_number=1, text=web_page.formatted_text, metadata=metadata)]

    @classmethod
    def parse(cls, file_path: Path, mime_type: str = "") -> List[ParsedPage]:
        """
        Universal file format dispatcher. Routes documents, spreadsheets, presentations,
        notebooks, images (OCR), code repositories, structured data, and archives.
        """
        suffix = file_path.suffix.lower()

        # PDF documents (with OCR fallback)
        if suffix == ".pdf" or "pdf" in mime_type:
            return cls.parse_pdf(file_path)

        # Word documents
        elif suffix in [".docx", ".doc"]:
            return cls.parse_docx(file_path)

        # Excel spreadsheets
        elif suffix in [".xlsx", ".xls"] or "spreadsheet" in mime_type or "excel" in mime_type:
            return UniversalParser.parse_excel(file_path)

        # PowerPoint presentations
        elif suffix in [".pptx", ".ppt"] or "presentation" in mime_type or "powerpoint" in mime_type:
            return UniversalParser.parse_powerpoint(file_path)

        # Jupyter notebooks
        elif suffix == ".ipynb":
            return UniversalParser.parse_jupyter(file_path)

        # Standalone Images (via RapidOCR)
        elif suffix in [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"] or "image" in mime_type:
            return UniversalParser.parse_image_ocr(file_path)

        # ZIP Archives
        elif suffix in [".zip", ".gz"] or "zip" in mime_type:
            return UniversalParser.parse_archive(file_path)

        # RTF Rich text
        elif suffix == ".rtf":
            return cls.parse_rtf(file_path)

        # CSV Tabular
        elif suffix == ".csv":
            return cls.parse_csv(file_path)

        # HTML / Saved Web Pages
        elif suffix in [".html", ".htm", ".xhtml"] or "html" in mime_type:
            return cls.parse_html(file_path)

        # AST Code files
        elif CodeParser.is_code_file(file_path):
            return cls.parse_code(file_path)

        # Structured configurations and data
        elif suffix in [
            ".yaml", ".yml", ".toml", ".xml", ".json", ".jsonl",
            ".ini", ".env", ".log", ".conf", ".properties"
        ]:
            return UniversalParser.parse_structured_data(file_path)

        # Plain text / Markdown fallback
        else:
            return cls.parse_text(file_path)

