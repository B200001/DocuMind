"""
Shared type definitions for all loaders.

Every loader returns:
    list[PageSection]

where each PageSection is a TypedDict with guaranteed keys so
downstream chunkers / embedders can treat all sources uniformly.
"""

from typing import Optional, TypedDict


class PageSection(TypedDict):
    """One logical unit of text from any source document."""

    text:        str             # cleaned, non-empty text content
    page:        Optional[int]   # 1-based page number (PDFs); None for others
    section:     Optional[str]   # heading / section title if available
    source_path: str             # absolute path of the originating file
