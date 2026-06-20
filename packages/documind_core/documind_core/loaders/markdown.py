"""
Markdown loader.
Parses Markdown headings natively (no HTML round-trip) so heading
metadata is preserved accurately. Falls back to full-text if no
headings are present.
"""
from __future__ import annotations  # Enable postponed evaluation of type annotations

import re  # Standard library module for regular expressions

from documind_core.loaders._types import PageSection  # Import the PageSection type used as the return value

# Matches ATX headings: # … through ###### …
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)  # Compile regex: capture 1-6 '#' chars, then heading text, multiline mode so ^ matches start of each line


def load_markdown(path: str) -> list[PageSection]:  # Define function taking a file path and returning a list of PageSection
    """
    Load a Markdown file and return one PageSection per heading-delimited section.

    Parameters
    ----------
    path:
        A.

    Returns
    -------
    list[PageSection]
        One entry per logical section (heading → next heading).
        If no headings exist, one entry for the entire file.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:  # Open the file as UTF-8, replacing any invalid byte sequences
        content = fh.read()  # Read the entire file content into a string

    # Find all heading positions
    heading_matches = list(_HEADING_RE.finditer(content))  # Find every heading match in the content and materialize as a list

    if not heading_matches:  # If there are no headings in the document
        # No headings — return the whole file as one section
        text = _clean(content)  # Clean up the whole file's text (strip whitespace, collapse blank lines)
        if text:  # If the cleaned text is non-empty
            return [PageSection(text=text, page=None,
                                 section=None, source_path=path)]  # Return a single PageSection covering the whole file
        return []  # Otherwise (empty file/content), return an empty list

    sections: list[PageSection] = []  # Initialize the list that will collect all resulting sections

    # Text before the first heading (e.g. a preamble / front matter)
    preamble = content[: heading_matches[0].start()].strip()  # Slice out everything before the first heading and strip whitespace
    if _clean(preamble):  # If the cleaned preamble text is non-empty
        sections.append(
            PageSection(
                text=_clean(preamble),  # Use the cleaned preamble text as the section's text
                page=None,  # No page number applies to Markdown
                section=None,  # No heading name applies to the preamble
                source_path=path,  # Record the source file path
            )
        )  # Append the preamble section to the list

    for idx, match in enumerate(heading_matches):  # Iterate over each heading match along with its index
        heading_text = match.group(2).strip()  # Extract and strip the heading's text (group 2 is the text after the '#'s)

        # Body = text between this heading and the next (or end of file)
        body_start = match.end()  # Body starts right after the current heading match ends
        body_end = (
            heading_matches[idx + 1].start()  # If there's a next heading, body ends where it starts
            if idx + 1 < len(heading_matches)  # Check whether a next heading exists
            else len(content)  # Otherwise body runs to the end of the file
        )
        body = _clean(content[body_start:body_end])  # Slice out and clean the body text for this section

        # Always emit a section — even if body is empty — so the heading
        # itself isn't lost (useful for table-of-contents style docs)
        sections.append(
            PageSection(
                text=f"{heading_text}\n{body}".strip(),  # Combine heading and body into the section's text, trimmed
                page=None,  # No page number applies to Markdown
                section=heading_text,  # Record this heading as the section name
                source_path=path,  # Record the source file path
            )
        )  # Append this heading's section to the list

    return [s for s in sections if s["text"]]  # Filter out any sections with empty text before returning


def _clean(text: str) -> str:  # Define a helper function to normalize whitespace in a text block
    """Strip excessive blank lines and trailing whitespace."""
    lines = text.splitlines()  # Split the text into individual lines
    cleaned = "\n".join(line.rstrip() for line in lines)  # Rejoin lines after stripping trailing whitespace from each
    # Collapse 3+ consecutive blank lines → 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # Replace runs of 3+ newlines with exactly two newlines
    return cleaned.strip()  # Strip leading/trailing whitespace from the whole block and return it