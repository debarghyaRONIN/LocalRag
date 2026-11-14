"""
HTML and Web Page parser for knowledge engine ingestion.

Extracts page title, meta description, clean markdown headings, and main content
while stripping navigation, scripts, ads, footers, headers, sidebars, cookie banners,
and promotional clutter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

import lxml.html


@dataclass
class WebHeading:
    level: int
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "text": self.text}


@dataclass
class WebPageContent:
    title: str
    description: str
    headings: List[WebHeading]
    main_content_markdown: str
    formatted_text: str
    metadata: Dict[str, Any]
    raw_html: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "headings": [h.to_dict() for h in self.headings],
            "main_content_markdown": self.main_content_markdown,
            "formatted_text": self.formatted_text,
            "metadata": self.metadata,
        }


# Tags that are stripped completely from HTML documents
BOILERPLATE_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "svg",
    "canvas",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "video",
    "audio",
    "nav",
    "header",
    "footer",
    "aside",
    "dialog",
}

# Substring matches in classes and IDs that indicate non-content boilerplate
BOILERPLATE_CLASS_KEYWORDS = [
    "ad-",
    "ads",
    "advertisement",
    "banner",
    "popup",
    "modal",
    "cookie",
    "gdpr",
    "privacy-banner",
    "sidebar",
    "social",
    "share-button",
    "breadcrumbs",
    "disqus",
    "comments",
    "widget",
    "promo",
    "sponsored",
    "menu",
    "navigation",
]


class FallbackHTMLTextExtractor(HTMLParser):
    """Fallback plain text parser using standard library html.parser."""

    def __init__(self):
        super().__init__()
        self.text_chunks: List[str] = []
        self.current_tag = ""
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()
        if self.current_tag in BOILERPLATE_TAGS:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in BOILERPLATE_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
        if tag.lower() in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self.text_chunks.append("\n")

    def handle_data(self, data):
        if self.skip_depth == 0 and data.strip():
            self.text_chunks.append(data.strip() + " ")

    def get_text(self) -> str:
        return "".join(self.text_chunks).strip()


class WebParser:
    """
    Language and structure-aware Web / HTML content extractor.
    """

    @classmethod
    def clean_element_to_markdown(cls, element: lxml.html.HtmlElement) -> str:
        """
        Recursively converts a clean HTML element hierarchy into readable Markdown.
        """
        parts: List[str] = []

        def walk(el: lxml.html.HtmlElement):
            if not isinstance(el.tag, str):
                return

            tag = el.tag.lower()

            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                text = (el.text_content() or "").strip()
                if text:
                    prefix = "#" * level
                    parts.append(f"\n\n{prefix} {text}\n\n")
                return

            elif tag == "p":
                text = (el.text_content() or "").strip()
                if text:
                    parts.append(f"\n\n{text}\n\n")
                return

            elif tag in ("ul", "ol"):
                is_ol = tag == "ol"
                parts.append("\n")
                idx = 1
                for child in el.iterchildren():
                    if isinstance(child.tag, str) and child.tag.lower() == "li":
                        item_text = (child.text_content() or "").strip()
                        if item_text:
                            if is_ol:
                                parts.append(f"{idx}. {item_text}\n")
                                idx += 1
                            else:
                                parts.append(f"- {item_text}\n")
                parts.append("\n")
                return

            elif tag == "pre":
                code_text = (el.text_content() or "").strip()
                if code_text:
                    parts.append(f"\n\n```\n{code_text}\n```\n\n")
                return

            elif tag == "blockquote":
                quote_text = (el.text_content() or "").strip()
                if quote_text:
                    parts.append(f"\n\n> {quote_text}\n\n")
                return

            elif tag == "table":
                rows = el.xpath(".//tr")
                if rows:
                    parts.append("\n\n")
                    for r_idx, row in enumerate(rows):
                        cells = [c.text_content().strip() for c in row.xpath("./th | ./td")]
                        if cells:
                            parts.append("| " + " | ".join(cells) + " |\n")
                            if r_idx == 0:
                                parts.append("| " + " | ".join(["---"] * len(cells)) + " |\n")
                    parts.append("\n")
                return

            elif tag == "hr":
                parts.append("\n\n---\n\n")
                return

            # Traverse child elements
            for child in el.iterchildren():
                walk(child)

        walk(element)

        raw_md = "".join(parts)
        # Collapse multiple blank lines
        clean_md = re.sub(r"\n{3,}", "\n\n", raw_md).strip()
        return clean_md

    @classmethod
    def parse_html(cls, html_str: str, base_url: Optional[str] = None) -> WebPageContent:
        """
        Parses raw HTML, removes non-content elements, extracts title, meta description,
        structured headings, and converts main content to clean Markdown.
        """
        try:
            doc = lxml.html.fromstring(html_str)
        except Exception:
            # Fallback for heavily corrupted markup
            fallback = FallbackHTMLTextExtractor()
            fallback.feed(html_str)
            text = fallback.get_text()
            return WebPageContent(
                title="",
                description="",
                headings=[],
                main_content_markdown=text,
                formatted_text=text,
                metadata={},
                raw_html=html_str,
            )

        # 1. Extract metadata before tree mutation
        title = ""
        og_title = doc.xpath('//meta[@property="og:title"]/@content')
        title_tags = doc.xpath("//title/text()")
        h1_tags = doc.xpath("//h1/text()")

        if og_title and og_title[0].strip():
            title = og_title[0].strip()
        elif title_tags and title_tags[0].strip():
            title = title_tags[0].strip()
        elif h1_tags and h1_tags[0].strip():
            title = h1_tags[0].strip()

        description = ""
        meta_desc = doc.xpath('//meta[@name="description"]/@content')
        og_desc = doc.xpath('//meta[@property="og:description"]/@content')
        if meta_desc and meta_desc[0].strip():
            description = meta_desc[0].strip()
        elif og_desc and og_desc[0].strip():
            description = og_desc[0].strip()

        author = ""
        author_meta = doc.xpath('//meta[@name="author"]/@content')
        if author_meta and author_meta[0].strip():
            author = author_meta[0].strip()

        canonical_url = ""
        canon_meta = doc.xpath('//link[@rel="canonical"]/@href') or doc.xpath('//meta[@property="og:url"]/@content')
        if canon_meta and canon_meta[0].strip():
            canonical_url = canon_meta[0].strip()

        # 2. Extract Headings hierarchy before stripping
        headings: List[WebHeading] = []
        heading_elements = doc.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6")
        for h_el in heading_elements:
            if isinstance(h_el.tag, str):
                lvl = int(h_el.tag[1])
                h_text = (h_el.text_content() or "").strip()
                if h_text:
                    headings.append(WebHeading(level=lvl, text=h_text))

        # 3. Strip Boilerplate Tags
        for tag in BOILERPLATE_TAGS:
            for el in doc.xpath(f"//{tag}"):
                try:
                    el.drop_tree()
                except Exception:
                    pass

        # 4. Strip Clutter by Class and ID Heuristics
        for keyword in BOILERPLATE_CLASS_KEYWORDS:
            query = f"//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}') or contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]"
            for el in doc.xpath(query):
                tag_name = el.tag.lower() if isinstance(el.tag, str) else ""
                # Do not drop main containers if they coincidentally contain a keyword
                if tag_name not in ("body", "html", "main", "article"):
                    try:
                        el.drop_tree()
                    except Exception:
                        pass

        # 5. Locate Primary Content Root
        content_root = None

        # Check <main>
        mains = doc.xpath("//main")
        if mains and len(mains[0].text_content().strip()) > 30:
            content_root = mains[0]
        else:
            # Check <article>
            articles = doc.xpath("//article")
            if articles and len(articles[0].text_content().strip()) > 30:
                content_root = articles[0]
            else:
                # Check role="main"
                role_mains = doc.xpath('//*[@role="main"]')
                if role_mains and len(role_mains[0].text_content().strip()) > 30:
                    content_root = role_mains[0]
                else:
                    # Check body
                    bodies = doc.xpath("//body")
                    if bodies:
                        content_root = bodies[0]
                    else:
                        content_root = doc

        # 6. Convert Primary Content to Markdown
        main_markdown = cls.clean_element_to_markdown(content_root)

        # Fallback if markdown extraction produced empty text
        if not main_markdown.strip():
            raw_text = (content_root.text_content() or "").strip()
            main_markdown = re.sub(r"\n{3,}", "\n\n", raw_text)

        # 7. Construct Formatted Citation Text
        formatted_blocks = []
        if title:
            # Don't duplicate if markdown already starts with this title heading
            first_line = main_markdown.splitlines()[0] if main_markdown else ""
            if not first_line.startswith(f"# {title}"):
                formatted_blocks.append(f"# {title}")

        if description:
            formatted_blocks.append(f"> {description}")

        if main_markdown:
            formatted_blocks.append(main_markdown)

        formatted_text = "\n\n".join(formatted_blocks).strip()

        metadata = {
            "title": title,
            "description": description,
            "author": author,
            "canonical_url": canonical_url or base_url or "",
            "headings": [h.to_dict() for h in headings],
            "is_web": True,
        }

        return WebPageContent(
            title=title,
            description=description,
            headings=headings,
            main_content_markdown=main_markdown,
            formatted_text=formatted_text,
            metadata=metadata,
            raw_html=html_str,
        )

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> WebPageContent:
        path = Path(file_path)
        html_str = path.read_text(encoding="utf-8", errors="replace")
        return cls.parse_html(html_str, base_url=str(path))
