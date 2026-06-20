"""
DOCX loader using python-docx.

Groups paragraphs by heading: each time a Heading style is encountered
a new section starts. Non-heading paragraphs are accumulated under the
current heading.
"""

from __future__ import annotations

import docx  # python-docx

from documind_core.loaders._types import PageSection

# Styles that Word uses for headings (covers Heading 1 – Heading 9)
_HEADING_PREFIXES = ("Heading", "Title", "Subtitle")


def _is_heading(paragraph: docx.text.paragraph.Paragraph) -> bool:
    style_name: str = paragraph.style.name or ""
    return any(style_name.startswith(p) for p in _HEADING_PREFIXES)


def load_docx(path: str) -> list[PageSection]:
    """
    Load a .docx file and return one PageSection per heading-delimited section.

    If the document has no headings at all, the entire text is returned as
    a single PageSection with section=None.

    Parameters
    ----------
    path:
        Absolute or relative path to the .docx file.

    Returns
    -------
    list[PageSection]
        One entry per logical section (heading → next heading).
    """
    document = docx.Document(path)

    sections: list[PageSection] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                PageSection(
                    text=text,
                    page=None,
                    section=current_heading,
                    source_path=path,
                )
            )

    for para in document.paragraphs:
        raw = para.text.strip()
        if not raw:
            continue

        if _is_heading(para):
            _flush()                         # save previous section
            current_heading = raw
            current_lines = []
        else:
            current_lines.append(raw)

    _flush()                                 # save last section
    return sections
