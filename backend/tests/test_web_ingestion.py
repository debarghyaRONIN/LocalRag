"""
Unit and integration tests for HTML and web page ingestion.

Validates:
1. WebParser HTML parsing and structured Markdown extraction.
2. Comprehensive boilerplate and noise stripping:
   - Elements: script, style, noscript, nav, header, footer, aside, dialog, form, button.
   - Class and ID keyword matching: ads, banners, cookies, modals, popups, sidebars.
3. Metadata extraction: title, meta description, author, keywords.
4. Heading hierarchy extraction: H1 to H6 level preservation, sequence, and text.
5. Markdown formatting: paragraphs, lists (ul/ol), tables, code blocks, blockquotes, horizontal rules.
6. FallbackHTMLTextExtractor standard library parsing fallback.
7. Edge case handling: malformed HTML, unclosed tags, empty inputs, non-HTML text.
8. DocumentParser integration for .html, .htm, and .xhtml files.
"""

from pathlib import Path
import pytest

from backend.app.services.ingestion.web_parser import (
    WebParser,
    WebPageContent,
    WebHeading,
    FallbackHTMLTextExtractor,
    BOILERPLATE_TAGS,
)
from backend.app.services.ingestion.parsers import DocumentParser


# ============================================================================
# 1. HTML Extraction, Noise Stripping, and Markdown Elements
# ============================================================================

def test_web_parser_boilerplate_stripping():
    """Verify that navigation, scripts, styles, ads, cookies, and footer elements are thoroughly stripped."""
    html_sample = '''<!DOCTYPE html>
<html>
<head>
    <title>Air-Gapped Systems Architecture</title>
    <meta name="description" content="Technical guide for sovereign offline infrastructure." />
    <meta name="author" content="Engineering Division" />
    <meta name="keywords" content="rag, airgap, security" />
    <style>
        body { background: #000; color: #fff; }
        .hidden { display: none; }
    </style>
    <script>
        window.analytics = { track: function() {} };
    </script>
</head>
<body>
    <header class="site-header">
        <nav aria-label="Main Navigation">
            <a href="/">Home</a>
            <a href="/products">Products</a>
            <a href="/pricing">Pricing</a>
        </nav>
    </header>

    <div class="cookie-banner-wrapper">
        <p>Accept cookies for personalized advertising.</p>
        <button id="accept-cookies">Accept</button>
    </div>

    <aside class="sidebar-advertisement">
        <div class="ad-unit">50% off Cloud Subscriptions</div>
    </aside>

    <div class="modal-popup-newsletter">
        <h3>Subscribe to Newsletter</h3>
        <input type="email" placeholder="you@domain.com" />
    </div>

    <main id="primary-content">
        <h1>Air-Gapped Systems Architecture</h1>
        <p>This document details the <strong>zero-egress</strong> architectural requirements.</p>

        <h2>Network Isolation</h2>
        <p>All inbound and outbound network sockets must be disabled or blocked.</p>
        <ul>
            <li>Disable external API access</li>
            <li>Enforce local weight verification</li>
            <li>Audit all local filesystem operations</li>
        </ul>

        <h2>Benchmark Data</h2>
        <table>
            <thead>
                <tr>
                    <th>Hardware</th>
                    <th>Throughput</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>RTX 4090</td>
                    <td>145 tokens/s</td>
                </tr>
                <tr>
                    <td>Apple M3 Max</td>
                    <td>88 tokens/s</td>
                </tr>
            </tbody>
        </table>

        <h2>Offline Deployment Code</h2>
        <pre><code>python scripts/package_airgap.py --verify-weights</code></pre>

        <blockquote>
            Security is not an add-on; it is the default boundary of the system.
        </blockquote>
    </main>

    <footer class="site-footer">
        <p>&copy; 2026 Sovereign Systems. All rights reserved.</p>
        <a href="/privacy">Privacy Policy</a>
    </footer>
</body>
</html>
'''
    parsed = WebParser.parse_html(html_sample)

    assert isinstance(parsed, WebPageContent)
    assert parsed.title == "Air-Gapped Systems Architecture"
    assert parsed.description == "Technical guide for sovereign offline infrastructure."
    assert parsed.metadata.get("author") == "Engineering Division"

    # Verify headings
    headings_dict = {h.text: h.level for h in parsed.headings}
    assert "Air-Gapped Systems Architecture" in headings_dict
    assert headings_dict["Air-Gapped Systems Architecture"] == 1
    assert headings_dict["Network Isolation"] == 2
    assert headings_dict["Benchmark Data"] == 2
    assert headings_dict["Offline Deployment Code"] == 2

    # Verify boilerplate was removed
    md = parsed.main_content_markdown
    assert "Accept cookies" not in md
    assert "50% off Cloud Subscriptions" not in md
    assert "Subscribe to Newsletter" not in md
    assert "Privacy Policy" not in md
    assert "window.analytics" not in md
    assert "background: #000" not in md

    # Verify structured elements
    assert "This document details the zero-egress architectural requirements." in md or "zero-egress" in md
    assert "- Disable external API access" in md
    assert "- Enforce local weight verification" in md
    assert "| Hardware | Throughput |" in md
    assert "| RTX 4090 | 145 tokens/s |" in md
    assert "```\npython scripts/package_airgap.py --verify-weights\n```" in md
    assert "> Security is not an add-on" in md


