"""ORACLE vector store — ChromaDB wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

logger = logging.getLogger("oracle.vectorstore")


class VectorStore:
    """ChromaDB-backed vector store for document embeddings."""

    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="oracle_documents",
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def count(self) -> int:
        return self._collection.count()

    def add(
        self,
        doc_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document chunk to the store."""
        meta = metadata if metadata else {"_oracle": "true"}
        self._collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )

    def query(
        self,
        embedding: list[float],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query similar documents."""
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        return self._collection.query(**kwargs)

    def delete(self, doc_id: str) -> None:
        """Delete a document chunk."""
        try:
            self._collection.delete(ids=[doc_id])
        except Exception as e:
            logger.warning(f"Delete failed for {doc_id}: {e}")

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_chunks": self.count,
            "persist_dir": str(self.persist_dir),
        }
