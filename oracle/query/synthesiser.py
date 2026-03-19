"""ORACLE LLM synthesis — build prompts, generate responses, assemble citations."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.query.retriever import RetrievalResult

logger = logging.getLogger("oracle.query.synthesiser")

SYSTEM_PROMPT = """You are ORACLE, an offline research assistant for security researchers conducting hardware and software tear-downs.

RULES:
1. Answer ONLY from the provided source material. Do not use your general knowledge.
2. If the answer is not in the sources, say "I cannot find this in the indexed sources."
3. Cite EVERY factual claim with its source document and page number using the format: [Source: filename, p.X]
4. If multiple sources support a claim, cite all of them.
5. Be precise and technical. Security researchers need exact part numbers, interface specifications, and protocol details.
6. If information is ambiguous or sources conflict, state both positions and flag the conflict.
7. Structure your answer clearly with short paragraphs or bullet points."""

CONTEXT_TEMPLATE = """=== RETRIEVED CONTEXT ===
{context}

=== CONVERSATION HISTORY ===
{history}

=== CURRENT QUESTION ===
{query}"""


@dataclass
class Citation:
    """A source citation attached to a response."""
    source_file: str
    page: int | None = None
    chunk_id: str = ""
    relevance: float = 0.0
    text_snippet: str = ""


@dataclass
class SynthesisResult:
    """Result of LLM synthesis with citations."""
    response_text: str
    citations: list[Citation] = field(default_factory=list)
    unmatched_claims: list[str] = field(default_factory=list)
    response_time_ms: float = 0.0
    model_used: str = ""
    context_chunks_used: int = 0
    summary: str = ""


class Synthesiser:
    """Build prompts, generate responses, assemble citations."""

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    def synthesise(
        self,
        query_text: str,
        retrieval: RetrievalResult,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> SynthesisResult:
        """Generate a response with citations from retrieved context."""
        context = retrieval.build_context()

        # Build conversation history string
        history_str = ""
        if conversation_history:
            history_parts = []
            for entry in conversation_history[-5:]:  # Last 5 exchanges
                history_parts.append(f"Q: {entry.get('query', '')}")
                resp = entry.get("response") or ""
                if len(resp) > 500:
                    resp = resp[:500] + "..."
                history_parts.append(f"A: {resp}")
            history_str = "\n".join(history_parts)

        prompt = CONTEXT_TEMPLATE.format(
            context=context,
            history=history_str or "No previous conversation.",
            query=query_text,
        )

        start = time.time()
        result = self.ollama.generate(
            prompt=prompt,
            system=SYSTEM_PROMPT,
        )
        elapsed_ms = (time.time() - start) * 1000

        response_text = result.get("response", "")
        model_used = result.get("model", self.ollama.config.reasoning_model)

        # Extract and match citations
        citations = self._extract_citations(response_text, retrieval)
        unmatched = self._find_unmatched_claims(response_text, citations)

        # Generate summary
        summary = self._generate_summary(query_text, response_text)

        return SynthesisResult(
            response_text=response_text,
            citations=citations,
            unmatched_claims=unmatched,
            response_time_ms=elapsed_ms,
            model_used=model_used,
            context_chunks_used=len(retrieval.chunks),
            summary=summary,
        )

    def _extract_citations(
        self, response: str, retrieval: RetrievalResult
    ) -> list[Citation]:
        """Extract citations from the response and match to source chunks."""
        citations = []
        seen_sources = set()

        # Find explicit citations in [Source: ...] format
        citation_pattern = re.compile(r"\[Source:\s*([^,\]]+)(?:,\s*p\.?\s*(\d+))?\]")
        for match in citation_pattern.finditer(response):
            source_file = match.group(1).strip()
            page = int(match.group(2)) if match.group(2) else None
            key = (source_file, page)
            if key not in seen_sources:
                seen_sources.add(key)
                # Find matching chunk
                chunk_id = ""
                relevance = 0.0
                snippet = ""
                for chunk in retrieval.chunks:
                    meta = chunk.get("metadata", {})
                    chunk_source = meta.get("source_file", "")
                    chunk_page = meta.get("page")
                    if source_file in chunk_source or chunk_source in source_file:
                        if page is None or chunk_page == page:
                            chunk_id = chunk.get("chunk_id", "")
                            relevance = chunk.get("relevance", 0)
                            snippet = chunk.get("text", "")[:200]
                            break

                citations.append(Citation(
                    source_file=source_file,
                    page=page,
                    chunk_id=chunk_id,
                    relevance=relevance,
                    text_snippet=snippet,
                ))

        # If no explicit citations found, infer from chunks used
        if not citations and retrieval.chunks:
            for chunk in retrieval.chunks[:5]:
                meta = chunk.get("metadata", {})
                source = meta.get("source_file", "unknown")
                page = meta.get("page")
                citations.append(Citation(
                    source_file=source,
                    page=page,
                    chunk_id=chunk.get("chunk_id", ""),
                    relevance=chunk.get("relevance", 0),
                    text_snippet=chunk.get("text", "")[:200],
                ))

        return citations

    def _find_unmatched_claims(
        self, response: str, citations: list[Citation]
    ) -> list[str]:
        """Find factual claims not matched to any citation."""
        unmatched = []

        # Split response into sentences
        sentences = re.split(r"(?<=[.!?])\s+", response)
        cited_sources = {c.source_file for c in citations}

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 20:
                continue

            # Check if sentence has a citation
            has_citation = bool(re.search(r"\[Source:", sentence))

            # Check if it's a factual claim (contains numbers, part names, specs)
            is_factual = bool(re.search(
                r"\b(\d+\s*(MHz|KB|MB|GB|kHz|V|mA|pin|bit)|STM32|ARM|Cortex|SPI|I2C|UART)\b",
                sentence, re.IGNORECASE
            ))

            if is_factual and not has_citation:
                unmatched.append(sentence[:200])

        return unmatched[:10]

    def _generate_summary(self, query: str, response: str) -> str:
        """Generate a one-line summary of the exchange."""
        if len(response) < 100:
            return response
        # Take first sentence
        first_sentence = response.split(".")[0].strip()
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:150] + "..."
        return first_sentence
