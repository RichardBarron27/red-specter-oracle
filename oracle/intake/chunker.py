"""ORACLE chunking engine — split text into overlapping chunks with source references."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("oracle.intake.chunker")


@dataclass
class Chunk:
    """A single chunk of text with source metadata."""
    chunk_id: str
    text: str
    chunk_index: int
    source_file: str
    page: int | None = None
    section: str | None = None
    content_type: str = "text"  # text, code, table, ocr, image_description, binary_strings
    language: str = "en"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        """Rough token estimate (~4 chars per token)."""
        return len(self.text) // 4


class ChunkingEngine:
    """Split text into overlapping chunks preserving source references."""

    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        Args:
            chunk_size: Target chunk size in tokens (~4 chars per token).
            overlap: Overlap between chunks in tokens.
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._char_size = chunk_size * 4
        self._char_overlap = overlap * 4

    def chunk_text(
        self,
        text: str,
        source_file: str,
        page: int | None = None,
        section: str | None = None,
        content_type: str = "text",
        language: str = "en",
        confidence: float = 1.0,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Chunk a text block into overlapping segments."""
        if not text or not text.strip():
            return []

        text = text.strip()

        # If text is short enough, return as single chunk
        if len(text) <= self._char_size:
            return [Chunk(
                chunk_id=str(uuid.uuid4()),
                text=text,
                chunk_index=0,
                source_file=source_file,
                page=page,
                section=section,
                content_type=content_type,
                language=language,
                confidence=confidence,
                metadata=extra_metadata or {},
            )]

        # Split on paragraph boundaries first
        paragraphs = self._split_paragraphs(text)

        chunks = []
        current_text = ""
        chunk_index = 0

        for para in paragraphs:
            # If adding this paragraph would exceed chunk size
            if len(current_text) + len(para) > self._char_size and current_text:
                chunks.append(self._make_chunk(
                    current_text, chunk_index, source_file, page,
                    section, content_type, language, confidence, extra_metadata,
                ))
                chunk_index += 1

                # Keep overlap from end of current chunk
                if self._char_overlap > 0:
                    overlap_text = current_text[-self._char_overlap:]
                    current_text = overlap_text + "\n\n" + para
                else:
                    current_text = para
            else:
                current_text = (current_text + "\n\n" + para).strip() if current_text else para

        # Final chunk
        if current_text.strip():
            chunks.append(self._make_chunk(
                current_text, chunk_index, source_file, page,
                section, content_type, language, confidence, extra_metadata,
            ))

        logger.debug(f"Chunked {source_file}: {len(chunks)} chunks from {len(text)} chars")
        return chunks

    def chunk_code_units(
        self,
        units: list[Any],
        source_file: str,
        language: str = "unknown",
    ) -> list[Chunk]:
        """Chunk code by logical units (functions/classes)."""
        chunks = []

        for i, unit in enumerate(units):
            text = unit.content if hasattr(unit, "content") else str(unit)
            name = unit.name if hasattr(unit, "name") else f"unit_{i}"
            unit_type = unit.unit_type if hasattr(unit, "unit_type") else "code"
            start_line = unit.start_line if hasattr(unit, "start_line") else None

            # If unit is too large, sub-chunk it
            if len(text) > self._char_size:
                sub_chunks = self.chunk_text(
                    text, source_file,
                    section=f"{unit_type}:{name}",
                    content_type="code",
                    language=language,
                    extra_metadata={"unit_name": name, "unit_type": unit_type,
                                     "start_line": start_line},
                )
                chunks.extend(sub_chunks)
            else:
                chunks.append(Chunk(
                    chunk_id=str(uuid.uuid4()),
                    text=text,
                    chunk_index=i,
                    source_file=source_file,
                    section=f"{unit_type}:{name}",
                    content_type="code",
                    language=language,
                    metadata={"unit_name": name, "unit_type": unit_type,
                              "start_line": start_line},
                ))

        return chunks

    def chunk_table(
        self,
        rows: list[list[str]],
        source_file: str,
        page: int | None = None,
        table_index: int = 0,
    ) -> list[Chunk]:
        """Convert a table to text chunks."""
        if not rows:
            return []

        # Convert table to readable text
        lines = []
        for row in rows:
            lines.append(" | ".join(str(cell) for cell in row))
        table_text = "\n".join(lines)

        return self.chunk_text(
            table_text, source_file, page=page,
            section=f"table_{table_index}",
            content_type="table",
        )

    def chunk_strings(
        self,
        strings: list[str],
        source_file: str,
    ) -> list[Chunk]:
        """Chunk extracted binary strings."""
        if not strings:
            return []

        # Group strings into chunks
        text = "\n".join(strings)
        return self.chunk_text(
            text, source_file,
            content_type="binary_strings",
            extra_metadata={"string_count": len(strings)},
        )

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text on paragraph boundaries."""
        paragraphs = re.split(r"\n\s*\n", text)
        result = []
        for p in paragraphs:
            p = p.strip()
            if p:
                # If a single paragraph is still too long, split on sentences
                if len(p) > self._char_size:
                    sentences = re.split(r"(?<=[.!?])\s+", p)
                    result.extend(s for s in sentences if s.strip())
                else:
                    result.append(p)
        return result

    def _make_chunk(
        self,
        text: str,
        chunk_index: int,
        source_file: str,
        page: int | None,
        section: str | None,
        content_type: str,
        language: str,
        confidence: float,
        extra_metadata: dict[str, Any] | None,
    ) -> Chunk:
        return Chunk(
            chunk_id=str(uuid.uuid4()),
            text=text.strip(),
            chunk_index=chunk_index,
            source_file=source_file,
            page=page,
            section=section,
            content_type=content_type,
            language=language,
            confidence=confidence,
            metadata=extra_metadata or {},
        )
