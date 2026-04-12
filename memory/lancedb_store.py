"""
LanceDB-backed vector store for ASHI wiki and knowledge embeddings.
Embedded, zero-copy, multimodal-ready.
Falls back to hash-based embeddings when sentence-transformers unavailable.
"""
import hashlib
import struct
import lancedb
import pyarrow as pa
from typing import Optional

EMBED_DIM = 64  # compact for hash embeddings; upgrade to 384 when sentence-transformers available


def _hash_embed(text: str) -> list[float]:
    """
    Deterministic hash-based embedding, always finite in [-1, 1].
    Uses unsigned int normalization instead of raw float bit-casting to avoid NaN.
    Not semantic — upgrade to sentence-transformers when available.
    """
    result = []
    for i in range(EMBED_DIM):
        digest = hashlib.sha256(f"{i}:{text}".encode()).digest()
        uint_val = struct.unpack(">I", digest[:4])[0]
        normalized = (uint_val / (2**32 - 1)) * 2.0 - 1.0  # [-1, 1]
        result.append(normalized)
    return result


def _get_embedder() -> tuple:
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        dim = 384

        def embed(text: str) -> list[float]:
            return model.encode(text).tolist()

        return embed, dim
    except ImportError:
        return _hash_embed, EMBED_DIM


_embedder, _dim = _get_embedder()


class VectorStore:
    def __init__(self, db_path: str, table_name: str = "wiki"):
        self.db = lancedb.connect(db_path)
        self.table_name = table_name
        self._schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("type", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), _dim)),
            ]
        )
        existing = self.db.list_tables()
        # list_tables() returns a paginated response object with a .tables attribute
        existing_names: list[str] = existing.tables
        if table_name not in existing_names:
            self.db.create_table(table_name, schema=self._schema)
        self.table = self.db.open_table(table_name)

    def add(self, id: str, text: str, metadata: Optional[dict] = None) -> None:
        vector = _embedder(text)
        row = {
            "id": id,
            "text": text,
            "type": (metadata or {}).get("type", "general"),
            "vector": vector,
        }
        self.table.add([row])

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.table.count_rows() == 0:
            return []
        vector = _embedder(query)
        results = self.table.search(vector).limit(top_k).to_list()
        return [
            {"id": r["id"], "text": r["text"], "score": r.get("_distance", 0.0)}
            for r in results
        ]
