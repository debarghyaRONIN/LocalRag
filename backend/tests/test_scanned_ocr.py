import io
import pytest
from pathlib import Path
from PIL import Image, ImageDraw
import fitz

from backend.app.services.ingestion.parsers import DocumentParser
from backend.app.services.ingestion.universal_parser import UniversalParser


@pytest.mark.asyncio
async def test_image_ocr(tmp_path: Path):
    # Create an image with legible text
    img = Image.new("RGB", (320, 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "RAPID OCR SOVEREIGN TEST", fill=(0, 0, 0))

    img_path = tmp_path / "scanned_memo.png"
    img.save(img_path)

    pages = UniversalParser.parse_image_ocr(img_path)
    assert len(pages) == 1
    assert "RAPID" in pages[0].text or "OCR" in pages[0].text or "SOVEREIGN" in pages[0].text
    assert pages[0].metadata.get("ocr_applied") is True


@pytest.mark.asyncio
async def test_scanned_pdf_ocr_fallback(tmp_path: Path):
    # 1. Create a PDF page with only an embedded image (no selectable text)
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((15, 25), "ENCRYPTED VAULT KEY 9981", fill=(0, 0, 0))

    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_bytes = img_buffer.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=400, height=100)
    rect = fitz.Rect(0, 0, 400, 100)
    page.insert_image(rect, stream=img_bytes)

    pdf_path = tmp_path / "scanned_doc.pdf"
    doc.save(pdf_path)
    doc.close()

    # Parse with DocumentParser.parse_pdf
    pages = DocumentParser.parse_pdf(pdf_path)
    assert len(pages) == 1
    # Check that OCR extracted the text from the scanned image
    assert "VAULT" in pages[0].text or "KEY" in pages[0].text or "9981" in pages[0].text or "ENCRYPTED" in pages[0].text
    assert pages[0].metadata.get("ocr_applied") is True


@pytest.mark.asyncio
async def test_native_pdf_no_ocr(tmp_path: Path):
    # Native text PDF does not require OCR
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((50, 50), "Standard native digital text with complete font glyphs.")

    pdf_path = tmp_path / "native_doc.pdf"
    doc.save(pdf_path)
    doc.close()

    pages = DocumentParser.parse_pdf(pdf_path)
    assert len(pages) == 1
    assert "Standard native digital text" in pages[0].text
    assert pages[0].metadata.get("ocr_applied") is False

