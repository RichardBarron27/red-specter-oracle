"""ORACLE retrieval pipeline — fetch relevant chunks and graph data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.graph.engine import ComponentGraph
from oracle.query.parser import ParsedQuery

logger = logging.getLogger("oracle.query.retriever")


@dataclass
class RetrievalResult:
    """Combined retrieval result from documents and graph."""
    chunks: list[dict[str, Any]] = field(default_factory=list)
    graph_nodes: list[dict[str, Any]] = field(default_factory=list)
    graph_edges: list[dict[str, Any]] = field(default_factory=list)
    total_sources: int = 0

    def build_context(self, max_chars: int = 8000) -> str:
        """Build a text context for the LLM from retrieved data."""
        parts = []

        # Document chunks
        if self.chunks:
            parts.append("=== SOURCE DOCUMENTS ===")
            for i, chunk in enumerate(self.chunks):
                source = chunk.get("metadata", {}).get("source_file", "unknown")
                page = chunk.get("metadata", {}).get("page", "")
                page_str = f", p.{page}" if page else ""
                relevance = chunk.get("relevance", 0)
                parts.append(
                    f"[Source: {source}{page_str}] (relevance: {relevance:.2f})\n"
                    f"{chunk.get('text', '')}"
                )

        # Graph data
        if self.graph_nodes:
            parts.append("\n=== COMPONENT GRAPH ===")
            for node in self.graph_nodes:
                parts.append(
                    f"Component: {node.get('name', '?')} "
                    f"(type: {node.get('component_type', '?')}, "
                    f"layer: {node.get('layer', '?')}, "
                    f"part#: {node.get('part_number', 'N/A')}, "
                    f"source: {node.get('source_doc', '?')})"
                )

        if self.graph_edges:
            parts.append("\n=== RELATIONSHIPS ===")
            for edge in self.graph_edges:
                parts.append(
                    f"{edge.get('source_name', '?')} --[{edge.get('relationship_type', '?')}]--> "
                    f"{edge.get('target_name', '?')} "
                    f"(evidence: {edge.get('evidence', 'N/A')})"
                )

        context = "\n".join(parts)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n... [truncated]"

        return context


class Retriever:
    """Retrieve relevant context from documents and component graph."""

    def __init__(
        self,
        ollama: OllamaClient,
        vector_store: VectorStore,
        db: Database,
        graph: ComponentGraph | None = None,
    ):
        self.ollama = ollama
        self.vector_store = vector_store
        self.db = db
        self.graph = graph

    def retrieve(
        self,
        parsed_query: ParsedQuery,
        session_id: str,
        top_k: int = 10,
    ) -> RetrievalResult:
        """Retrieve relevant context for a query."""
        result = RetrievalResult()

        if parsed_query.query_type in ("DOCUMENT", "HYBRID"):
            result.chunks = self._retrieve_chunks(
                parsed_query.original_text, session_id, top_k
            )

        if parsed_query.query_type in ("COMPONENT", "HYBRID"):
            nodes, edges = self._retrieve_graph_data(
                parsed_query, session_id
            )
            result.graph_nodes = nodes
            result.graph_edges = edges

        # If COMPONENT query returned no graph data, fall back to document search
        if parsed_query.query_type == "COMPONENT" and not result.graph_nodes:
            result.chunks = self._retrieve_chunks(
                parsed_query.original_text, session_id, top_k
            )

        result.total_sources = len(result.chunks) + len(result.graph_nodes)
        return result

    def _retrieve_chunks(
        self, query_text: str, session_id: str, top_k: int
    ) -> list[dict[str, Any]]:
        """Retrieve relevant document chunks from ChromaDB."""
        embedding = self.ollama.embed(query_text)
        if not embedding:
            return []

        # Get document IDs for this session
        docs = self.db.list_documents(session_id)
        if not docs:
            return []

        # Query ChromaDB
        results = self.vector_store.query(
            embedding=embedding,
            n_results=top_k,
        )

        # Format results
        formatted = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        session_doc_ids = {d["document_id"] for d in docs}

        for i in range(len(ids)):
            meta = metadatas[i] if i < len(metadatas) else {}
            # Filter to current session's documents
            if meta.get("document_id") not in session_doc_ids:
                continue
            formatted.append({
                "chunk_id": ids[i],
                "text": documents[i] if i < len(documents) else "",
                "metadata": meta,
                "distance": distances[i] if i < len(distances) else 1.0,
                "relevance": max(0, 1 - (distances[i] if i < len(distances) else 1.0)),
            })

        return sorted(formatted, key=lambda x: x["relevance"], reverse=True)

    def _retrieve_graph_data(
        self, parsed_query: ParsedQuery, session_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Retrieve relevant graph nodes and edges."""
        if not self.graph:
            return [], []

        self.graph.build_from_session(session_id)

        components = self.db.list_components(session_id)
        relationships = self.db.list_relationships(session_id)

        if not components:
            return [], []

        # Find components matching search terms
        query_lower = parsed_query.original_text.lower()
        matching_nodes = []
        matching_ids = set()

        for comp in components:
            name_lower = comp["name"].lower()
            type_lower = comp["component_type"].lower()
            part_lower = (comp.get("part_number") or "").lower()

            if (name_lower in query_lower or
                query_lower in name_lower or
                type_lower in query_lower or
                part_lower in query_lower or
                any(term in name_lower or term in type_lower
                    for term in parsed_query.search_terms)):
                matching_nodes.append(comp)
                matching_ids.add(comp["component_id"])

        # If no specific matches, return all components (for broad queries)
        if not matching_nodes and len(components) <= 20:
            matching_nodes = components
            matching_ids = {c["component_id"] for c in components}

        # Get relevant edges
        matching_edges = []
        component_map = {c["component_id"]: c["name"] for c in components}

        for rel in relationships:
            src = rel["source_component"]
            tgt = rel["target_component"]
            if src in matching_ids or tgt in matching_ids:
                matching_edges.append({
                    **rel,
                    "source_name": component_map.get(src, src),
                    "target_name": component_map.get(tgt, tgt),
                })

        return matching_nodes, matching_edges
