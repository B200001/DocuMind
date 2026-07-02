from documind_core.vectorstore.qdrant_store import QdrantStore, SparseVectorInput
from dataclasses import dataclass
from typing import Optional

@dataclass
class FakeChunk:
    id: str; doc_id: str; text: str; page: Optional[int]; section: Optional[str]

store = QdrantStore()
store.ensure_collection()

chunks = [FakeChunk(id='doc1:0', doc_id='doc1', text='hello world', page=1, section='Intro')]
dense = [[0.1]*768]
sparse = [SparseVectorInput(indices=[1,2], values=[1.0,2.0])]
store.upsert_chunks(chunks, dense=dense, sparse=sparse)

hits = store.search_dense(dense[0], k=1)
print(hits)