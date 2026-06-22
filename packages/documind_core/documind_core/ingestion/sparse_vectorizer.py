"""
A small, dependency-free sparse vectorizer that turns chunk text into a
SparseVectorInput (term-index -> raw term-frequency) suitable for Qdrant's
sparse vector index.

WHY THIS EXISTS (read this if you're new to the codebase)
-----------------------------------------------------------
BM25 scoring has two halves:
  1. Term Frequency (TF)  — "how many times does this word appear in THIS chunk?"
  2. Inverse Doc Frequency (IDF) — "how rare is this word across ALL chunks?"

We only need to compute TF here, at ingestion time, because each chunk is
embedded independently and we don't have visibility into the whole corpus
yet. The IDF half is computed automatically by Qdrant itself, at SEARCH
time, because the collection's sparse vector was configured with
`Modifier.IDF` (see qdrant_store.py). So: we send raw word counts in, and
Qdrant turns them into proper BM25-style scores when you search.

HOW TERMS BECOME NUMBERS
-------------------------
Qdrant's sparse vectors are just (index, value) pairs — like a dictionary
where the key is a number, not the actual word. So "refund" might become
index 196397 with value 3.0 (meaning "refund" appeared 3 times).

To turn a word like "refund" into a stable number, we hash it with MD5
and take the result modulo a fixed vocabulary size. This means:
  - The same word ALWAYS maps to the same index (deterministic).
  - We never need to maintain a growing word->index dictionary file.
  - Two different words COULD theoretically map to the same index
    (a "hash collision"), but with a vocab size of 2^18 (~262k slots)
    this is rare enough not to matter in practice for a RAG system.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from documind_core.vectorstore.qdrant_store import SparseVectorInput

# Size of our "fake vocabulary" — every word gets squeezed into one of
# this many buckets. Bigger = fewer collisions, but no real downside to
# keeping it large since Qdrant's sparse index doesn't pre-allocate memory
# per bucket (it's sparse, after all).
VOCAB_SIZE = 2**18  # 262,144 buckets

# Matches runs of letters/numbers, splitting on everything else (spaces,
# punctuation, etc). This is a very simple tokenizer — good enough for
# BM25-style matching, not meant to be linguistically perfect.
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """
    Lowercase the text and split it into word tokens.

    Example: "The Refund Policy!" -> ["the", "refund", "policy"]
    """
    return _WORD_RE.findall(text.lower())


def _term_to_index(term: str) -> int:
    """
    Map a word to a stable integer index using MD5 hashing.

    Same word in -> same index out, every time, in every process,
    forever — that's what makes this deterministic and idempotent.
    """
    digest = hashlib.md5(term.encode("utf-8")).hexdigest()
    return int(digest, 16) % VOCAB_SIZE


def text_to_sparse_vector(text: str) -> SparseVectorInput:
    """
    Convert a piece of text into a sparse term-frequency vector.

    Parameters
    ----------
    text:
        The chunk text to vectorize.

    Returns
    -------
    SparseVectorInput
        indices = one entry per UNIQUE word in the text (as a hashed index)
        values  = how many times that word appeared (raw count, not IDF —
                  Qdrant applies IDF automatically at search time)

    Example
    -------
        text_to_sparse_vector("the cat sat on the mat")
        -> SparseVectorInput(
               indices=[idx("the"), idx("cat"), idx("sat"), idx("on"), idx("mat")],
               values= [2.0,        1.0,        1.0,        1.0,       1.0]
           )
        ("the" appears twice, everything else appears once)
    """
    tokens = _tokenize(text)

    # Counter tallies how many times each word appears, e.g. {"the": 2, "cat": 1, ...}
    term_counts = Counter(tokens)

    indices: list[int] = []
    values: list[float] = []

    for term, count in term_counts.items():
        indices.append(_term_to_index(term))
        values.append(float(count))

    return SparseVectorInput(indices=indices, values=values)
