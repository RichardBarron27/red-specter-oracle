"""ORACLE query parser — classify and route natural language queries."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("oracle.query.parser")

# Keywords for query classification
COMPONENT_KEYWORDS = {
    "component", "part", "chip", "ic", "mcu", "soc", "fpga", "sensor",
    "connector", "interface", "protocol", "bus", "pin", "pinout",
    "schematic", "wiring", "board", "pcb", "layout", "module",
    "blast radius", "centrality", "critical", "trust chain",
    "connected to", "depends on", "controls", "runs on",
    "manufacturer", "part number", "datasheet",
}

GRAPH_KEYWORDS = {
    "graph", "relationship", "connected", "depends", "trust",
    "blast radius", "centrality", "critical node", "chain",
    "layer", "architecture", "topology", "attack surface",
}


@dataclass
class ParsedQuery:
    """A classified and parsed query."""
    original_text: str
    query_type: str  # DOCUMENT, COMPONENT, HYBRID
    search_terms: list[str]
    intent: str  # describe, compare, find, list, explain, trace


class QueryParser:
    """Parse and classify natural language queries."""

    def parse(self, query_text: str) -> ParsedQuery:
        """Classify and parse a query."""
        text_lower = query_text.lower().strip()

        query_type = self._classify_type(text_lower)
        intent = self._detect_intent(text_lower)
        search_terms = self._extract_search_terms(text_lower)

        parsed = ParsedQuery(
            original_text=query_text,
            query_type=query_type,
            search_terms=search_terms,
            intent=intent,
        )

        logger.debug(f"Parsed query: type={query_type}, intent={intent}, terms={search_terms}")
        return parsed

    def _classify_type(self, text: str) -> str:
        """Classify query as DOCUMENT, COMPONENT, or HYBRID."""
        component_score = sum(1 for kw in COMPONENT_KEYWORDS if kw in text)
        graph_score = sum(1 for kw in GRAPH_KEYWORDS if kw in text)

        # Check for explicit part numbers (strong COMPONENT signal)
        has_part_number = bool(re.search(
            r"\b(STM32|ATmega|PIC\d|ESP32|nRF|LPC|W25Q|LAN87|AMS11)\w*\b",
            text, re.IGNORECASE
        ))

        if has_part_number:
            component_score += 3

        total = component_score + graph_score

        if total == 0:
            return "DOCUMENT"
        elif graph_score > component_score:
            return "COMPONENT"
        elif component_score > 0 and graph_score > 0:
            return "HYBRID"
        elif component_score > 2:
            return "HYBRID"
        else:
            return "DOCUMENT"

    def _detect_intent(self, text: str) -> str:
        """Detect the query intent."""
        if text.startswith(("list", "show", "what are", "enumerate")):
            return "list"
        elif text.startswith(("compare", "difference", "vs", "versus")):
            return "compare"
        elif text.startswith(("find", "search", "where", "locate")):
            return "find"
        elif text.startswith(("explain", "why", "how does", "describe")):
            return "explain"
        elif text.startswith(("trace", "follow", "path", "chain")):
            return "trace"
        elif "?" in text:
            return "explain"
        else:
            return "describe"

    def _extract_search_terms(self, text: str) -> list[str]:
        """Extract key search terms from the query."""
        # Remove common question words
        stop_words = {
            "what", "which", "how", "does", "is", "are", "the", "a", "an",
            "this", "that", "these", "those", "do", "can", "will", "would",
            "should", "of", "in", "on", "to", "for", "with", "from", "by",
            "about", "it", "its", "they", "their", "my", "me", "i", "we",
            "you", "your", "tell", "show", "give", "please", "device",
        }

        words = re.findall(r"\b\w+\b", text.lower())
        terms = [w for w in words if w not in stop_words and len(w) > 2]

        return terms[:10]
