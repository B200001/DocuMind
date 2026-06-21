"""
QdrantStore — wraps qdrant-client to store and retrieve document chunks
using two named vectors per point:

    "dense"  — 768-dim cosine-similarity embedding (e.g. nomic-embed-text)
    "sparse" — BM25-style sparse vector (term-index -> weight), with
               Qdrant's IDF modifier applied server-side at query time

Raw chunk text and metadata are stored directly in the point payload, so
retrieval never needs a join back to the relational DB.

Usage
-----
    from documind_core.vectorstore.qdrant_store import QdrantStore

    store = QdrantStore()
    store.ensure_collection()

    store.upsert_chunks(chunks, dense=dense_vectors, sparse=sparse_vectors)

    hits = store.search_dense(query_vector, k=8)
    hits = store.search_sparse(query_sparse_vector, k=8, doc_id="abc-123")

    store.delete_by_doc("abc-123")
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from qdrant_client import QdrantClient, models

from documind_core.config import get_settings

logger = logging.getLogger(__name__)

# nomic-embed-text produces 768-dim dense vectors.
DEFAULT_DENSE_DIM = 768
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# Fixed, arbitrary namespace used to deterministically derive Qdrant point
# UUIDs from our string chunk IDs (Qdrant point IDs must be unsigned ints
# or valid UUIDs, not arbitrary strings like "doc_id:7").
_POINT_ID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _point_id_for(chunk_id: str) -> str:
    """Deterministically derive a stable UUID from a chunk_id string."""
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, chunk_id))


# ─── Input shapes ──────────────────────────────────────────────────────────────

class ChunkLike(Protocol):
    """
    Minimal shape QdrantStore needs from a chunk object.

    Matches documind_core.chunking.chunker.ChunkRecord and
    documind_core.models.Chunk field names, so either can be passed
    directly to upsert_chunks() without adaptation.
    """

    id: str
    doc_id: str
    text: str
    page: Optional[int]
    section: Optional[str]


@dataclass(frozen=True)
class SparseVectorInput:
    """A BM25-style sparse vector: parallel arrays of term indices and weights."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class SearchHit:
    """One search result, with payload already unpacked for convenience."""

    point_id: str
    score: float
    doc_id: str
    chunk_id: str
    page: Optional[int]
    section: Optional[str]
    text: str


# ─── Exceptions ────────────────────────────────────────────────────────────────

class QdrantStoreError(RuntimeError):
    """Raised for configuration or usage errors specific to QdrantStore."""


# ─── Store ─────────────────────────────────────────────────────────────────────

