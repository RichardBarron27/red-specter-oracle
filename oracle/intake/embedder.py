"""ORACLE embedding pipeline — embed chunks and store in ChromaDB."""

from __future__ import annotations

import logging
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.intake.chunker import Chunk

logger = logging.getLogger("oracle.intake.embedder")


class EmbeddingPipeline:
    """Embed text chunks and store in ChromaDB with full metadata."""

    def __init__(self, ollama: OllamaClient, vector_store: VectorStore):
        self.ollama = ollama
        self.vector_store = vector_store

    BATCH_SIZE = 8

    def embed_and_store(self, chunks: list[Chunk], document_id: str) -> int:
        """Embed a list of chunks and store them in the vector store.

        Sends chunks to Ollama in batches to minimise HTTP round-trips.
        Returns the number of chunks successfully stored.
        """
        stored = 0
        active = [c for c in chunks if c.text.strip()]

        for batch_start in range(0, len(active), self.BATCH_SIZE):
            batch = active[batch_start: batch_start + self.BATCH_SIZE]
            texts = [c.text for c in batch]

            embeddings = self.ollama.embed_batch(texts)
            if len(embeddings) != len(batch):
                logger.warning(
                    f"Batch embed returned {len(embeddings)} vectors for {len(batch)} chunks — skipping batch"
                )
                continue

            for chunk, embedding in zip(batch, embeddings):
                if not embedding:
                    logger.warning(f"Empty embedding for chunk {chunk.chunk_id}")
                    continue

                metadata: dict[str, Any] = {
                    "document_id": document_id,
                    "source_file": chunk.source_file,
                    "chunk_index": chunk.chunk_index,
                    "content_type": chunk.content_type,
                    "language": chunk.language,
                    "confidence": chunk.confidence,
                    "token_estimate": chunk.token_estimate,
                }

                if chunk.page is not None:
                    metadata["page"] = chunk.page
                if chunk.section:
                    metadata["section"] = chunk.section

                for k, v in chunk.metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        metadata[k] = v

                self.vector_store.add(
                    doc_id=chunk.chunk_id,
                    text=chunk.text,
                    embedding=embedding,
                    metadata=metadata,
                )
                stored += 1

        logger.info(f"Embedded and stored {stored}/{len(chunks)} chunks for document {document_id}")
        return stored

    def search(
        self,
        query: str,
        n_results: int = 5,
        content_type: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar chunks using a text query.

        Returns list of results with text, metadata, and distance.
        """
        # Embed the query
        query_embedding = self.ollama.embed(query)
        if not query_embedding:
            logger.error("Failed to embed query")
            return []

        # Build filter
        where: dict[str, Any] | None = None
        if content_type or document_id:
            conditions = []
            if content_type:
                conditions.append({"content_type": content_type})
            if document_id:
                conditions.append({"document_id": document_id})

            if len(conditions) == 1:
                where = conditions[0]
            else:
                where = {"$and": conditions}

        # Query vector store
        results = self.vector_store.query(
            embedding=query_embedding,
            n_results=n_results,
            where=where,
        )

        # Format results
        formatted = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i in range(len(ids)):
            formatted.append({
                "chunk_id": ids[i],
                "text": documents[i],
                "metadata": metadatas[i],
                "distance": distances[i],
                "relevance": max(0, 1 - distances[i]),
            })

        return formatted

    def get_stats(self) -> dict[str, Any]:
        """Get embedding pipeline statistics."""
        return {
            "vector_store": self.vector_store.get_stats(),
        }