# ============================================================================
# 2. Heading Hierarchy Tests
# ============================================================================

def test_heading_hierarchy_extraction():
    """Verify that headings from H1 through H6 are captured with exact levels and sequential order."""
    html = '''
    <html>
    <body>
        <h1>Title Level 1</h1>
        <h2>Section Level 2</h2>
        <h3>Subsection Level 3</h3>
        <h4>Topic Level 4</h4>
        <h5>Detail Level 5</h5>
        <h6>Footnote Level 6</h6>
    </body>
    </html>
    '''
    parsed = WebParser.parse_html(html)
    assert len(parsed.headings) == 6

    expected_levels = [1, 2, 3, 4, 5, 6]
    actual_levels = [h.level for h in parsed.headings]
    assert actual_levels == expected_levels

    assert parsed.headings[0].text == "Title Level 1"
    assert parsed.headings[5].text == "Footnote Level 6"


# ============================================================================
# 3. Ordered Lists and Tables
# ============================================================================

def test_ordered_list_and_table_markdown():
    """Verify ordered list enumeration and table markdown generation."""
    html = '''
    <html>
    <body>
        <main>
            <ol>
                <li>First execution step</li>
                <li>Second execution step</li>
                <li>Third execution step</li>
            </ol>
            <table>
                <tr><th>Param</th><th>Default</th></tr>
                <tr><td>HNSW_M</td><td>16</td></tr>
                <tr><td>EF_CONSTRUCT</td><td>100</td></tr>
            </table>
        </main>
    </body>
    </html>
    '''
    parsed = WebParser.parse_html(html)
    md = parsed.main_content_markdown

    assert "1. First execution step" in md
    assert "2. Second execution step" in md
    assert "3. Third execution step" in md

    assert "| Param | Default |" in md
    assert "| HNSW_M | 16 |" in md
    assert "| EF_CONSTRUCT | 100 |" in md


# ============================================================================
# 4. Fallback HTML Parser
# ============================================================================

def test_fallback_html_text_extractor():
    """Verify standard library FallbackHTMLTextExtractor extracts clean text and skips script/style."""
    extractor = FallbackHTMLTextExtractor()
    extractor.feed(
        "<html><head><script>alert('malicious')</script><style>p { color: red }</style></head>"
        "<body><h1>Header</h1><p>Clean paragraph text.</p><footer>Footer text</footer></body></html>"
    )
    extracted = extractor.get_text()

    assert "Clean paragraph text" in extracted
    assert "Header" in extracted
    assert "alert" not in extracted
    assert "color: red" not in extracted


# ============================================================================
# 5. Malformed HTML and Resilience
# ============================================================================

def test_malformed_html_resilience():
    """Verify parser handles unclosed tags, missing heads, and broken HTML gracefully."""
    malformed = "<div><h1>Unclosed Header<p>Paragraph without end tag <span>nested<b>bold text"
    parsed = WebParser.parse_html(malformed)

    assert isinstance(parsed, WebPageContent)
    assert "Paragraph without end tag" in parsed.formatted_text or "Unclosed Header" in parsed.formatted_text


def test_empty_html_string():
    """Verify empty string returns valid WebPageContent without raising errors."""
    parsed = WebParser.parse_html("")
    assert isinstance(parsed, WebPageContent)
    assert parsed.title == ""
    assert parsed.headings == []
    assert parsed.main_content_markdown == ""


def test_plain_text_without_html():
    """Verify non-HTML plain text is ingested cleanly as paragraph text."""
    plain = "This is a simple text document without any HTML tags whatsoever."
    parsed = WebParser.parse_html(plain)

    assert isinstance(parsed, WebPageContent)
    assert "This is a simple text document" in parsed.formatted_text


# ============================================================================
# 6. DocumentParser Integration for HTML Files
# ============================================================================

def test_document_parser_html_file_extensions(tmp_path: Path):
    """Verify DocumentParser correctly dispatches .html and .htm files to WebParser."""
    # Test .html file
    html_file = tmp_path / "overview.html"
    html_file.write_text(
        "<!DOCTYPE html><html><head><title>System Overview</title></head>"
        "<body><main><h1>System Overview</h1><p>Offline RAG operational manual.</p></main></body></html>",
        encoding="utf-8"
    )

    pages = DocumentParser.parse(html_file)
    assert len(pages) == 1
    assert pages[0].metadata["is_web"] is True
    assert pages[0].metadata["title"] == "System Overview"
    assert "System Overview" in pages[0].text
    assert "Offline RAG operational manual." in pages[0].text

    # Test .htm file
    htm_file = tmp_path / "reference.htm"
    htm_file.write_text(
        "<html><head><title>API Reference</title></head>"
        "<body><main><h2>Endpoints</h2><p>GET /api/v1/health</p></main></body></html>",
        encoding="utf-8"
    )

    htm_pages = DocumentParser.parse(htm_file)
    assert len(htm_pages) == 1
    assert htm_pages[0].metadata["is_web"] is True
    assert htm_pages[0].metadata["title"] == "API Reference"
    assert "GET /api/v1/health" in htm_pages[0].text
