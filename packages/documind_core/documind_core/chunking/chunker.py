"""
Structure-aware, token-based chunker.

Design
------
Input is the list of PageSection objects for a *single* document (as
produced by documind_core.loaders) plus that document's doc_id. Sections
are treated as the atomic unit of structure:

  * A section that fits within the target chunk size is never split —
    it is packed together with neighboring sections up to the token budget.
  * A section that exceeds the target size on its own is split internally
    on token boundaries (with the same overlap rules applied).
  * Overlap (~15% of chunk_size) is carried from the tail of one chunk
    into the head of the next, so retrieval doesn't lose context at
    chunk boundaries.
  * Chunk IDs are deterministic: f"{doc_id}:{ordinal}" — re-running the
    chunker on the same input always produces the same IDs, making
    re-ingestion idempotent (upserts overwrite rather than duplicate).

This module has no dependency on the SQLModel `Chunk` table — it returns
plain `ChunkRecord` dataclasses with the same field names, so callers can
do `Chunk(**asdict(chunk_record))` or map fields explicitly without this
package needing a DB/network dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from documind_core.chunking.tokenizer import get_tokenizer, is_using_fallback_tokenizer

# ─── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE_TOKENS = 512
DEFAULT_OVERLAP_RATIO = 0.15  # ~15%


# ─── Output shape ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChunkRecord:
    """
    Chunk-shaped output of the chunker.

    Field names intentionally mirror documind_core.models.Chunk so callers
    can construct the ORM model directly from this dataclass's fields.
    """

    id: str                      # deterministic: f"{doc_id}:{ordinal}"
    doc_id: str
    ordinal: int                 # 0-based position within the document
    text: str
    token_count: int
    page: Optional[int] = None
    section: Optional[str] = None
    source_path: Optional[str] = None


# ─── Internal working types ─────────────────────────────────────────────────

@dataclass
class _Section:
    """A section annotated with its token encoding, for internal use."""

    text: str
    page: Optional[int]
    section: Optional[str]
    source_path: Optional[str]
    token_ids: list[int] = field(default_factory=list)


# ─── Public API ──────────────────────────────────────────────────────────────

def chunk_document(
    doc_id: str,
    sections: list[dict],
    chunk_size_tokens: int = DEFAULT_CHUNK_SIZE_TOKENS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[ChunkRecord]:
    """
    Chunk a single document's sections into ~chunk_size_tokens pieces.

    Parameters
    ----------
    doc_id:
        Stable identifier for the source document. Used to build
        deterministic chunk IDs.
    sections:
        Ordered list of PageSection-shaped dicts (keys: text, page,
        section, source_path) — typically the output of
        documind_core.loaders.load_document(). Must all belong to the
        same document and be in reading order.
    chunk_size_tokens:
        Target maximum tokens per chunk (default 512).
    overlap_ratio:
        Fraction of chunk_size_tokens to carry over from the previous
        chunk into the next (default 0.15, i.e. ~77 tokens at size 512).

    Returns
    -------
    list[ChunkRecord]
        Chunks in document order, ordinal starting at 0, with metadata
        (page, section, source_path) propagated from the originating
        section(s).

    Notes
    -----
    * If `sections` is empty, returns an empty list.
    * Empty-text sections are skipped.
    * If using the offline word-approximation tokenizer fallback (no
      network access to fetch tiktoken's BPE file), token_count values
      are approximate, not exact BPE counts.
    """
    if not sections:
        return []

    if chunk_size_tokens <= 0:
        raise ValueError("chunk_size_tokens must be positive")
    if not (0.0 <= overlap_ratio < 1.0):
        raise ValueError("overlap_ratio must be in [0.0, 1.0)")

    overlap_tokens = int(round(chunk_size_tokens * overlap_ratio))
    tokenizer = get_tokenizer()
    use_fallback = is_using_fallback_tokenizer()

    # ── Step 1: encode each non-empty section ───────────────────────────
    encoded_sections: list[_Section] = []
    for raw in sections:
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        token_ids = tokenizer.encode(text) if not use_fallback else _word_units(text)
        encoded_sections.append(
            _Section(
                text=text,
                page=raw.get("page"),
                section=raw.get("section"),
                source_path=raw.get("source_path"),
                token_ids=token_ids,
            )
        )

    if not encoded_sections:
        return []

    # ── Step 2: pack sections into chunks, splitting oversized ones ─────
    pieces = _build_pieces(
        encoded_sections,
        chunk_size_tokens=chunk_size_tokens,
        tokenizer=tokenizer,
        use_fallback=use_fallback,
    )

    pieces = _apply_overlap(
        pieces,
        overlap_tokens=overlap_tokens,
        tokenizer=tokenizer,
        use_fallback=use_fallback,
    )

    # ── Step 3: assign deterministic IDs and ordinals ────────────────────
    records: list[ChunkRecord] = []
    for ordinal, piece in enumerate(pieces):
        records.append(
            ChunkRecord(
                id=f"{doc_id}:{ordinal}",
                doc_id=doc_id,
                ordinal=ordinal,
                text=piece["text"],
                token_count=piece["token_count"],
                page=piece["page"],
                section=piece["section"],
                source_path=piece["source_path"],
            )
        )

    return records


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _word_units(text: str) -> list[int]:
    """Fallback 'tokenization': one unit per whitespace-split word."""
    return list(range(len(text.split(" "))))


def _decode_words(text: str, start: int, end: int) -> str:
    """Slice *text* by word index [start:end) — fallback-mode decode."""
    words = text.split(" ")
    return " ".join(words[start:end])


def _build_pieces(
    sections: list[_Section],
    chunk_size_tokens: int,
    tokenizer,
    use_fallback: bool,
) -> list[dict]:
    """
    Greedily pack whole sections into pieces up to chunk_size_tokens.

    A section that alone exceeds chunk_size_tokens is split internally
    into multiple pieces (token-sliced, not word/sentence-aware, since
    it has no finer structure to respect).

    Each returned piece dict has: text, token_count, page, section,
    source_path, and an internal _tail_ids list used by _apply_overlap.
    """
    pieces: list[dict] = []

    current_texts: list[str] = []
    current_token_ids: list[int] = []
    current_page: Optional[int] = None
    current_section: Optional[str] = None
    current_source: Optional[str] = None

    def _flush() -> None:
        if not current_token_ids:
            return
        pieces.append(
            {
                "text": "\n\n".join(current_texts).strip(),
                "token_count": len(current_token_ids),
                "page": current_page,
                "section": current_section,
                "source_path": current_source,
                "_tail_ids": list(current_token_ids),
            }
        )

    for sec in sections:
        sec_len = len(sec.token_ids)

        # Case A: section fits standalone within the budget remaining
        # in the current piece → pack it in whole.
        if current_token_ids and (len(current_token_ids) + sec_len) <= chunk_size_tokens:
            current_texts.append(sec.text)
            current_token_ids.extend(sec.token_ids)
            # Keep first-seen page/section/source as the piece's primary
            # metadata (a packed piece may span >1 section).
            continue

        # Case B: section fits within an empty budget → start fresh here.
        if not current_token_ids and sec_len <= chunk_size_tokens:
            current_texts = [sec.text]
            current_token_ids = list(sec.token_ids)
            current_page = sec.page
            current_section = sec.section
            current_source = sec.source_path
            continue

        # Case C: doesn't fit in current piece (but current piece is
        # non-empty) → flush current piece, then re-evaluate this
        # section against a fresh, empty piece.
        if current_token_ids and sec_len <= chunk_size_tokens:
            _flush()
            current_texts = [sec.text]
            current_token_ids = list(sec.token_ids)
            current_page = sec.page
            current_section = sec.section
            current_source = sec.source_path
            continue

        # Case D: section itself exceeds chunk_size_tokens → flush
        # whatever is pending, then split this section internally.
        if current_token_ids:
            _flush()
            current_texts, current_token_ids = [], []
            current_page = current_section = current_source = None

        start = 0
        while start < sec_len:
            end = min(start + chunk_size_tokens, sec_len)
            sub_ids = sec.token_ids[start:end]
            if use_fallback:
                sub_text = _decode_words(sec.text, start, end)
            else:
                sub_text = tokenizer.decode(sub_ids)

            pieces.append(
                {
                    "text": sub_text.strip(),
                    "token_count": len(sub_ids),
                    "page": sec.page,
                    "section": sec.section,
                    "source_path": sec.source_path,
                    "_tail_ids": list(sub_ids),
                }
            )
            start = end

    _flush()
    return pieces


def _apply_overlap(
    pieces: list[dict],
    overlap_tokens: int,
    tokenizer,
    use_fallback: bool,
) -> list[dict]:
    """
    Prepend the tail of each piece to the *next* piece's text, so
    consecutive chunks share ~overlap_tokens of context.

    The first piece is left untouched (nothing precedes it). Token counts
    are recomputed after prepending so token_count stays accurate.
    """
    if overlap_tokens <= 0 or len(pieces) < 2:
        for p in pieces:
            p.pop("_tail_ids", None)
        return pieces

    result: list[dict] = []
    previous_tail_ids: Optional[list[int]] = None
    previous_tail_text: Optional[str] = None

    for piece in pieces:
        tail_ids = piece["_tail_ids"][-overlap_tokens:]
        if use_fallback:
            full_words = piece["text"].split(" ")
            n = min(overlap_tokens, len(full_words))
            tail_text = " ".join(full_words[-n:]) if n > 0 else ""
        else:
            tail_text = tokenizer.decode(tail_ids) if tail_ids else ""

        if previous_tail_ids is None:
            new_text = piece["text"]
            new_token_count = piece["token_count"]
        else:
            new_text = f"{previous_tail_text}\n\n{piece['text']}".strip()
            new_token_count = piece["token_count"] + len(previous_tail_ids)

        result.append(
            {
                "text": new_text,
                "token_count": new_token_count,
                "page": piece["page"],
                "section": piece["section"],
                "source_path": piece["source_path"],
            }
        )

        previous_tail_ids = tail_ids
        previous_tail_text = tail_text

    return result
