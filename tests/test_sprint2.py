"""ORACLE Sprint 2 tests — parsers, chunking, embedding, ingestion engine."""

import hashlib
import io
import struct
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.chunker import ChunkingEngine, Chunk
from oracle.intake.embedder import EmbeddingPipeline
from oracle.intake.engine import IngestionEngine
from oracle.intake.handler import IntakeHandler
from oracle.intake.parsers.pdf_parser import PDFParser, PDFResult
from oracle.intake.parsers.image_handler import ImageHandler, ImageResult
from oracle.intake.parsers.code_parser import CodeParser, CodeResult
from oracle.intake.parsers.binary_handler import BinaryHandler, BinaryResult
from oracle.intake.parsers.ocr_handler import OCRHandler, OCRResult


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def config(tmp_dir):
    return OracleConfig(
        config_dir=tmp_dir / "config",
        db_path=tmp_dir / "oracle.db",
        sessions_dir=tmp_dir / "sessions",
        documents_dir=tmp_dir / "documents",
        chroma_dir=tmp_dir / "chroma",
        key_path=tmp_dir / "keys" / "oracle.key",
    )


@pytest.fixture
def db(config):
    config.ensure_dirs()
    database = Database(config.db_path)
    yield database
    database.close()


@pytest.fixture
def vector_store(tmp_dir):
    return VectorStore(tmp_dir / "chroma")


@pytest.fixture
def mock_ollama():
    """Mock Ollama client that returns fake embeddings."""
    client = MagicMock(spec=OllamaClient)
    client.embed.return_value = [0.1] * 768
    client.embed_batch.side_effect = lambda texts, **kw: [[0.1] * 768 for _ in texts]
    client.has_model.return_value = False
    client.config = MagicMock()
    client.config.vision_model = "minicpm-v"
    client.config.embedding_model = "nomic-embed-text"
    return client


@pytest.fixture
def chunker():
    return ChunkingEngine()


@pytest.fixture
def embedder(mock_ollama, vector_store):
    return EmbeddingPipeline(mock_ollama, vector_store)


@pytest.fixture
def sample_pdf(tmp_dir):
    """Create a minimal test PDF using PyMuPDF."""
    import fitz
    pdf_path = tmp_dir / "test_datasheet.pdf"
    doc = fitz.open()

    # Page 1
    page = doc.new_page()
    page.insert_text((72, 72), "STM32F407VGT6 Datasheet", fontsize=16)
    page.insert_text((72, 120), "ARM Cortex-M4 32-bit microcontroller")
    page.insert_text((72, 140), "168 MHz CPU, 1MB Flash, 192KB SRAM")
    page.insert_text((72, 180), "Interfaces: SPI, I2C, UART, USB, CAN, Ethernet")
    page.insert_text((72, 200), "Package: LQFP100")

    # Page 2
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Pin Configuration", fontsize=14)
    page2.insert_text((72, 120), "Pin 1: VDD (Power Supply)")
    page2.insert_text((72, 140), "Pin 2: PA0 (GPIO / UART4_TX)")
    page2.insert_text((72, 160), "Pin 3: PA1 (GPIO / UART4_RX)")

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_image(tmp_dir):
    """Create a test image with text."""
    img_path = tmp_dir / "schematic.png"
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    img.save(str(img_path))
    return img_path


@pytest.fixture
def sample_code(tmp_dir):
    """Create a test C source file."""
    code_path = tmp_dir / "firmware.c"
    code_path.write_text(textwrap.dedent("""\
        #include <stdio.h>
        #include "stm32f4xx.h"

        #define BAUD_RATE 115200
        #define BUFFER_SIZE 256

        struct uart_config {
            uint32_t baud;
            uint8_t parity;
        };

        void uart_init(uint32_t baud) {
            USART1->BRR = SystemCoreClock / baud;
            USART1->CR1 |= USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
        }

        int main(void) {
            uart_init(BAUD_RATE);
            // Main loop
            while (1) {
                // Process data
            }
            return 0;
        }
    """))
    return code_path


