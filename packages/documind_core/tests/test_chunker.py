"""
Unit tests for documind_core.chunking.chunker.

Covers:
  * Boundary sizes — exact fit, just-under, just-over the chunk target
  * Overlap correctness — adjacent chunks share the expected tail/head tokens
  * Metadata propagation — doc_id, page, section, source_path, ordinal
  * Deterministic / idempotent chunk IDs across repeated runs
  * Edge cases — empty input, whitespace-only sections, zero overlap
"""

from __future__ import annotations

import pytest

from documind_core.chunking.chunker import chunk_document, ChunkRecord
from documind_core.chunking.tokenizer import get_tokenizer, is_using_fallback_tokenizer


# ─── Helpers ──────────────────────────────────────────────────────────────────

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _token_unit(i: int, prefix: str = "") -> str:
    """
    Return one whitespace-delimited unit that encodes to exactly one token.

    With tiktoken each unit is a single letter (prefix is ignored — use
    section metadata to distinguish sections). With the word-based fallback
    each unit is one synthetic word index, optionally prefixed.
    """
    if is_using_fallback_tokenizer():
        p = prefix or "w"
        return f"{p}{i}"
    return _ALPHABET[i % len(_ALPHABET)]


def _tokens(n: int, prefix: str = "") -> str:
    """Generate text that encodes to exactly *n* tokens with the active tokenizer."""
    text = " ".join(_token_unit(i, prefix) for i in range(n))
    assert len(_encode(text)) == n, f"_tokens({n}) produced {len(_encode(text))} tokens"
    return text


def _section(text: str, page=None, section=None, source_path="/doc.pdf") -> dict:
    return {"text": text, "page": page, "section": section, "source_path": source_path}


def _encode(text: str) -> list[int]:
    """Encode *text* the same way the chunker does."""
    tokenizer = get_tokenizer()
    if is_using_fallback_tokenizer():
        return list(range(len(text.split(" "))))
    return tokenizer.encode(text)


def _token_slice(text: str, start: int, end: int) -> str:
    """Decode token indices [start:end) from *text* — mirrors chunker slicing."""
    tokenizer = get_tokenizer()
    if is_using_fallback_tokenizer():
        words = text.split(" ")
        return " ".join(words[start:end])
    return tokenizer.decode(_encode(text)[start:end])


def _overlap_head(chunk_text: str) -> str:
    """Return the overlap prefix prepended to a chunk (text before the first '\\n\\n')."""
    return chunk_text.split("\n\n", 1)[0]


def _chunk_text_for_range(source: str, start: int, end: int) -> str:
    """
    Expected chunk text for token range [start:end).

    The chunker strips decoded BPE slices; mirror that here so assertions
    match production output.
    """
    sliced = _token_slice(source, start, end)
    return sliced if is_using_fallback_tokenizer() else sliced.strip()


# ─── Boundary size tests ──────────────────────────────────────────────────────

