"""ORACLE ingestion engine — orchestrates parsing, chunking, embedding for all file types."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.chunker import ChunkingEngine
from oracle.intake.embedder import EmbeddingPipeline
from oracle.intake.parsers.pdf_parser import PDFParser
from oracle.intake.parsers.image_handler import ImageHandler
from oracle.intake.parsers.code_parser import CodeParser
from oracle.intake.parsers.binary_handler import BinaryHandler
from oracle.intake.parsers.ocr_handler import OCRHandler

logger = logging.getLogger("oracle.intake.engine")


class IngestionEngine:
    """Orchestrate document parsing, chunking, and embedding."""

    def __init__(
        self,
        ollama: OllamaClient,
        vector_store: VectorStore,
        db: Database,
        image_output_dir: Path | None = None,
    ):
        self.ollama = ollama
        self.db = db
        self.chunker = ChunkingEngine()
        self.embedder = EmbeddingPipeline(ollama, vector_store)
        self.pdf_parser = PDFParser(image_output_dir=image_output_dir)
        self.image_handler = ImageHandler(ollama=ollama)
        self.code_parser = CodeParser()
        self.binary_handler = BinaryHandler()
        self.ocr_handler = OCRHandler()

    def ingest_document(self, document_id: str) -> dict[str, Any]:
        """Ingest a document by ID — parse, chunk, embed, store."""
        doc = self.db.get_document(document_id)
        if not doc:
            raise ValueError(f"Document not found: {document_id}")

        file_path = Path(doc["file_path"])
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_type = doc["file_type"]
        filename = doc["filename"]

        logger.info(f"Ingesting {filename} ({file_type})")
        self.db.update_document(document_id, ingestion_status="processing")

        try:
            if file_type == "pdf":
                result = self._ingest_pdf(file_path, document_id)
            elif file_type == "image":
                result = self._ingest_image(file_path, filename, document_id)
            elif file_type == "code":
                result = self._ingest_code(file_path, document_id)
            elif file_type == "binary":
                result = self._ingest_binary(file_path, document_id)
            elif file_type in ("text", "structured"):
                result = self._ingest_text(file_path, document_id)
            else:
                result = self._ingest_text(file_path, document_id)

            self.db.update_document(document_id, ingestion_status="indexed")
            logger.info(f"Ingestion complete for {filename}: {result.get('chunks_stored', 0)} chunks")
            return result

        except Exception as e:
            logger.error(f"Ingestion failed for {filename}: {e}")
            self.db.update_document(document_id, ingestion_status="failed")
            raise

    def _ingest_pdf(self, file_path: Path, document_id: str) -> dict[str, Any]:
        """Parse and ingest a PDF."""
        parsed = self.pdf_parser.parse(file_path)
        all_chunks = []

        # Chunk text from each page
        for page in parsed.pages:
            if page.text.strip():
                chunks = self.chunker.chunk_text(
                    page.text,
                    source_file=parsed.filename,
                    page=page.page_number,
                    content_type="text",
                )
                all_chunks.extend(chunks)

            # Chunk tables
            for t_idx, table in enumerate(page.tables):
                table_chunks = self.chunker.chunk_table(
                    table, source_file=parsed.filename,
                    page=page.page_number, table_index=t_idx,
                )
                all_chunks.extend(table_chunks)

            # Handle embedded images — characterise via vision model if available
            for img in page.images:
                if "data" in img and self.ollama.has_model(self.ollama.config.vision_model):
                    img_result = self.image_handler.characterise_bytes(
                        img["data"],
                        filename=f"{parsed.filename}_p{page.page_number}_img{img.get('index', 0)}",
                    )
                    if img_result.description:
                        desc_chunks = self.chunker.chunk_text(
                            img_result.description,
                            source_file=parsed.filename,
                            page=page.page_number,
                            content_type="image_description",
                            extra_metadata={
                                "image_width": img_result.width,
                                "image_height": img_result.height,
                            },
                        )
                        all_chunks.extend(desc_chunks)

        # Embed and store
        stored = self.embedder.embed_and_store(all_chunks, document_id)

        return {
            "file_type": "pdf",
            "pages": parsed.page_count,
            "chunks_created": len(all_chunks),
            "chunks_stored": stored,
            "images_found": len(parsed.all_images()),
            "tables_found": sum(len(p.tables) for p in parsed.pages),
        }

    def _ingest_image(self, file_path: Path, filename: str,
                      document_id: str) -> dict[str, Any]:
        """Parse and ingest an image file."""
        # Try OCR first (for handwritten annotations)
        ocr_result = self.ocr_handler.process(file_path)
        all_chunks = []

        if ocr_result.text.strip() and ocr_result.confidence > 20:
            ocr_chunks = self.chunker.chunk_text(
                ocr_result.text,
                source_file=filename,
                content_type="ocr",
                confidence=ocr_result.confidence / 100.0,
                extra_metadata={"ocr_word_count": ocr_result.word_count},
            )
            all_chunks.extend(ocr_chunks)

        # Vision model characterisation
        if self.ollama.has_model(self.ollama.config.vision_model):
            img_result = self.image_handler.characterise(file_path)
            if img_result.description:
                desc_chunks = self.chunker.chunk_text(
                    img_result.description,
                    source_file=filename,
                    content_type="image_description",
                    extra_metadata={
                        "image_width": img_result.width,
                        "image_height": img_result.height,
                    },
                )
                all_chunks.extend(desc_chunks)
        else:
            # Metadata only
            img_result = self.image_handler.extract_metadata(file_path)
            meta_text = (
                f"Image: {filename}, "
                f"dimensions: {img_result.width}x{img_result.height}, "
                f"format: {img_result.format}"
            )
            all_chunks.extend(self.chunker.chunk_text(
                meta_text, source_file=filename, content_type="image_description",
            ))

        stored = self.embedder.embed_and_store(all_chunks, document_id)

        return {
            "file_type": "image",
            "chunks_created": len(all_chunks),
            "chunks_stored": stored,
            "ocr_text_found": bool(ocr_result.text.strip()),
            "ocr_confidence": ocr_result.confidence,
            "vision_characterised": bool(
                self.ollama.has_model(self.ollama.config.vision_model)
            ),
        }

    def _ingest_code(self, file_path: Path, document_id: str) -> dict[str, Any]:
        """Parse and ingest a source code file."""
        parsed = self.code_parser.parse(file_path)
        all_chunks = []

        if parsed.units:
            # Chunk by logical units
            code_chunks = self.chunker.chunk_code_units(
                parsed.units, source_file=parsed.filename,
                language=parsed.language,
            )
            all_chunks.extend(code_chunks)
        else:
            # Fallback: chunk entire file
            content = file_path.read_text(errors="replace")
            all_chunks = self.chunker.chunk_text(
                content, source_file=parsed.filename,
                content_type="code", language=parsed.language,
            )

        # Add a summary chunk with extracted elements
        summary_parts = []
        if parsed.functions:
            summary_parts.append(f"Functions: {', '.join(parsed.functions[:20])}")
        if parsed.classes:
            summary_parts.append(f"Classes: {', '.join(parsed.classes[:20])}")
        if parsed.imports:
            summary_parts.append(f"Imports: {', '.join(parsed.imports[:20])}")
        if parsed.defines:
            summary_parts.append(f"Defines: {', '.join(parsed.defines[:20])}")
        if parsed.structs:
            summary_parts.append(f"Structs: {', '.join(parsed.structs[:20])}")

        if summary_parts:
            summary = f"Code summary for {parsed.filename} ({parsed.language}):\n" + "\n".join(summary_parts)
            summary_chunks = self.chunker.chunk_text(
                summary, source_file=parsed.filename,
                content_type="code", language=parsed.language,
                extra_metadata={"is_summary": True},
            )
            all_chunks.extend(summary_chunks)

        stored = self.embedder.embed_and_store(all_chunks, document_id)

        return {
            "file_type": "code",
            "language": parsed.language,
            "line_count": parsed.line_count,
            "functions": len(parsed.functions),
            "classes": len(parsed.classes),
            "chunks_created": len(all_chunks),
            "chunks_stored": stored,
        }

    def _ingest_binary(self, file_path: Path, document_id: str) -> dict[str, Any]:
        """Parse and ingest a binary file."""
        parsed = self.binary_handler.parse(file_path)
        all_chunks = []

        # Header info as a chunk
        header_text = f"Binary file: {parsed.filename}\n"
        header_text += f"Type: {parsed.magic_type}\n"
        header_text += f"Size: {parsed.size_bytes} bytes\n"
        header_text += f"Entropy: {parsed.entropy:.4f}\n"
        header_text += f"Magic bytes: {parsed.magic_bytes_hex}\n"

        if parsed.headers:
            for k, v in parsed.headers.items():
                header_text += f"{k}: {v}\n"

        all_chunks.extend(self.chunker.chunk_text(
            header_text, source_file=parsed.filename,
            content_type="binary_strings",
            extra_metadata={"magic_type": parsed.magic_type, "entropy": parsed.entropy},
        ))

        # Extracted strings
        if parsed.strings:
            string_chunks = self.chunker.chunk_strings(
                parsed.strings, source_file=parsed.filename,
            )
            all_chunks.extend(string_chunks)

        stored = self.embedder.embed_and_store(all_chunks, document_id)

        return {
            "file_type": "binary",
            "magic_type": parsed.magic_type,
            "size_bytes": parsed.size_bytes,
            "entropy": parsed.entropy,
            "strings_extracted": len(parsed.strings),
            "chunks_created": len(all_chunks),
            "chunks_stored": stored,
        }

    def _ingest_text(self, file_path: Path, document_id: str) -> dict[str, Any]:
        """Parse and ingest a plain text or structured file."""
        content = file_path.read_text(errors="replace")
        filename = file_path.name

        chunks = self.chunker.chunk_text(
            content, source_file=filename, content_type="text",
        )

        stored = self.embedder.embed_and_store(chunks, document_id)

        return {
            "file_type": "text",
            "chunks_created": len(chunks),
            "chunks_stored": stored,
        }