@pytest.fixture
def sample_binary(tmp_dir):
    """Create a test ELF-like binary."""
    bin_path = tmp_dir / "firmware.elf"
    # ELF header
    data = b"\x7fELF"  # Magic
    data += b"\x01"     # 32-bit
    data += b"\x01"     # Little endian
    data += b"\x01"     # ELF version
    data += b"\x00" * 9  # Padding
    data += struct.pack("<H", 2)   # ET_EXEC
    data += struct.pack("<H", 40)  # ARM
    data += b"\x00" * 44  # Rest of header
    # Add some strings
    data += b"\x00" * 100
    data += b"STM32F407_firmware_v2.1\x00"
    data += b"UART_INIT_OK\x00"
    data += b"SPI_TRANSFER_COMPLETE\x00"
    data += b"Error: buffer overflow detected\x00"
    data += b"\x00" * 200
    return bin_path


@pytest.fixture
def sample_python(tmp_dir):
    """Create a test Python file."""
    py_path = tmp_dir / "exploit.py"
    py_path.write_text(textwrap.dedent("""\
        import struct
        from collections import namedtuple

        class FirmwareAnalyzer:
            def __init__(self, binary_path):
                self.path = binary_path
                self.sections = []

            def parse_header(self):
                with open(self.path, 'rb') as f:
                    magic = f.read(4)
                    return magic == b'\\x7fELF'

            def find_strings(self, min_length=6):
                results = []
                return results

        def calculate_checksum(data):
            return sum(data) & 0xFFFF
    """))
    return py_path


# ============================================================
# 1. PDF Parser
# ============================================================