class TestBoundarySizes:

    def test_section_exactly_at_chunk_size_is_one_chunk(self):
        text = _tokens(512)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 1
        assert chunks[0].token_count == 512

    def test_section_one_token_over_splits_into_two(self):
        text = _tokens(513)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 2
        assert chunks[0].token_count == 512
        assert chunks[1].token_count == 1

    def test_section_one_token_under_is_single_chunk(self):
        text = _tokens(511)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 1
        assert chunks[0].token_count == 511

    def test_two_small_sections_pack_into_one_chunk(self):
        sections = [_section(_tokens(100)), _section(_tokens(100))]
        chunks = chunk_document("doc1", sections, chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 1
        assert chunks[0].token_count == 200

    def test_section_that_fits_is_never_split_even_if_next_does_not_fit(self):
        # A 400-token section followed by a 400-token section: together
        # they exceed 512, so the second section must start a NEW chunk
        # rather than being truncated/split across the boundary.
        sections = [_section(_tokens(400), section="A"), _section(_tokens(400), section="B")]
        chunks = chunk_document("doc1", sections, chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 2
        # First chunk is exactly the first section, untouched.
        assert chunks[0].token_count == 400
        assert chunks[0].section == "A"
        # Second chunk is exactly the second section, untouched (no overlap requested).
        assert chunks[1].token_count == 400
        assert chunks[1].section == "B"

    def test_oversized_section_splits_into_ceil_division_pieces(self):
        # 1500 tokens / 512 per chunk, with 0 overlap -> 3 pieces (512, 512, 476)
        text = _tokens(1500)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 3
        assert chunks[0].token_count == 512
        assert chunks[1].token_count == 512
        assert chunks[2].token_count == 476

    def test_empty_sections_list_returns_empty(self):
        assert chunk_document("doc1", []) == []

    def test_whitespace_only_section_is_skipped(self):
        chunks = chunk_document("doc1", [_section("   \n\t  ")])
        assert chunks == []

    def test_invalid_chunk_size_raises(self):
        with pytest.raises(ValueError):
            chunk_document("doc1", [_section("hello")], chunk_size_tokens=0)

    def test_invalid_overlap_ratio_raises(self):
        with pytest.raises(ValueError):
            chunk_document("doc1", [_section("hello")], overlap_ratio=1.0)
        with pytest.raises(ValueError):
            chunk_document("doc1", [_section("hello")], overlap_ratio=-0.1)


# ─── Overlap tests ─────────────────────────────────────────────────────────────

class TestOverlap:

    def test_zero_overlap_chunks_do_not_share_tokens(self):
        text = _tokens(1000)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.0)

        assert chunks[0].token_count == 512
        assert chunks[1].token_count == 488
        assert chunks[0].text == _chunk_text_for_range(text, 0, 512)
        assert chunks[1].text == _chunk_text_for_range(text, 512, 1000)
        assert _encode(text)[511] != _encode(text)[512]  # clean boundary

    def test_overlap_carries_expected_word_count_into_next_chunk(self):
        # chunk_size=512, overlap_ratio=0.15 -> 77 overlap tokens
        text = _tokens(1000)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.15)

        # Second chunk's token_count should be (piece size) + 77 carried over
        # The raw second piece (before overlap) covers tokens [512:1000) = 488 tokens
        assert chunks[1].token_count == 488 + 77

    def test_overlap_head_of_next_chunk_matches_tail_of_previous(self):
        text = _tokens(1000)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.15)

        overlap_n = 77
        tail_of_first = _chunk_text_for_range(text, 512 - overlap_n, 512)
        head_of_second = _overlap_head(chunks[1].text)

        assert head_of_second == tail_of_first

    def test_first_chunk_has_no_overlap_prepended(self):
        text = _tokens(1000)
        chunks = chunk_document("doc1", [_section(text)], chunk_size_tokens=512, overlap_ratio=0.15)

        assert chunks[0].token_count == 512  # untouched, nothing precedes it
        assert chunks[0].text == _chunk_text_for_range(text, 0, 512)

    def test_overlap_across_multiple_packed_sections(self):
        # Three sections each 300 tokens: with chunk_size=512 they pack as
        # [sec0(300)] then [sec1(300)] then [sec2(300)] roughly, since
        # 300+300=600 > 512. Overlap should still bridge correctly.
        section_a = _tokens(300)
        sections = [
            _section(section_a, section="A"),
            _section(_tokens(300), section="B"),
            _section(_tokens(300), section="C"),
        ]
        chunks = chunk_document("doc1", sections, chunk_size_tokens=512, overlap_ratio=0.15)

        assert len(chunks) == 3
        # 0.15 * 512 = 76.8 -> rounds to 77
        overlap_n = 77
        tail_of_0 = _chunk_text_for_range(section_a, 300 - overlap_n, 300)
        assert _overlap_head(chunks[1].text) == tail_of_0


# ─── Metadata propagation tests ────────────────────────────────────────────────

