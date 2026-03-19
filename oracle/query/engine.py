"""ORACLE query engine — orchestrates parse, retrieve, synthesise, score."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.graph.engine import ComponentGraph
from oracle.query.parser import QueryParser
from oracle.query.retriever import Retriever
from oracle.query.synthesiser import Synthesiser, SynthesisResult
from oracle.query.confidence import WilsonScorer, ConfidenceScore
from oracle.validation.detector import ResponseValidator
from oracle.validation.profiler import ResearcherProfiler
from oracle.validation.audit import AuditTrail

logger = logging.getLogger("oracle.query.engine")


@dataclass
class QueryResponse:
    """Complete query response with all metadata."""
    query_id: str = ""
    query_text: str = ""
    query_type: str = ""
    response_text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: dict[str, Any] = field(default_factory=dict)
    unmatched_claims: list[str] = field(default_factory=list)
    sources_used: int = 0
    response_time_ms: float = 0.0
    model_used: str = ""
    summary: str = ""
    requires_review: bool = False
    validation: dict[str, Any] = field(default_factory=dict)
    validation_status: str = "GREEN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query_text": self.query_text,
            "query_type": self.query_type,
            "response_text": self.response_text,
            "citations": self.citations,
            "confidence": self.confidence,
            "unmatched_claims": self.unmatched_claims,
            "sources_used": self.sources_used,
            "response_time_ms": round(self.response_time_ms, 1),
            "model_used": self.model_used,
            "summary": self.summary,
            "requires_review": self.requires_review,
            "validation": self.validation,
            "validation_status": self.validation_status,
        }


class QueryEngine:
    """Orchestrate the full query pipeline: parse → retrieve → synthesise → score."""

    def __init__(
        self,
        ollama: OllamaClient,
        vector_store: VectorStore,
        db: Database,
        graph: ComponentGraph | None = None,
        crypto=None,
    ):
        self.ollama = ollama
        self.db = db
        self.parser = QueryParser()
        self.retriever = Retriever(ollama, vector_store, db, graph)
        self.synthesiser = Synthesiser(ollama)
        self.scorer = WilsonScorer()
        self.validator = ResponseValidator(db, crypto)
        self.profiler = ResearcherProfiler(db)
        self.audit = AuditTrail(db, crypto)

    def query(
        self,
        session_id: str,
        query_text: str,
        top_k: int = 10,
        context_window: int = 5,
    ) -> QueryResponse:
        """Execute a full query pipeline."""
        start = time.time()

        # 1. Parse query
        parsed = self.parser.parse(query_text)

        # 2. Store query
        query_record = self.db.add_query(session_id, query_text)
        query_id = query_record["query_id"]

        # 3. Get conversation history
        history = self._get_conversation_history(session_id, context_window)

        # 4. Retrieve context
        retrieval = self.retriever.retrieve(parsed, session_id, top_k)

        # 5. Synthesise response
        if not self.ollama.is_available():
            response = QueryResponse(
                query_id=query_id,
                query_text=query_text,
                query_type=parsed.query_type,
                response_text="Ollama is not available. Cannot generate response.",
                requires_review=True,
            )
            self._save_response(query_id, response)
            return response

        synthesis = self.synthesiser.synthesise(
            query_text, retrieval, history
        )

        # 6. Score confidence
        total_claims = self.scorer.count_factual_claims(synthesis.response_text)
        confidence = self.scorer.score_response(
            response_text=synthesis.response_text,
            citations_found=len(synthesis.citations),
            total_claims=total_claims,
            chunks_used=synthesis.context_chunks_used,
            chunks_available=retrieval.total_sources,
            unmatched_claims=len(synthesis.unmatched_claims),
        )

        # 7. Run validation (all 7 M40 subsystems)
        validation = self.validator.validate(
            response_text=synthesis.response_text,
            source_context=retrieval.build_context(),
            source_chunks=retrieval.chunks,
        )

        # Merge validation with confidence scoring
        if validation.status == "RED" and confidence.accuracy > 0.4:
            # Validation caught something confidence didn't
            confidence.requires_review = True

        elapsed_ms = (time.time() - start) * 1000

        # 8. Log to audit trail
        self.audit.log_query(session_id, query_text, query_id)

        # 9. Build response
        response = QueryResponse(
            query_id=query_id,
            query_text=query_text,
            query_type=parsed.query_type,
            response_text=synthesis.response_text,
            citations=[
                {
                    "source_file": c.source_file,
                    "page": c.page,
                    "chunk_id": c.chunk_id,
                    "relevance": round(c.relevance, 3),
                    "snippet": c.text_snippet,
                }
                for c in synthesis.citations
            ],
            confidence=confidence.to_dict(),
            unmatched_claims=synthesis.unmatched_claims,
            sources_used=retrieval.total_sources,
            response_time_ms=elapsed_ms,
            model_used=synthesis.model_used,
            summary=synthesis.summary,
            requires_review=confidence.requires_review or validation.requires_review,
            validation=validation.to_dict(),
            validation_status=validation.status,
        )

        # 10. Update researcher profile
        self.profiler.update_profile(session_id, query_text, synthesis.response_text, parsed.query_type)

        # 11. Log response to audit trail
        self.audit.log_response(query_id, synthesis.summary, validation.status, confidence.overall)
        self.audit.log_validation(query_id, validation.to_dict())

        # 12. Save to database
        self._save_response(query_id, response)

        logger.info(
            f"Query '{query_text[:50]}...' → {parsed.query_type}, "
            f"{len(synthesis.citations)} citations, "
            f"confidence={confidence.overall:.2f}, "
            f"{elapsed_ms:.0f}ms"
        )

        return response

    def _get_conversation_history(
        self, session_id: str, context_window: int
    ) -> list[dict[str, Any]]:
        """Get recent conversation history for context."""
        queries = self.db.list_queries(session_id)
        history = []
        for q in queries[:context_window]:
            history.append({
                "query": q.get("query_text", ""),
                "response": q.get("response_text", ""),
            })
        return list(reversed(history))  # Chronological order

    def _save_response(self, query_id: str, response: QueryResponse) -> None:
        """Save the response to the database."""
        self.db.update_query(
            query_id,
            response_text=response.response_text,
            confidence_score=response.confidence.get("overall", 0),
            sources=json.dumps(response.citations),
            response_time_ms=response.response_time_ms,
            metadata=json.dumps({
                "query_type": response.query_type,
                "model_used": response.model_used,
                "requires_review": response.requires_review,
                "summary": response.summary,
            }),
        )
