"""ORACLE component extractor — extract named entities from indexed documents."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database

logger = logging.getLogger("oracle.graph.extractor")

EXTRACTION_PROMPT = """You are a hardware security researcher analysing technical documents.

Extract ALL components, parts, and technologies mentioned in this text.

For EACH component found, output a JSON object with these fields:
- name: component name (e.g. "STM32F407VGT6", "USB Type-C connector")
- type: one of: mcu, soc, fpga, memory, sensor, connector, ic, passive, power, interface, protocol, firmware, os, driver, software, library, bus, other
- part_number: exact part number if mentioned (e.g. "STM32F407VGT6"), or null
- manufacturer: manufacturer if known (e.g. "STMicroelectronics"), or null
- version: version/revision if mentioned, or null
- layer: one of: hardware, firmware, os, application, protocol

Output ONLY a JSON array of objects. No explanation. No markdown.
If no components are found, output an empty array: []

TEXT:
{text}"""

RELATIONSHIP_PROMPT = """You are a hardware security researcher mapping component relationships.

Given these components already identified:
{components}

And this text from a technical document:
{text}

Identify relationships between components. For each relationship, output a JSON object:
- source: name of source component (must match a component above)
- target: name of target component (must match a component above)
- type: one of: CONNECTS_TO, DEPENDS_ON, CONTROLS, COMMUNICATES_VIA, CONTAINS, RUNS_ON
- evidence: brief quote or description from the text that supports this relationship

Output ONLY a JSON array. No explanation. No markdown.
If no relationships are found, output: []

