"""
Loader registry — dispatches to the correct loader by file extension / MIME type.

Usage
-----
    from documind_core.loaders import load_document

    pages = load_document("/path/to/report.pdf")
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from documind_core.loaders._types import PageSection
from documind_core.loaders.pdf      import load_pdf, EmptyPDFError
from documind_core.loaders.docx     import load_docx
from documind_core.loaders.html     import load_html
from documind_core.loaders.markdown import load_markdown


# ─── Exceptions ───────────────────────────────────────────────────────────────

class UnsupportedFileTypeError(ValueError):
    """Raised when no loader exists for the given file type."""


class ScannedPDFError(ValueError):
    """
    Raised when a PDF contains no extractable text.
    Signals that OCR is required before this document can be ingested.
    """


# ─── Extension → loader mapping ───────────────────────────────────────────────

_EXT_MAP: dict[str, str] = {
    ".pdf":      "pdf",
    ".docx":     "docx",
    ".doc":      "docx",      # best-effort; python-docx may reject old .doc
    ".html":     "html",
    ".htm":      "html",
    ".md":       "markdown",
    ".markdown": "markdown",
    ".txt":      "markdown",  # treat plain text like headingless markdown
}

_MIME_MAP: dict[str, str] = {
    "application/pdf":                                        "pdf",
    "application/vnd.openxmlformats-officedocument"
    ".wordprocessingml.document":                            "docx",
    "text/html":                                             "html",
    "text/markdown":                                         "markdown",
    "text/plain":                                            "markdown",
}

_LOADERS = {
    "pdf":      load_pdf,
    "docx":     load_docx,
    "html":     load_html,
    "markdown": load_markdown,
}


# ─── Public API ───────────────────────────────────────────────────────────────

def load_document(path: str | Path) -> list[PageSection]:
    """
    Load a document and return a normalized list of PageSection objects.

    Dispatch order
    --------------
    1. File extension (fast, reliable for well-named files)
    2. MIME type sniffed by the stdlib ``mimetypes`` module (fallback)

    Parameters
    ----------
    path:
        Path to the document. Must exist on disk.

    Returns
    -------
    list[PageSection]
        Normalised page/section objects with ``text``, ``page``,
        ``section``, and ``source_path`` keys.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    UnsupportedFileTypeError
        If no loader is registered for this file type.
    ScannedPDFError
        If the file is a PDF with no extractable text (needs OCR).
    """
    resolved = Path(path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Document not found: {resolved}")

    loader_key = _resolve_loader(resolved)

    try:
        return _LOADERS[loader_key](str(resolved))
    except EmptyPDFError as exc:
        raise ScannedPDFError(
            f"'{resolved.name}' appears to be a scanned PDF with no "
            "extractable text. Run it through an OCR pipeline first "
            "(e.g. ocrmypdf) before ingesting."
        ) from exc


def supported_extensions() -> list[str]:
    """Return the list of file extensions this registry can handle."""
    return sorted(_EXT_MAP.keys())


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _resolve_loader(path: Path) -> str:
    """Return the loader key for *path*, or raise UnsupportedFileTypeError."""

    # 1. Try extension first (most reliable)
    ext = path.suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]

    # 2. Fall back to MIME sniffing
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime in _MIME_MAP:
        return _MIME_MAP[mime]

    raise UnsupportedFileTypeError(
        f"No loader registered for '{path.name}' "
        f"(extension='{ext}', mime='{mime}'). "
        f"Supported extensions: {', '.join(sorted(_EXT_MAP))}."
    )
