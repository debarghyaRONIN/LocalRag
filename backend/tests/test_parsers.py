from pathlib import Path
from backend.app.services.ingestion.parsers import DocumentParser


def test_parse_text(tmp_path: Path):
    txt_file = tmp_path / "notes.md"
    txt_file.write_text("# Section 1\n\nLocal RAG pipeline instructions.", encoding="utf-8")

    pages = DocumentParser.parse(txt_file)
    assert len(pages) == 1
    assert "Local RAG pipeline instructions." in pages[0].text
    assert pages[0].page_number == 1


def test_parse_csv(tmp_path: Path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("model,vram,latency\nqwen2.5,6GB,20ms\nbge-m3,1GB,12ms\n", encoding="utf-8")

    pages = DocumentParser.parse(csv_file)
    assert len(pages) == 1
    assert "model: qwen2.5" in pages[0].text
    assert "vram: 6GB" in pages[0].text