class TestMetadataPropagation:

    def test_doc_id_propagates_to_every_chunk(self):
        sections = [_section(_tokens(50), page=1), _section(_tokens(50), page=2)]
        chunks = chunk_document("my-doc-123", sections)

        assert all(c.doc_id == "my-doc-123" for c in chunks)

    def test_ordinals_are_sequential_from_zero(self):
        sections = [_section(_tokens(50)) for _ in range(5)]
        chunks = chunk_document("doc1", sections, chunk_size_tokens=40, overlap_ratio=0.0)

        assert [c.ordinal for c in chunks] == list(range(len(chunks)))

    def test_chunk_id_format_is_deterministic(self):
        sections = [_section(_tokens(50))]
        chunks = chunk_document("abc-123", sections)

        assert chunks[0].id == "abc-123:0"

    def test_page_and_section_propagate_for_single_section_chunk(self):
        chunks = chunk_document(
            "doc1",
            [_section(_tokens(50), page=7, section="Methodology")],
        )

        assert chunks[0].page == 7
        assert chunks[0].section == "Methodology"

    def test_source_path_propagates(self):
        chunks = chunk_document(
            "doc1",
            [_section(_tokens(50), source_path="/data/uploads/report.pdf")],
        )

        assert chunks[0].source_path == "/data/uploads/report.pdf"

    def test_packed_chunk_keeps_first_sections_metadata(self):
        # When multiple small sections are packed into one chunk, the
        # chunk's page/section metadata reflects the FIRST section packed.
        sections = [
            _section(_tokens(50), page=1, section="Intro"),
            _section(_tokens(50), page=2, section="Body"),
        ]
        chunks = chunk_document("doc1", sections, chunk_size_tokens=512, overlap_ratio=0.0)

        assert len(chunks) == 1
        assert chunks[0].page == 1
        assert chunks[0].section == "Intro"

    def test_split_oversized_section_repeats_same_metadata_on_every_piece(self):
        text = _tokens(1200)
        chunks = chunk_document(
            "doc1",
            [_section(text, page=3, section="BigSection")],
            chunk_size_tokens=512,
            overlap_ratio=0.0,
        )

        assert len(chunks) == 3
        assert all(c.page == 3 for c in chunks)
        assert all(c.section == "BigSection" for c in chunks)

    def test_multi_document_doc_ids_do_not_collide(self):
        sections = [_section(_tokens(50))]
        chunks_a = chunk_document("doc-a", sections)
        chunks_b = chunk_document("doc-b", sections)

        assert chunks_a[0].id == "doc-a:0"
        assert chunks_b[0].id == "doc-b:0"
        assert chunks_a[0].id != chunks_b[0].id


# ─── Idempotency / re-ingest tests ─────────────────────────────────────────────

class TestIdempotency:

    def test_repeated_runs_produce_identical_ids(self):
        sections = [_section(_tokens(50), page=i) for i in range(10)]

        run1 = chunk_document("doc1", sections, chunk_size_tokens=128, overlap_ratio=0.1)
        run2 = chunk_document("doc1", sections, chunk_size_tokens=128, overlap_ratio=0.1)

        assert [c.id for c in run1] == [c.id for c in run2]

    def test_repeated_runs_produce_identical_text(self):
        sections = [_section(_tokens(700))]

        run1 = chunk_document("doc1", sections, chunk_size_tokens=256, overlap_ratio=0.15)
        run2 = chunk_document("doc1", sections, chunk_size_tokens=256, overlap_ratio=0.15)

        assert [c.text for c in run1] == [c.text for c in run2]

    def test_chunk_record_is_a_dataclass_with_expected_fields(self):
        chunks = chunk_document("doc1", [_section("hello world")])
        record = chunks[0]

        assert isinstance(record, ChunkRecord)
        for attr in ("id", "doc_id", "ordinal", "text", "token_count",
                     "page", "section", "source_path"):
            assert hasattr(record, attr)