class QdrantStore:
    """
    Wraps a qdrant-client collection with two named vectors (dense + sparse)
    and payload-resident chunk text/metadata.
    """

    def __init__(
        self,
        url: str | None = None,
        collection_name: str | None = None,
        dense_dim: int = DEFAULT_DENSE_DIM,
        client: QdrantClient | None = None,
    ) -> None:
        """
        Parameters
        ----------
        url, collection_name, dense_dim:
            Standard configuration; defaults come from get_settings().
        client:
            Optional pre-built QdrantClient — primarily for tests, where
            an in-memory client (QdrantClient(location=":memory:")) can
            be injected instead of connecting to a real server.
        """
        settings = get_settings()
        self.url = url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection
        self.dense_dim = dense_dim
        self._client = client or QdrantClient(url=self.url)

    # ─── Collection lifecycle ────────────────────────────────────────────────

    def ensure_collection(self) -> None:
        """
        Create the collection with both named vectors if it doesn't exist.
        If the collection already exists but its "dense" vector size
        doesn't match `self.dense_dim`, the collection is dropped and
        recreated — Qdrant collections can't change vector dimensionality
        in place, and silently mismatched dims would corrupt similarity
        search. This is a destructive operation; callers that change
        embedding models should treat this as a full re-ingest trigger.
        """
        exists = self._client.collection_exists(self.collection_name)

        if exists:
            info = self._client.get_collection(self.collection_name)
            existing_dense = info.config.params.vectors

            current_dim: Optional[int] = None
            if isinstance(existing_dense, dict) and DENSE_VECTOR_NAME in existing_dense:
                current_dim = existing_dense[DENSE_VECTOR_NAME].size

            if current_dim == self.dense_dim:
                logger.info(
                    "Collection '%s' already exists with matching dense dim (%d).",
                    self.collection_name, self.dense_dim,
                )
                return

            logger.warning(
                "Collection '%s' exists with dense dim=%s but configured dim=%d. "
                "Recreating collection (this deletes all existing vectors).",
                self.collection_name, current_dim, self.dense_dim,
            )
            self._client.delete_collection(self.collection_name)

        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=self.dense_dim,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )
        logger.info(
            "Created collection '%s' (dense dim=%d, cosine; sparse with IDF).",
            self.collection_name, self.dense_dim,
        )

    # ─── Writes ────────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        chunks: list[ChunkLike],
        dense: list[list[float]],
        sparse: list[SparseVectorInput],
    ) -> None:
        """
        Upsert a batch of chunks with their dense and sparse vectors.

        Parameters
        ----------
        chunks:
            Chunk-like objects (id, doc_id, text, page, section). Order
            must align with `dense` and `sparse`.
        dense:
            One 768-dim (or `self.dense_dim`) embedding per chunk, same
            order as `chunks`.
        sparse:
            One SparseVectorInput per chunk, same order as `chunks`.

        Raises
        ------
        QdrantStoreError
            If `chunks`, `dense`, and `sparse` have mismatched lengths,
            or if any dense vector has the wrong dimensionality.

        Notes
        -----
        Point IDs are deterministically derived from each chunk's `id`
        (via uuid5), so re-ingesting the same chunk_id always updates
        the same point rather than creating a duplicate — this is what
        makes re-ingestion idempotent end-to-end, matching the chunker's
        deterministic chunk IDs.
        """
        if not chunks:
            return

        if not (len(chunks) == len(dense) == len(sparse)):
            raise QdrantStoreError(
                f"chunks ({len(chunks)}), dense ({len(dense)}), and sparse "
                f"({len(sparse)}) must all be the same length."
            )

        points: list[models.PointStruct] = []
        for chunk, dense_vec, sparse_vec in zip(chunks, dense, sparse):
            if len(dense_vec) != self.dense_dim:
                raise QdrantStoreError(
                    f"Chunk '{chunk.id}' has a {len(dense_vec)}-dim dense vector, "
                    f"expected {self.dense_dim}-dim."
                )

            points.append(
                models.PointStruct(
                    id=_point_id_for(chunk.id),
                    vector={
                        DENSE_VECTOR_NAME: dense_vec,
                        SPARSE_VECTOR_NAME: models.SparseVector(
                            indices=sparse_vec.indices,
                            values=sparse_vec.values,
                        ),
                    },
                    payload={
                        "doc_id": chunk.doc_id,
                        "chunk_id": chunk.id,
                        "page": chunk.page,
                        "section": chunk.section,
                        "text": chunk.text,
                    },
                )
            )

        self._client.upsert(collection_name=self.collection_name, points=points)
        logger.info("Upserted %d chunk(s) into '%s'.", len(points), self.collection_name)

    # ─── Reads ─────────────────────────────────────────────────────────────────

    def search_dense(
        self,
        vector: list[float],
        k: int = 8,
        filter: Optional[models.Filter] = None,
        doc_id: Optional[str] = None,
    ) -> list[SearchHit]:
        """
        Dense (cosine) similarity search.

        Parameters
        ----------
        vector:
            Query embedding, same dimensionality as `self.dense_dim`.
        k:
            Number of results to return.
        filter:
            Optional pre-built qdrant_client.models.Filter for advanced
            filtering. If provided, `doc_id` is ignored.
        doc_id:
            Convenience shortcut — filters results to a single document
            without needing to build a Filter manually. Ignored if
            `filter` is also provided.

        Returns
        -------
        list[SearchHit]
            Results ordered by descending similarity score, with payload
            fields already unpacked.
        """
        effective_filter = filter or self._doc_id_filter(doc_id)

        response = self._client.query_points(
            collection_name=self.collection_name,
            query=vector,
            using=DENSE_VECTOR_NAME,
            query_filter=effective_filter,
            limit=k,
            with_payload=True,
        )
        return [self._to_hit(p) for p in response.points]

    def search_sparse(
        self,
        sparse: SparseVectorInput,
        k: int = 8,
        filter: Optional[models.Filter] = None,
        doc_id: Optional[str] = None,
    ) -> list[SearchHit]:
        """
        Sparse (BM25-style) search using the IDF-modified sparse index.

        Parameters
        ----------
        sparse:
            Query sparse vector (term indices + raw term weights/counts;
            Qdrant applies IDF server-side since the collection's sparse
            vector was configured with Modifier.IDF).
        k:
            Number of results to return.
        filter:
            Optional pre-built Filter. If provided, `doc_id` is ignored.
        doc_id:
            Convenience shortcut to filter to a single document.

        Returns
        -------
        list[SearchHit]
            Results ordered by descending sparse score.
        """
        effective_filter = filter or self._doc_id_filter(doc_id)

        response = self._client.query_points(
            collection_name=self.collection_name,
            query=models.SparseVector(indices=sparse.indices, values=sparse.values),
            using=SPARSE_VECTOR_NAME,
            query_filter=effective_filter,
            limit=k,
            with_payload=True,
        )
        return [self._to_hit(p) for p in response.points]

    # ─── Deletes ───────────────────────────────────────────────────────────────

    def delete_by_doc(self, doc_id: str) -> None:
        """
        Delete all chunks belonging to a document.

        Parameters
        ----------
        doc_id:
            The document whose chunks should be removed. Typically called
            before re-ingesting an updated document, or when a document
            is deleted from the source library.
        """
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=self._doc_id_filter(doc_id),
            ),
        )
        logger.info("Deleted all chunks for doc_id='%s' from '%s'.", doc_id, self.collection_name)

    # ─── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _doc_id_filter(doc_id: Optional[str]) -> Optional[models.Filter]:
        if doc_id is None:
            return None
        return models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        )

    @staticmethod
    def _to_hit(point: Any) -> SearchHit:
        payload = point.payload or {}
        return SearchHit(
            point_id=str(point.id),
            score=point.score,
            doc_id=payload.get("doc_id", ""),
            chunk_id=payload.get("chunk_id", ""),
            page=payload.get("page"),
            section=payload.get("section"),
            text=payload.get("text", ""),
        )
