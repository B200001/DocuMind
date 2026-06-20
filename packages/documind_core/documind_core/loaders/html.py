"""
HTML loader using BeautifulSoup4.

Strips <script>, <style>, and other non-content tags, then segments the
document by heading tags (h1-h6). Each heading starts a new PageSection.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

from documind_core.loaders._types import PageSection

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_STRIP_TAGS   = {"script", "style", "noscript", "head", "meta",
                 "link", "svg", "iframe", "canvas"}


def _visible_text(tag: Tag) -> str:
    """Extract visible text from a BS4 tag, collapsing whitespace."""
    return " ".join(tag.get_text(" ", strip=True).split())


def load_html(path: str) -> list[PageSection]:
    """
    Load an HTML file and return one PageSection per heading-delimited section.

    Parameters
    ----------
    path:
        Absolute or relative path to the .html / .htm file.

    Returns
    -------
    list[PageSection]
        One entry per logical section.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()

    soup = BeautifulSoup(raw, "html.parser")

    # Remove non-content tags in-place
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    sections: list[PageSection] = []
    current_heading: str | None = None
    current_parts: list[str] = []

    def _flush() -> None:
        text = " ".join(current_parts).strip()
        if text:
            sections.append(
                PageSection(
                    text=text,
                    page=None,
                    section=current_heading,
                    source_path=path,
                )
            )

    for element in soup.body.descendants if soup.body else soup.descendants:
        if not isinstance(element, Tag):
            continue

        tag_name = element.name.lower() if element.name else ""

        if tag_name in _HEADING_TAGS:
            _flush()
            current_heading = _visible_text(element)
            current_parts = []
        elif tag_name in {"p", "li", "td", "th", "blockquote", "pre", "div"}:
            # Only grab leaf-ish blocks (skip if they contain nested blocks)
            child_tags = {
                c.name for c in element.children
                if isinstance(c, Tag) and c.name
            }
            block_children = child_tags & {
                "p", "div", "ul", "ol", "table", "blockquote", "pre"
            }
            if block_children:
                continue                     # will be handled by inner elements

            text = _visible_text(element)
            if text:
                current_parts.append(text)

    _flush()
    return sections
