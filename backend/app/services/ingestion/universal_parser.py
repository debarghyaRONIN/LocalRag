import io
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
import zipfile

from backend.app.services.ingestion.code_parser import CodeParser

logger = logging.getLogger(__name__)

_ocr_engine = None


def get_ocr_engine():
    """Lazy-loaded singleton for RapidOCR ONNX runtime engine."""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception as e:
            logger.warning(f"Failed to initialize RapidOCR: {e}")
            _ocr_engine = None
    return _ocr_engine


class UniversalParser:
    """
    Universal Multi-Format Ingestion Engine.
    Parses Office formats (Excel, PowerPoint), Notebooks (.ipynb), Images (OCR),
    Structured Configs (YAML, TOML, XML, JSON, INI, ENV, LOG), and Archives (.zip).
    """

    @staticmethod
    def parse_excel(file_path: Path) -> List[Any]:
        """
        Extract tabular worksheets from Excel (.xlsx, .xls) into structured Markdown tables.
        Each sheet is represented as a separate page with sheet name citations.
        """
        import openpyxl
        pages = []
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
            for idx, sheet_name in enumerate(wb.sheetnames, start=1):
                sheet = wb[sheet_name]
                rows_data = []
                for row in sheet.iter_rows(values_only=True):
                    # Filter out trailing empty rows
                    cells = [str(c).strip() if c is not None else "" for c in row]
                    if any(cells):
                        rows_data.append(cells)

                if not rows_data:
                    continue

                # Build Markdown table
                headers = rows_data[0]
                md_lines = [f"## Worksheet: {sheet_name}\n"]
                md_lines.append("| " + " | ".join(headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

                for data_row in rows_data[1:]:
                    # Pad or trim data row to header length
                    padded = (data_row + [""] * len(headers))[:len(headers)]
                    # Escape pipes
                    escaped = [c.replace("|", "\\|").replace("\n", " ") for c in padded]
                    md_lines.append("| " + " | ".join(escaped) + " |")

                sheet_text = "\n".join(md_lines)
                from backend.app.services.ingestion.parsers import ParsedPage
                pages.append(
                    ParsedPage(
                        page_number=idx,
                        text=sheet_text,
                        metadata={
                            "sheet_name": sheet_name,
                            "sheet_index": idx,
                            "total_sheets": len(wb.sheetnames),
                            "format": "excel",
                        }
                    )
                )
            wb.close()
        except Exception as e:
            logger.error(f"Excel parsing failed for {file_path}: {e}")
            from backend.app.services.ingestion.parsers import ParsedPage
            pages.append(ParsedPage(page_number=1, text=f"[Excel Read Error: {e}]"))
        
        return pages if pages else [ParsedPage(page_number=1, text="[Empty Excel Workbook]")]

    @staticmethod
    def parse_powerpoint(file_path: Path) -> List[Any]:
        """
        Extract slides, titles, shapes, body paragraphs, and speaker notes from PowerPoint (.pptx).
        Each slide is represented as an individual page for exact slide grounding.
        """
        import pptx
        from backend.app.services.ingestion.parsers import ParsedPage

        pages = []
        try:
            prs = pptx.Presentation(file_path)
            for slide_idx, slide in enumerate(prs.slides, start=1):
                slide_lines = [f"## Slide {slide_idx}"]
                slide_title = ""

                # Extract shapes text
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for paragraph in shape.text_frame.paragraphs:
                            p_text = paragraph.text.strip()
                            if p_text:
                                if not slide_title and shape == getattr(slide.shapes, "title", None):
                                    slide_title = p_text
                                    slide_lines.append(f"### {p_text}")
                                else:
                                    slide_lines.append(f"- {p_text}")

                    if shape.has_table:
                        table = shape.table
                        t_rows = []
                        for row in table.rows:
                            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                            if any(cells):
                                t_rows.append(cells)
                        if t_rows:
                            slide_lines.append("\n| " + " | ".join(t_rows[0]) + " |")
                            slide_lines.append("| " + " | ".join(["---"] * len(t_rows[0])) + " |")
                            for r in t_rows[1:]:
                                padded = (r + [""] * len(t_rows[0]))[:len(t_rows[0])]
                                slide_lines.append("| " + " | ".join(padded) + " |")
                            slide_lines.append("")

                # Extract speaker notes if present
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        slide_lines.append(f"\n> **Speaker Notes:** {notes}")

                combined_slide_text = "\n".join(slide_lines).strip()
                if combined_slide_text:
                    pages.append(
                        ParsedPage(
                            page_number=slide_idx,
                            text=combined_slide_text,
                            metadata={
                                "slide_number": slide_idx,
                                "slide_title": slide_title,
                                "total_slides": len(prs.slides),
                                "format": "powerpoint",
                            }
                        )
                    )
        except Exception as e:
            logger.error(f"PowerPoint parsing failed for {file_path}: {e}")
            pages.append(ParsedPage(page_number=1, text=f"[PowerPoint Read Error: {e}]"))

        return pages if pages else [ParsedPage(page_number=1, text="[Empty PowerPoint Presentation]")]

    @staticmethod
    def parse_jupyter(file_path: Path) -> List[Any]:
        """
        Extract Jupyter Notebook (.ipynb) cells, separating Markdown documentation,
        code cells with execution numbers, and text/stream execution outputs.
        """
        from backend.app.services.ingestion.parsers import ParsedPage
        pages = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            nb = json.loads(content)
            cells = nb.get("cells", [])

            lines = [f"# Jupyter Notebook: {file_path.name}\n"]
            for idx, cell in enumerate(cells, start=1):
                cell_type = cell.get("cell_type", "code")
                source_raw = "".join(cell.get("source", [])).strip()
                if not source_raw:
                    continue

                if cell_type == "markdown":
                    lines.append(f"\n{source_raw}\n")
                elif cell_type == "code":
                    exec_count = cell.get("execution_count") or idx
                    lines.append(f"\n```python\n# In [{exec_count}]:\n{source_raw}\n```")

                    # Extract stream/text outputs
                    outputs = cell.get("outputs", [])
                    out_texts = []
                    for out in outputs:
                        if out.get("output_type") in ("stream", "execute_result", "display_data"):
                            if "text" in out:
                                t = "".join(out["text"]).strip()
                                if t:
                                    out_texts.append(t)
                            elif "data" in out and "text/plain" in out["data"]:
                                t = "".join(out["data"]["text/plain"]).strip()
                                if t:
                                    out_texts.append(t)
                    if out_texts:
                        combined_out = "\n".join(out_texts)
                        # Truncate very long outputs to 1500 chars to avoid prompt pollution
                        if len(combined_out) > 1500:
                            combined_out = combined_out[:1500] + "... [Output Truncated]"
                        lines.append(f"\n```output\n# Out [{exec_count}]:\n{combined_out}\n```")

            text = "\n".join(lines).strip()
            pages.append(
                ParsedPage(
                    page_number=1,
                    text=text,
                    metadata={"total_cells": len(cells), "format": "jupyter_notebook"}
                )
            )
        except Exception as e:
            logger.error(f"Jupyter parsing failed for {file_path}: {e}")
            pages.append(ParsedPage(page_number=1, text=f"[Jupyter Notebook Error: {e}]"))

        return pages

    @staticmethod
    def parse_image_ocr(file_path: Path) -> List[Any]:
        """
        Extract text from scanned images (.png, .jpg, .jpeg, .tiff, .bmp, .webp) using RapidOCR.
        """
        from backend.app.services.ingestion.parsers import ParsedPage
        ocr = get_ocr_engine()
        if not ocr:
            return [ParsedPage(page_number=1, text="[RapidOCR Not Available]")]

        try:
            results, elapse = ocr(str(file_path))
            if not results:
                return [ParsedPage(page_number=1, text="[No readable text detected in image]")]

            extracted_lines = []
            for item in results:
                # item is [bbox, text, score]
                if len(item) >= 2:
                    text_str = item[1].strip()
                    if text_str:
                        extracted_lines.append(text_str)

            text = "\n".join(extracted_lines)
            return [
                ParsedPage(
                    page_number=1,
                    text=text,
                    metadata={
                        "is_image": True,
                        "ocr_applied": True,
                        "ocr_engine": "RapidOCR",
                        "detected_lines": len(extracted_lines),
                        "format": "image_ocr",
                    }
                )
            ]
        except Exception as e:
            logger.error(f"Image OCR failed for {file_path}: {e}")
            return [ParsedPage(page_number=1, text=f"[Image OCR Error: {e}]")]

    @staticmethod
    def parse_structured_data(file_path: Path) -> List[Any]:
        """
        Parse structured formats: YAML (.yaml, .yml), TOML (.toml), XML (.xml),
        JSON/JSONL (.json, .jsonl), and INI/ENV/LOG files.
        """
        from backend.app.services.ingestion.parsers import ParsedPage
        suffix = file_path.suffix.lower()
        raw_content = file_path.read_text(encoding="utf-8", errors="replace").strip()

        try:
            if suffix in (".yaml", ".yml"):
                import yaml
                data = yaml.safe_load(raw_content)
                formatted = yaml.dump(data, default_flow_style=False, sort_keys=False)
                return [ParsedPage(page_number=1, text=f"```yaml\n{formatted}\n```", metadata={"format": "yaml"})]

            elif suffix == ".toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib
                data = tomllib.loads(raw_content)
                formatted = json.dumps(data, indent=2)
                return [ParsedPage(page_number=1, text=f"```toml-json\n{formatted}\n```", metadata={"format": "toml"})]

            elif suffix == ".xml":
                root = ET.fromstring(raw_content)
                lines = [f"## XML Root: <{root.tag}>"]

                def walk_element(elem, depth=0):
                    indent = "  " * depth
                    attribs = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
                    tag_str = f"<{elem.tag}{' ' + attribs if attribs else ''}>"
                    text = elem.text.strip() if elem.text else ""
                    if text:
                        lines.append(f"{indent}- **{tag_str}**: {text}")
                    elif attribs:
                        lines.append(f"{indent}- **{tag_str}**")
                    for child in elem:
                        walk_element(child, depth + 1)

                walk_element(root)
                return [ParsedPage(page_number=1, text="\n".join(lines), metadata={"format": "xml"})]

            elif suffix in (".json", ".jsonl"):
                if suffix == ".jsonl":
                    records = []
                    for line in raw_content.splitlines():
                        if line.strip():
                            records.append(json.loads(line.strip()))
                    formatted = json.dumps(records, indent=2)
                    return [ParsedPage(page_number=1, text=f"```jsonl\n{formatted}\n```", metadata={"format": "jsonl", "record_count": len(records)})]
                else:
                    data = json.loads(raw_content)
                    formatted = json.dumps(data, indent=2)
                    return [ParsedPage(page_number=1, text=f"```json\n{formatted}\n```", metadata={"format": "json"})]

            elif suffix in (".ini", ".env", ".log", ".properties", ".conf"):
                return [ParsedPage(page_number=1, text=raw_content, metadata={"format": suffix.lstrip(".")})]

        except Exception as e:
            logger.warning(f"Structured parser failed for {file_path} ({e}), falling back to raw text")

        return [ParsedPage(page_number=1, text=raw_content)]

    @staticmethod
    def parse_archive(file_path: Path) -> List[Any]:
        """
        Extract and recursively parse supported documents within a ZIP archive.
        Each archive entry is converted into a ParsedPage attributed with source file path.
        """
        from backend.app.services.ingestion.parsers import DocumentParser, ParsedPage
        pages = []
        max_files = 100
        max_bytes_per_file = 20 * 1024 * 1024  # 20MB safety limit

        try:
            with zipfile.ZipFile(file_path, "r") as z:
                count = 0
                for info in z.infolist():
                    if info.is_dir() or count >= max_files:
                        continue
                    fname = info.filename
                    # Ignore internal system/git directories
                    if fname.startswith("__MACOSX") or "/.git/" in fname or fname.endswith(".DS_Store"):
                        continue
                    if info.file_size > max_bytes_per_file:
                        continue

                    sub_path = Path(fname)
                    sub_suffix = sub_path.suffix.lower()

                    # Supported readable extensions inside archive
                    supported_exts = {
                        ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
                        ".java", ".c", ".cpp", ".go", ".rs", ".json", ".yaml",
                        ".yml", ".xml", ".toml", ".csv", ".ini", ".env", ".log"
                    }
                    if sub_suffix in supported_exts:
                        try:
                            raw_bytes = z.read(info)
                            text = raw_bytes.decode("utf-8", errors="replace").strip()
                            if text:
                                count += 1
                                pages.append(
                                    ParsedPage(
                                        page_number=count,
                                        text=f"### Archive File: [{file_path.name} -> {fname}]\n\n{text}",
                                        metadata={
                                            "archive_name": file_path.name,
                                            "entry_path": fname,
                                            "entry_size": info.file_size,
                                            "format": "archive_entry",
                                        }
                                    )
                                )
                        except Exception as read_err:
                            logger.warning(f"Failed to read archive entry {fname}: {read_err}")

        except Exception as e:
            logger.error(f"Archive parsing failed for {file_path}: {e}")
            pages.append(ParsedPage(page_number=1, text=f"[Archive Read Error: {e}]"))

        return pages if pages else [ParsedPage(page_number=1, text=f"[Empty Archive: {file_path.name}]")]