TEXT:
{text}"""


class ComponentExtractor:
    """Extract components and relationships from indexed documents using LLM."""

    def __init__(self, ollama: OllamaClient, vector_store: VectorStore, db: Database):
        self.ollama = ollama
        self.vector_store = vector_store
        self.db = db

    def extract_components(
        self,
        session_id: str,
        use_llm: bool = True,
        max_chunks: int = 50,
    ) -> list[dict[str, Any]]:
        """Extract components from all indexed chunks in a session."""
        # Get all chunks from ChromaDB for this session
        chunks = self._get_session_chunks(session_id, max_chunks)
        if not chunks:
            logger.warning(f"No chunks found for session {session_id}")
            return []

        all_components = []

        for chunk in chunks:
            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            source_doc = metadata.get("source_file", "unknown")
            page = metadata.get("page")

            if use_llm and self.ollama.is_available():
                extracted = self._extract_with_llm(text)
            else:
                extracted = self._extract_with_regex(text)

            for comp in extracted:
                comp["source_doc"] = source_doc
                comp["source_page"] = page
                # Deduplicate by name within session
                existing = self.db.find_component_by_name(session_id, comp["name"])
                if not existing:
                    stored = self.db.add_component(
                        session_id=session_id,
                        name=comp["name"],
                        component_type=comp.get("type", "other"),
                        part_number=comp.get("part_number"),
                        manufacturer=comp.get("manufacturer"),
                        version=comp.get("version"),
                        layer=comp.get("layer", "hardware"),
                        source_doc=source_doc,
                        source_page=page,
                        confidence=comp.get("confidence", 0.7),
                    )
                    all_components.append(stored)

        logger.info(f"Extracted {len(all_components)} components for session {session_id}")
        return all_components

    def extract_relationships(
        self,
        session_id: str,
        max_chunks: int = 50,
    ) -> list[dict[str, Any]]:
        """Extract relationships between existing components."""
        components = self.db.list_components(session_id)
        if len(components) < 2:
            return []

        component_names = [c["name"] for c in components]
        component_map = {c["name"]: c["component_id"] for c in components}
        chunks = self._get_session_chunks(session_id, max_chunks)

        all_relationships = []

        for chunk in chunks:
            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            source_doc = metadata.get("source_file", "unknown")

            if self.ollama.is_available():
                rels = self._extract_relationships_with_llm(text, component_names)
            else:
                rels = self._extract_relationships_with_regex(text, component_names)

            for rel in rels:
                source_id = component_map.get(rel.get("source", ""))
                target_id = component_map.get(rel.get("target", ""))
                if source_id and target_id and source_id != target_id:
                    stored = self.db.add_relationship(
                        session_id=session_id,
                        source_component=source_id,
                        target_component=target_id,
                        relationship_type=rel.get("type", "CONNECTS_TO"),
                        evidence=rel.get("evidence", ""),
                        source_doc=source_doc,
                        confidence=0.7,
                    )
                    all_relationships.append(stored)

        logger.info(f"Extracted {len(all_relationships)} relationships for session {session_id}")
        return all_relationships

    def _get_session_chunks(self, session_id: str, max_chunks: int) -> list[dict[str, Any]]:
        """Get all chunks for a session from ChromaDB."""
        docs = self.db.list_documents(session_id)
        if not docs:
            return []

        all_chunks = []
        for doc in docs:
            doc_id = doc["document_id"]
            try:
                results = self.vector_store._collection.get(
                    where={"document_id": doc_id},
                    include=["documents", "metadatas"],
                    limit=max_chunks,
                )
                if results and results.get("ids"):
                    for i, chunk_id in enumerate(results["ids"]):
                        all_chunks.append({
                            "chunk_id": chunk_id,
                            "text": results["documents"][i] if results.get("documents") else "",
                            "metadata": results["metadatas"][i] if results.get("metadatas") else {},
                        })
            except Exception as e:
                logger.warning(f"Failed to get chunks for document {doc_id}: {e}")

        return all_chunks[:max_chunks]

    def _extract_with_llm(self, text: str) -> list[dict[str, Any]]:
        """Extract components using LLM."""
        if not text.strip() or len(text) < 20:
            return []

        prompt = EXTRACTION_PROMPT.format(text=text[:3000])
        result = self.ollama.generate(prompt)
        response = result.get("response", "")

        return self._parse_json_response(response)

    def _extract_relationships_with_llm(
        self, text: str, component_names: list[str]
    ) -> list[dict[str, Any]]:
        """Extract relationships using LLM."""
        if not text.strip() or len(text) < 20:
            return []

        # Only process if text mentions at least 2 known components
        mentioned = [n for n in component_names if n.lower() in text.lower()]
        if len(mentioned) < 2:
            return []

        prompt = RELATIONSHIP_PROMPT.format(
            components=", ".join(mentioned),
            text=text[:3000],
        )
        result = self.ollama.generate(prompt)
        response = result.get("response", "")

        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> list[dict[str, Any]]:
        """Parse JSON array from LLM response, handling common issues."""
        if not response:
            return []

        # Try to find JSON array in the response
        response = response.strip()

        # Remove markdown code blocks
        if "```" in response:
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
            if match:
                response = match.group(1).strip()

        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            elif isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            # Try to find array within text
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, list):
                        return [item for item in parsed if isinstance(item, dict)]
                except json.JSONDecodeError:
                    pass

        return []

    def _extract_with_regex(self, text: str) -> list[dict[str, Any]]:
        """Fallback extraction using regex patterns (no LLM)."""
        components = []

        # Part number patterns
        patterns = {
            "mcu": re.compile(r"\b(STM32\w+|ATmega\w+|PIC\d+\w+|ESP32\w*|nRF\d+\w+|LPC\d+\w+)\b", re.IGNORECASE),
            "ic": re.compile(r"\b([A-Z]{2,4}\d{3,}[A-Z]*(?:[-/]\w+)?)\b"),
            "protocol": re.compile(r"\b(SPI|I2C|UART|JTAG|SWD|USB|CAN|Ethernet|RS-?232|RS-?485|MODBUS|BLE|WiFi|Bluetooth)\b", re.IGNORECASE),
            "interface": re.compile(r"\b(GPIO|ADC|DAC|PWM|DMA|SDIO|FSMC|FMC|DCMI)\b", re.IGNORECASE),
        }

        seen = set()
        for comp_type, pattern in patterns.items():
            for match in pattern.finditer(text):
                name = match.group(1)
                if name not in seen and len(name) > 2:
                    seen.add(name)
                    components.append({
                        "name": name,
                        "type": comp_type,
                        "part_number": name if comp_type in ("mcu", "ic") else None,
                        "manufacturer": None,
                        "version": None,
                        "layer": "hardware" if comp_type in ("mcu", "ic") else "protocol",
                        "confidence": 0.6,
                    })

        return components

    def _extract_relationships_with_regex(
        self, text: str, component_names: list[str]
    ) -> list[dict[str, Any]]:
        """Fallback relationship extraction using co-occurrence."""
        relationships = []
        text_lower = text.lower()

        mentioned = [n for n in component_names if n.lower() in text_lower]
        # Create CONNECTS_TO for any two components mentioned in the same chunk
        for i, src in enumerate(mentioned):
            for tgt in mentioned[i + 1:]:
                relationships.append({
                    "source": src,
                    "target": tgt,
                    "type": "CONNECTS_TO",
                    "evidence": "Co-occurrence in same text block",
                })

        return relationships