class TestPDFParser:
    def test_parse_pdf(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        assert isinstance(result, PDFResult)
        assert result.page_count == 2
        assert result.filename == "test_datasheet.pdf"

    def test_page_text_extracted(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        assert "STM32F407VGT6" in result.pages[0].text
        assert "ARM Cortex-M4" in result.pages[0].text

    def test_page_numbers(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2

    def test_full_text(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        full = result.full_text()
        assert "STM32F407VGT6" in full
        assert "Pin Configuration" in full

    def test_parse_bytes(self, sample_pdf):
        parser = PDFParser()
        data = sample_pdf.read_bytes()
        result = parser.parse_bytes(data, "bytes_test.pdf")
        assert result.page_count == 2
        assert result.filename == "bytes_test.pdf"

    def test_metadata_extracted(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        assert isinstance(result.metadata, dict)

    def test_second_page_content(self, sample_pdf):
        parser = PDFParser()
        result = parser.parse(sample_pdf)
        assert "Pin 1" in result.pages[1].text
        assert "UART4_TX" in result.pages[1].text

    def test_image_extraction_dir(self, sample_pdf, tmp_dir):
        parser = PDFParser(image_output_dir=tmp_dir / "images")
        result = parser.parse(sample_pdf)
        assert isinstance(result.all_images(), list)


# ============================================================
# 2. Image Handler
# ============================================================

class TestImageHandler:
    def test_extract_metadata(self, sample_image):
        handler = ImageHandler()
        result = handler.extract_metadata(sample_image)
        assert isinstance(result, ImageResult)
        assert result.width == 200
        assert result.height == 100
        assert result.filename == "schematic.png"

    def test_metadata_hash(self, sample_image):
        handler = ImageHandler()
        result = handler.extract_metadata(sample_image)
        assert len(result.file_hash) == 64

    def test_metadata_format(self, sample_image):
        handler = ImageHandler()
        result = handler.extract_metadata(sample_image)
        assert result.format in ("PNG", "png")

    def test_extract_metadata_bytes(self):
        img = Image.new("RGB", (50, 50), color=(128, 128, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        handler = ImageHandler()
        result = handler.extract_metadata_bytes(buf.getvalue(), "test.png")
        assert result.width == 50
        assert result.height == 50

    def test_characterise_no_ollama(self, sample_image):
        handler = ImageHandler(ollama=None)
        result = handler.characterise(sample_image)
        assert result.description == ""

    def test_jpeg_support(self, tmp_dir):
        jpg_path = tmp_dir / "photo.jpg"
        img = Image.new("RGB", (300, 200), color=(200, 100, 50))
        img.save(str(jpg_path), format="JPEG")
        handler = ImageHandler()
        result = handler.extract_metadata(jpg_path)
        assert result.width == 300
        assert result.height == 200

    def test_tiff_support(self, tmp_dir):
        tiff_path = tmp_dir / "scan.tiff"
        img = Image.new("RGB", (150, 150), color=(0, 0, 0))
        img.save(str(tiff_path), format="TIFF")
        handler = ImageHandler()
        result = handler.extract_metadata(tiff_path)
        assert result.width == 150


# ============================================================
# 3. Code Parser
# ============================================================

class TestCodeParser:
    def test_detect_language_c(self):
        parser = CodeParser()
        assert parser.detect_language("firmware.c") == "c"
        assert parser.detect_language("header.h") == "c"

    def test_detect_language_python(self):
        parser = CodeParser()
        assert parser.detect_language("script.py") == "python"

    def test_detect_language_rust(self):
        parser = CodeParser()
        assert parser.detect_language("main.rs") == "rust"

    def test_detect_language_verilog(self):
        parser = CodeParser()
        assert parser.detect_language("fpga.v") == "verilog"
        assert parser.detect_language("design.sv") == "systemverilog"

    def test_detect_language_unknown(self):
        parser = CodeParser()
        assert parser.detect_language("file.xyz") == "unknown"

    def test_parse_c_file(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert isinstance(result, CodeResult)
        assert result.language == "c"
        assert "uart_init" in result.functions
        assert "main" in result.functions

    def test_c_includes(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert "stdio.h" in result.imports
        assert "stm32f4xx.h" in result.imports

    def test_c_defines(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert "BAUD_RATE" in result.defines
        assert "BUFFER_SIZE" in result.defines

    def test_c_structs(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert "uart_config" in result.structs

    def test_c_comments(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert any("Main loop" in c for c in result.comments)

    def test_parse_python(self, sample_python):
        parser = CodeParser()
        result = parser.parse(sample_python)
        assert result.language == "python"
        assert "FirmwareAnalyzer" in result.classes
        assert "calculate_checksum" in result.functions

    def test_python_imports(self, sample_python):
        parser = CodeParser()
        result = parser.parse(sample_python)
        assert any("struct" in i for i in result.imports)

    def test_code_units_extracted(self, sample_python):
        parser = CodeParser()
        result = parser.parse(sample_python)
        assert len(result.units) > 0
        unit_names = [u.name for u in result.units]
        assert "FirmwareAnalyzer" in unit_names

    def test_line_count(self, sample_code):
        parser = CodeParser()
        result = parser.parse(sample_code)
        assert result.line_count > 10

    def test_parse_text_directly(self):
        parser = CodeParser()
        result = parser.parse_text("def hello():\n    pass\n", "test.py")
        assert result.language == "python"
        assert "hello" in result.functions


# ============================================================
# 4. Binary Handler
# ============================================================

class TestBinaryHandler:
    def test_parse_elf(self, sample_binary):
        sample_binary.write_bytes(self._make_elf())
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert isinstance(result, BinaryResult)
        assert result.magic_type == "ELF executable"

    def test_string_extraction(self, sample_binary):
        data = b"\x00" * 50 + b"FIRMWARE_VERSION_2.1" + b"\x00" * 50
        sample_binary.write_bytes(data)
        handler = BinaryHandler(min_string_length=6)
        result = handler.parse(sample_binary)
        assert "FIRMWARE_VERSION_2.1" in result.strings

    def test_min_string_length(self, sample_binary):
        data = b"\x00" * 20 + b"short" + b"\x00" + b"longer_string_here" + b"\x00" * 20
        sample_binary.write_bytes(data)
        handler = BinaryHandler(min_string_length=6)
        result = handler.parse(sample_binary)
        assert "longer_string_here" in result.strings
        assert "short" not in result.strings

    def test_entropy_calculation(self, sample_binary):
        # Random-ish data should have high entropy
        import os
        sample_binary.write_bytes(os.urandom(1000))
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert result.entropy > 7.0  # Max is 8.0

    def test_low_entropy(self, sample_binary):
        # Repeated data has low entropy
        sample_binary.write_bytes(b"\x00" * 1000)
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert result.entropy == 0.0

    def test_file_hash(self, sample_binary):
        data = b"test binary content"
        sample_binary.write_bytes(data)
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert result.file_hash == hashlib.sha256(data).hexdigest()

    def test_magic_bytes_hex(self, sample_binary):
        sample_binary.write_bytes(b"\x7fELF" + b"\x00" * 60)
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert result.magic_bytes_hex.startswith("7f454c46")

    def test_unknown_magic(self, sample_binary):
        sample_binary.write_bytes(b"\xDE\xAD\xBE\xEF" + b"\x00" * 100)
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert result.magic_type == "unknown"

    def test_parse_bytes(self):
        handler = BinaryHandler()
        result = handler.parse_bytes(b"\x7fELF" + b"\x00" * 60, "test.elf")
        assert result.filename == "test.elf"
        assert result.magic_type == "ELF executable"

    def test_metadata(self, sample_binary):
        sample_binary.write_bytes(b"\x00" * 100 + b"test_string_here" + b"\x00" * 100)
        handler = BinaryHandler()
        result = handler.parse(sample_binary)
        assert "string_count" in result.metadata
        assert "entropy" in result.metadata

    def _make_elf(self) -> bytes:
        data = b"\x7fELF"
        data += b"\x01\x01\x01"
        data += b"\x00" * 9
        data += struct.pack("<H", 2)   # ET_EXEC
        data += struct.pack("<H", 40)  # ARM
        data += b"\x00" * 44
        data += b"\x00" * 100
        data += b"TEST_STRING_EXTRACTED\x00"
        return data


# ============================================================
# 5. OCR Handler
# ============================================================

class TestOCRHandler:
    def test_process_image(self, sample_image):
        handler = OCRHandler()
        result = handler.process(sample_image)
        assert isinstance(result, OCRResult)
        assert result.filename == "schematic.png"

    def test_process_bytes(self):
        img = Image.new("RGB", (200, 50), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        handler = OCRHandler()
        result = handler.process_bytes(buf.getvalue(), "test.png")
        assert isinstance(result, OCRResult)

    def test_preprocessing_steps(self, sample_image):
        handler = OCRHandler()
        result = handler.process(sample_image)
        assert len(result.preprocessing) > 0
        assert "grayscale" in result.preprocessing

    def test_confidence_score(self, sample_image):
        handler = OCRHandler()
        result = handler.process(sample_image)
        assert isinstance(result.confidence, float)

    def test_metadata_includes_language(self, sample_image):
        handler = OCRHandler()
        result = handler.process(sample_image)
        assert result.metadata.get("language") == "eng"

    def test_custom_language(self):
        handler = OCRHandler(language="deu")
        assert handler.language == "deu"


# ============================================================
# 6. Chunking Engine
# ============================================================

class TestChunkingEngine:
    def test_short_text_single_chunk(self, chunker):
        chunks = chunker.chunk_text("Short text.", source_file="test.pdf")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text."
        assert chunks[0].source_file == "test.pdf"

    def test_empty_text_no_chunks(self, chunker):
        chunks = chunker.chunk_text("", source_file="test.pdf")
        assert len(chunks) == 0

    def test_whitespace_only_no_chunks(self, chunker):
        chunks = chunker.chunk_text("   \n\n   ", source_file="test.pdf")
        assert len(chunks) == 0

    def test_long_text_multiple_chunks(self, chunker):
        # ~3000 chars should produce multiple chunks at 512 tokens (~2048 chars)
        text = "This is a test sentence. " * 200
        chunks = chunker.chunk_text(text, source_file="long.pdf")
        assert len(chunks) > 1

    def test_source_file_preserved(self, chunker):
        chunks = chunker.chunk_text("Test text", source_file="datasheet.pdf")
        assert all(c.source_file == "datasheet.pdf" for c in chunks)

    def test_page_number_preserved(self, chunker):
        chunks = chunker.chunk_text("Test", source_file="doc.pdf", page=5)
        assert chunks[0].page == 5

    def test_section_preserved(self, chunker):
        chunks = chunker.chunk_text("Test", source_file="doc.pdf", section="Introduction")
        assert chunks[0].section == "Introduction"

    def test_content_type_preserved(self, chunker):
        chunks = chunker.chunk_text("Test", source_file="doc.pdf", content_type="table")
        assert chunks[0].content_type == "table"

    def test_chunk_id_unique(self, chunker):
        chunks = chunker.chunk_text("A " * 1000, source_file="test.pdf")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_index_sequential(self, chunker):
        text = "Paragraph one.\n\n" * 100
        chunks = chunker.chunk_text(text, source_file="test.pdf")
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_chunk_code_units(self, chunker):
        from oracle.intake.parsers.code_parser import CodeUnit
        units = [
            CodeUnit("main", "function", 1, 10, "int main() { return 0; }", "c"),
            CodeUnit("init", "function", 11, 20, "void init() { setup(); }", "c"),
        ]
        chunks = chunker.chunk_code_units(units, source_file="test.c", language="c")
        assert len(chunks) == 2
        assert chunks[0].content_type == "code"
        assert chunks[0].section == "function:main"

    def test_chunk_table(self, chunker):
        rows = [["Pin", "Function"], ["1", "VDD"], ["2", "PA0"]]
        chunks = chunker.chunk_table(rows, source_file="ds.pdf", page=3)
        assert len(chunks) >= 1
        assert "Pin" in chunks[0].text
        assert chunks[0].content_type == "table"

    def test_chunk_strings(self, chunker):
        strings = ["FIRMWARE_V2", "UART_INIT", "SPI_TRANSFER"]
        chunks = chunker.chunk_strings(strings, source_file="fw.bin")
        assert len(chunks) >= 1
        assert chunks[0].content_type == "binary_strings"

    def test_token_estimate(self, chunker):
        chunks = chunker.chunk_text("Hello world test", source_file="t.txt")
        assert chunks[0].token_estimate == len("Hello world test") // 4

    def test_confidence_preserved(self, chunker):
        chunks = chunker.chunk_text("OCR text", source_file="scan.png", confidence=0.75)
        assert chunks[0].confidence == 0.75

    def test_extra_metadata_preserved(self, chunker):
        chunks = chunker.chunk_text("Test", source_file="t.txt",
                                     extra_metadata={"custom_key": "value"})
        assert chunks[0].metadata.get("custom_key") == "value"

    def test_language_preserved(self, chunker):
        chunks = chunker.chunk_text("Test", source_file="t.txt", language="de")
        assert chunks[0].language == "de"


# ============================================================
# 7. Embedding Pipeline
# ============================================================

class TestEmbeddingPipeline:
    def test_embed_and_store(self, embedder):
        chunks = [
            Chunk(chunk_id="c1", text="STM32F4 datasheet", chunk_index=0,
                  source_file="ds.pdf", content_type="text"),
            Chunk(chunk_id="c2", text="UART configuration", chunk_index=1,
                  source_file="ds.pdf", page=2, content_type="text"),
        ]
        stored = embedder.embed_and_store(chunks, "doc1")
        assert stored == 2

    def test_embed_empty_chunks(self, embedder):
        stored = embedder.embed_and_store([], "doc1")
        assert stored == 0

    def test_embed_skips_empty_text(self, embedder):
        chunks = [
            Chunk(chunk_id="c1", text="", chunk_index=0,
                  source_file="ds.pdf", content_type="text"),
        ]
        stored = embedder.embed_and_store(chunks, "doc1")
        assert stored == 0

    def test_metadata_stored(self, embedder, vector_store):
        chunks = [
            Chunk(chunk_id="c1", text="Test chunk with metadata", chunk_index=0,
                  source_file="test.pdf", page=3, section="intro",
                  content_type="text", language="en", confidence=0.95),
        ]
        embedder.embed_and_store(chunks, "doc1")
        results = vector_store._collection.get(ids=["c1"], include=["metadatas"])
        meta = results["metadatas"][0]
        assert meta["source_file"] == "test.pdf"
        assert meta["page"] == 3
        assert meta["section"] == "intro"
        assert meta["document_id"] == "doc1"

    def test_search(self, embedder):
        chunks = [
            Chunk(chunk_id="c1", text="STM32 microcontroller specs", chunk_index=0,
                  source_file="ds.pdf", content_type="text"),
        ]
        embedder.embed_and_store(chunks, "doc1")
        results = embedder.search("STM32 specs")
        assert len(results) >= 1
        assert results[0]["chunk_id"] == "c1"
        assert "relevance" in results[0]

    def test_search_returns_metadata(self, embedder):
        chunks = [
            Chunk(chunk_id="c1", text="Power supply schematic", chunk_index=0,
                  source_file="sch.pdf", page=1, content_type="text"),
        ]
        embedder.embed_and_store(chunks, "doc1")
        results = embedder.search("power supply")
        assert results[0]["metadata"]["source_file"] == "sch.pdf"

    def test_get_stats(self, embedder):
        stats = embedder.get_stats()
        assert "vector_store" in stats


# ============================================================
# 8. Ingestion Engine
# ============================================================

class TestIngestionEngine:
    @pytest.fixture
    def engine(self, mock_ollama, vector_store, db, tmp_dir):
        return IngestionEngine(
            ollama=mock_ollama,
            vector_store=vector_store,
            db=db,
            image_output_dir=tmp_dir / "images",
        )

    @pytest.fixture
    def intake(self, config, db):
        return IntakeHandler(config, db)

    def test_ingest_pdf(self, engine, db, intake, config, sample_pdf):
        session = db.create_session("PDF Test")
        doc = intake.receive_file(session["session_id"], "datasheet.pdf",
                                   sample_pdf.read_bytes())
        result = engine.ingest_document(doc["document_id"])
        assert result["file_type"] == "pdf"
        assert result["pages"] == 2
        assert result["chunks_stored"] > 0

        # Verify document status updated
        updated = db.get_document(doc["document_id"])
        assert updated["ingestion_status"] == "indexed"

    def test_ingest_code(self, engine, db, intake, config, sample_code):
        session = db.create_session("Code Test")
        doc = intake.receive_file(session["session_id"], "firmware.c",
                                   sample_code.read_bytes())
        result = engine.ingest_document(doc["document_id"])
        assert result["file_type"] == "code"
        assert result["language"] == "c"
        assert result["functions"] > 0
        assert result["chunks_stored"] > 0

    def test_ingest_text(self, engine, db, intake, config, tmp_dir):
        session = db.create_session("Text Test")
        text_file = tmp_dir / "notes.txt"
        text_file.write_text("Research notes about the JTAG interface on the target board.")
        doc = intake.receive_file(session["session_id"], "notes.txt",
                                   text_file.read_bytes())
        result = engine.ingest_document(doc["document_id"])
        assert result["file_type"] == "text"
        assert result["chunks_stored"] > 0

    def test_ingest_image(self, engine, db, intake, config, sample_image):
        session = db.create_session("Image Test")
        doc = intake.receive_file(session["session_id"], "schematic.png",
                                   sample_image.read_bytes())
        result = engine.ingest_document(doc["document_id"])
        assert result["file_type"] == "image"
        assert result["chunks_stored"] > 0

    def test_ingest_binary(self, engine, db, intake, config, tmp_dir):
        session = db.create_session("Binary Test")
        bin_data = b"\x7fELF\x01\x01\x01" + b"\x00" * 57 + b"TEST_STRING_HERE\x00" + b"\x00" * 200
        bin_file = tmp_dir / "firmware.elf"
        bin_file.write_bytes(bin_data)
        doc = intake.receive_file(session["session_id"], "firmware.elf",
                                   bin_data)
        result = engine.ingest_document(doc["document_id"])
        assert result["file_type"] == "binary"
        assert result["chunks_stored"] > 0

    def test_ingest_nonexistent_document(self, engine):
        with pytest.raises(ValueError, match="Document not found"):
            engine.ingest_document("nonexistent")

    def test_ingest_missing_file(self, engine, db):
        session = db.create_session("Missing File")
        db.add_document(session["session_id"], "gone.pdf", "/nonexistent/path.pdf",
                         "pdf", 100, "hash")
        doc = db.list_documents(session["session_id"])[0]
        with pytest.raises(FileNotFoundError):
            engine.ingest_document(doc["document_id"])

    def test_failed_ingestion_status(self, engine, db, tmp_dir):
        session = db.create_session("Fail Test")
        # Create a file that will fail during PDF parsing
        bad_file = tmp_dir / "bad.pdf"
        bad_file.write_bytes(b"not a real pdf")
        db.add_document(session["session_id"], "bad.pdf", str(bad_file),
                         "pdf", 100, "hash")
        doc = db.list_documents(session["session_id"])[0]
        try:
            engine.ingest_document(doc["document_id"])
        except:
            pass
        updated = db.get_document(doc["document_id"])
        assert updated["ingestion_status"] == "failed"

    def test_search_after_ingest(self, engine, db, intake, config, sample_pdf):
        session = db.create_session("Search Test")
        doc = intake.receive_file(session["session_id"], "datasheet.pdf",
                                   sample_pdf.read_bytes())
        engine.ingest_document(doc["document_id"])
        results = engine.embedder.search("STM32 microcontroller")
        assert len(results) > 0
        assert "datasheet.pdf" in results[0]["metadata"]["source_file"]


# ============================================================
# 9. Integration — Full Sprint 2 Pipeline
# ============================================================

class TestSprint2Integration:
    def test_full_pipeline_pdf(self, config, db, mock_ollama, vector_store, tmp_dir):
        """End-to-end: upload PDF → ingest → search → get results with source refs."""
        config.ensure_dirs()
        intake = IntakeHandler(config, db)
        engine = IngestionEngine(mock_ollama, vector_store, db)

        # Create session and upload
        session = db.create_session("Full Pipeline Test")
        sid = session["session_id"]

        # Create a test PDF
        import fitz
        pdf_path = tmp_dir / "stm32_datasheet.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "STM32F407VGT6 ARM Cortex-M4 Microcontroller")
        page.insert_text((72, 100), "168 MHz, 1MB Flash, 192KB SRAM")
        page.insert_text((72, 130), "Interfaces: SPI, I2C, UART, USB OTG, CAN, Ethernet")
        doc.save(str(pdf_path))
        doc.close()

        # Upload
        doc_record = intake.receive_file(sid, "stm32_datasheet.pdf", pdf_path.read_bytes())
        assert doc_record["ingestion_status"] == "received"

        # Ingest
        result = engine.ingest_document(doc_record["document_id"])
        assert result["chunks_stored"] > 0

        # Search
        search_results = engine.embedder.search("What interfaces does the STM32 support?")
        assert len(search_results) > 0

        # Verify source references
        first = search_results[0]
        assert "stm32_datasheet.pdf" in first["metadata"]["source_file"]
        assert "document_id" in first["metadata"]

    def test_multi_format_ingest(self, config, db, mock_ollama, vector_store, tmp_dir):
        """Ingest PDF + code + text in same session."""
        config.ensure_dirs()
        intake = IntakeHandler(config, db)
        engine = IngestionEngine(mock_ollama, vector_store, db)

        session = db.create_session("Multi Format")
        sid = session["session_id"]

        # PDF
        import fitz
        pdf_path = tmp_dir / "spec.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Product specification document")
        doc.save(str(pdf_path))
        doc.close()
        pdf_doc = intake.receive_file(sid, "spec.pdf", pdf_path.read_bytes())

        # Code
        code_content = b"void spi_init() { SPI1->CR1 = 0x03; }"
        code_doc = intake.receive_file(sid, "spi.c", code_content)

        # Text
        text_content = b"Notes: JTAG header on J5, 20-pin ARM standard"
        text_doc = intake.receive_file(sid, "notes.txt", text_content)

        # Ingest all
        for d in [pdf_doc, code_doc, text_doc]:
            engine.ingest_document(d["document_id"])

        # Verify all indexed
        docs = db.list_documents(sid)
        assert all(d["ingestion_status"] == "indexed" for d in docs)

        # Search across all
        results = engine.embedder.search("SPI configuration")
        assert len(results) > 0
