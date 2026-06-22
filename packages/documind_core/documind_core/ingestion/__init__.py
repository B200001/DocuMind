"""Document ingestion pipeline."""

from documind_core.ingestion.pipeline import ingest_document, IngestResult, IngestionError

__all__ = ["ingest_document", "IngestResult", "IngestionError"]
