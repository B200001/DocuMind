"""
PDF loader using PyMuPDF (fitz).

Returns one PageSection per page.
Raises EmptyPDFError if every page is blank (likely a scanned PDF needing OCR).
"""

from __future__ import annotations

import fitz  # PyMuPDF

from documind_core.loaders._types import PageSection


class EmptyPDFError(ValueError):
    """Raised when a PDF contains no extractable text (likely scanned)."""


def load_pdf(path: str) -> list[PageSection]:
    """
    Load a PDF and return one PageSection per page.

    Parameters
    ----------
    path:
        Absolute or relative path to the .pdf file.

    Returns
    -------
    list[PageSection]
        One entry per page that contains at least some text.

    Raises
    ------
    EmptyPDFError
        If the document has pages but zero extractable text across all of them.
    FileNotFoundError
        If the file does not exist.
    """
    doc = fitz.open(path)

    if doc.page_count == 0:
        return []

    pages: list[PageSection] = []
    total_text = 0

    for page_num in range(doc.page_count):
        page = doc[page_num]
        raw = page.get_text("text")          # plain-text extraction
        text = raw.strip()
        total_text += len(text)

        if not text:
            continue                          # skip genuinely blank pages

        pages.append(
            PageSection(
                text=text,
                page=page_num + 1,           # 1-based
                section=None,                # PDFs have no heading structure here
                source_path=path,
            )
        )

    if total_text == 0:
        raise EmptyPDFError(
            f"No extractable text found in '{path}'. "
            "This PDF is likely scanned and requires OCR before ingestion."
        )

    return pages
