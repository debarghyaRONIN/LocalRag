import json
import zipfile
import pytest
from pathlib import Path

from backend.app.services.ingestion.parsers import DocumentParser
from backend.app.services.ingestion.universal_parser import UniversalParser


@pytest.mark.asyncio
async def test_excel_parser(tmp_path: Path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Airgap Hardware"
    ws1.append(["Component", "Model", "Clearance"])
    ws1.append(["Hardware Security Module", "YubiHSM2", "Level 4"])
    ws1.append(["Optical Data Diode", "Fibermux-10G", "Level 3"])

    ws2 = wb.create_sheet(title="Network Configuration")
    ws2.append(["Interface", "IP", "VLAN"])
    ws2.append(["eth0", "10.0.0.1", "VLAN-100"])

    excel_path = tmp_path / "system_spec.xlsx"
    wb.save(excel_path)
    wb.close()

    pages = DocumentParser.parse(excel_path)
    assert len(pages) == 2
    assert "Worksheet: Airgap Hardware" in pages[0].text
    assert "Hardware Security Module" in pages[0].text
    assert "Worksheet: Network Configuration" in pages[1].text
    assert pages[0].metadata["sheet_name"] == "Airgap Hardware"


@pytest.mark.asyncio
async def test_powerpoint_parser(tmp_path: Path):
    import pptx

    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Airgap Defense Briefing"
    slide.placeholders[1].text = "Zero-trust deployment architecture"

    # Add speaker notes
    notes_slide = slide.notes_slide
    notes_slide.notes_text_frame.text = "Strictly unclassified presentation copy."

    pptx_path = tmp_path / "briefing.pptx"
    prs.save(pptx_path)

    pages = DocumentParser.parse(pptx_path)
    assert len(pages) == 1
    assert "Airgap Defense Briefing" in pages[0].text
    assert "Speaker Notes:" in pages[0].text
    assert pages[0].metadata["slide_number"] == 1


@pytest.mark.asyncio
async def test_jupyter_parser(tmp_path: Path):
    notebook_data = {
        "cells": [
            {
                "cell_type": "markdown",
                "source": ["# Benchmark Analysis\n", "Evaluating local embedding latency."]
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "source": ["import time\n", "print('Embedding 10k chunks')"],
                "outputs": [
                    {
                        "output_type": "stream",
                        "text": ["Embedding 10k chunks\n", "Completed in 0.42s\n"]
                    }
                ]
            }
        ]
    }
    ipynb_path = tmp_path / "benchmark.ipynb"
    ipynb_path.write_text(json.dumps(notebook_data), encoding="utf-8")

    pages = DocumentParser.parse(ipynb_path)
    assert len(pages) == 1
    assert "Benchmark Analysis" in pages[0].text
    assert "# In [1]:" in pages[0].text
    assert "Completed in 0.42s" in pages[0].text
    assert pages[0].metadata["format"] == "jupyter_notebook"


@pytest.mark.asyncio
async def test_structured_data_parsers(tmp_path: Path):
    # YAML
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("rag:\n  top_k: 10\n  clearance_level: 4\n", encoding="utf-8")
    yaml_pages = DocumentParser.parse(yaml_path)
    assert "clearance_level: 4" in yaml_pages[0].text

    # TOML
    toml_path = tmp_path / "pyproject.toml"
    toml_path.write_text('[engine]\nname = "ragapp"\nversion = "2.0"\n', encoding="utf-8")
    toml_pages = DocumentParser.parse(toml_path)
    assert "ragapp" in toml_pages[0].text

    # XML
    xml_path = tmp_path / "manifest.xml"
    xml_path.write_text('<system enclave="airgap"><node id="node-01">Master</node></system>', encoding="utf-8")
    xml_pages = DocumentParser.parse(xml_path)
    assert "<system" in xml_pages[0].text
    assert "Master" in xml_pages[0].text

    # JSONL
    jsonl_path = tmp_path / "events.jsonl"
    jsonl_path.write_text('{"event": "login", "user": "admin"}\n{"event": "query", "user": "analyst"}\n', encoding="utf-8")
    jsonl_pages = DocumentParser.parse(jsonl_path)
    assert "analyst" in jsonl_pages[0].text
    assert jsonl_pages[0].metadata["record_count"] == 2

    # RTF
    rtf_path = tmp_path / "document.rtf"
    rtf_path.write_text(r"{\rtf1\ansi{\fonttbl\f0\fswiss Helvetica;}\f0\pard Classified Mission Directive\par}", encoding="utf-8")
    rtf_pages = DocumentParser.parse(rtf_path)
    assert "Classified Mission Directive" in rtf_pages[0].text


@pytest.mark.asyncio
async def test_archive_parser(tmp_path: Path):
    zip_path = tmp_path / "project_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("docs/readme.md", "# Airgap Sovereign Engine\nCompletely local execution.")
        z.writestr("src/core.py", "def authenticate_node():\n    return True\n")

    pages = DocumentParser.parse(zip_path)
    assert len(pages) == 2
    assert any("Airgap Sovereign Engine" in p.text for p in pages)
    assert any("authenticate_node" in p.text for p in pages)
    assert pages[0].metadata["archive_name"] == "project_bundle.zip"

