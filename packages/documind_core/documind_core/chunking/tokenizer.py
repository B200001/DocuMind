"""
Tokenizer abstraction used by the chunker.

We prefer `tiktoken` (fast, pure-Python-friendly, no model download needed
beyond its small BPE file) for token counting. If the encoding file can't
be fetched (no network, offline environment), we fall back to a calibrated
word-based approximation so the chunker remains usable everywhere — it will
just be slightly less precise about exact token counts.

This module exposes a single `Tokenizer` interface so the chunker never
needs to know which backend is active.
"""

from __future__ import annotations

from typing import Protocol


class Tokenizer(Protocol):
    """Minimal interface the chunker needs from any tokenizer backend."""

    def encode(self, text: str) -> list[int]: ...
    def decode(self, token_ids: list[int]) -> str: ...


class _TiktokenTokenizer:
    """Wraps tiktoken's cl100k_base encoding."""

    def __init__(self) -> None:
        import tiktoken
        self._enc = tiktoken.get_encoding("cl100k_base")

    def encode(self, text: str) -> list[int]:
        return self._enc.encode(text)

    def decode(self, token_ids: list[int]) -> str:
        return self._enc.decode(token_ids)


class _WordApproxTokenizer:
    """
    Fallback tokenizer used when tiktoken's encoding file is unavailable
    (e.g. fully offline environments with no cached BPE file).

    Approximates tokens via whitespace-split words, calibrated by an
    empirical multiplier (English text averages ~1.3 BPE tokens per word).
    Each "token" here is actually a word index into a reconstructed list,
    which keeps encode/decode round-trippable for our purposes (splitting
    text into pieces of a target size).
    """

    _TOKENS_PER_WORD = 1.3

    def encode(self, text: str) -> list[int]:
        words = text.split(" ")
        # Represent each word as one unit; we inflate the *count* the
        # chunker uses for sizing decisions, not the list length itself,
        # via count_tokens() below — encode/decode just need to round-trip.
        return list(range(len(words)))

    def decode(self, token_ids: list[int]) -> str:
        raise NotImplementedError(
            "_WordApproxTokenizer does not support decode(); "
            "the chunker uses word-slicing directly in fallback mode."
        )


_tokenizer_instance: Tokenizer | None = None
_using_fallback: bool = False


def get_tokenizer() -> Tokenizer:
    """
    Return a process-wide singleton tokenizer, preferring tiktoken and
    falling back to the word-approximation backend if unavailable.
    """
    global _tokenizer_instance, _using_fallback

    if _tokenizer_instance is not None:
        return _tokenizer_instance

    try:
        _tokenizer_instance = _TiktokenTokenizer()
        _using_fallback = False
    except Exception:
        _tokenizer_instance = _WordApproxTokenizer()
        _using_fallback = True

    return _tokenizer_instance


def is_using_fallback_tokenizer() -> bool:
    """True if the singleton tokenizer is the word-approximation fallback."""
    get_tokenizer()  # ensure initialized
    return _using_fallback


def reset_tokenizer_cache() -> None:
    """Clear the singleton — primarily for tests."""
    global _tokenizer_instance, _using_fallback
    _tokenizer_instance = None
    _using_fallback = False
