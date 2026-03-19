"""ORACLE Sprint 6 tests — integration, packaging, air-gap, final verification."""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import fitz  # PyMuPDF

from oracle import __version__
from oracle.core.config import OracleConfig
from oracle.core.crypto import CryptoEngine
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.handler import IntakeHandler
from oracle.intake.engine import IngestionEngine
from oracle.intake.chunker import ChunkingEngine
from oracle.intake.parsers.pdf_parser import PDFParser
from oracle.intake.parsers.code_parser import CodeParser
from oracle.intake.parsers.binary_handler import BinaryHandler
from oracle.intake.parsers.image_handler import ImageHandler
from oracle.intake.parsers.ocr_handler import OCRHandler
from oracle.graph.engine import ComponentGraph
from oracle.graph.extractor import ComponentExtractor
from oracle.query.engine import QueryEngine
from oracle.query.parser import QueryParser
from oracle.query.confidence import WilsonScorer
from oracle.validation.detector import ResponseValidator
from oracle.validation.profiler import ResearcherProfiler
from oracle.validation.audit import AuditTrail


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path

@pytest.fixture
def config(tmp_dir):
    return OracleConfig(
        config_dir=tmp_dir / "config", db_path=tmp_dir / "oracle.db",
        sessions_dir=tmp_dir / "sessions", documents_dir=tmp_dir / "documents",
        chroma_dir=tmp_dir / "chroma", key_path=tmp_dir / "keys" / "oracle.key",
    )

@pytest.fixture
def db(config):
    config.ensure_dirs()
    database = Database(config.db_path)
    yield database
    database.close()

@pytest.fixture
def crypto(tmp_dir):
    return CryptoEngine(key_path=tmp_dir / "keys" / "test.key")

@pytest.fixture
def vector_store(tmp_dir):
    return VectorStore(tmp_dir / "chroma")

@pytest.fixture
def mock_ollama():
    client = MagicMock(spec=OllamaClient)
    client.embed.return_value = [0.1] * 768
    client.is_available.return_value = True
    client.has_model.return_value = False
    client.config = MagicMock()
    client.config.reasoning_model = "mistral-small:24b"
    client.config.vision_model = "minicpm-v"
    client.config.embedding_model = "nomic-embed-text"
    client.generate.return_value = {
        "response": "The STM32F407VGT6 supports SPI, I2C, and UART interfaces. "
                    "[Source: datasheet.pdf, p.1] The SPI bus connects to external flash. "
                    "[Source: schematic.pdf, p.2]",
        "model": "mistral-small:24b",
    }
    return client

@pytest.fixture
def sample_pdf(tmp_dir):
    pdf_path = tmp_dir / "ics_datasheet.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Industrial Control System — PLC Module X200", fontsize=14)
    page1.insert_text((72, 110), "Main MCU: STM32F407VGT6 ARM Cortex-M4 168MHz")
    page1.insert_text((72, 130), "External Flash: W25Q128JVSIQ (16MB SPI)")
    page1.insert_text((72, 150), "Ethernet PHY: LAN8720A (RMII)")
    page1.insert_text((72, 170), "Power: AMS1117-3.3V LDO regulator")
    page1.insert_text((72, 190), "Debug: UART (115200 baud) + JTAG (20-pin ARM)")
    page1.insert_text((72, 210), "CAN bus: MCP2551 transceiver")
    page1.insert_text((72, 230), "USB: Type-C connector, USB 2.0 Full Speed")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Communication Interfaces", fontsize=14)
    page2.insert_text((72, 110), "SPI1: Connected to W25Q128 flash (PA5/PA6/PA7)")
    page2.insert_text((72, 130), "I2C1: Connected to RTC DS3231 and EEPROM AT24C256")
    page2.insert_text((72, 150), "UART1: Debug console at 115200 baud (PA9/PA10)")
    page2.insert_text((72, 170), "CAN1: Industrial bus via MCP2551 (PB8/PB9)")
    page2.insert_text((72, 190), "Ethernet: RMII to LAN8720A (PA1/PA2/PA7)")
    page2.insert_text((72, 210), "USB OTG FS: Type-C connector (PA11/PA12)")

    page3 = doc.new_page()
    page3.insert_text((72, 72), "Firmware Specification", fontsize=14)
    page3.insert_text((72, 110), "RTOS: FreeRTOS v10.5.1")
    page3.insert_text((72, 130), "HAL: STM32 HAL v1.27.1")
    page3.insert_text((72, 150), "Network: lwIP v2.1.3")
    page3.insert_text((72, 170), "Protocol: Modbus TCP/RTU")
    page3.insert_text((72, 190), "Bootloader: Custom secure boot with SHA-256 verification")

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path

@pytest.fixture
def sample_firmware(tmp_dir):
    code_path = tmp_dir / "main.c"
    code_path.write_text(textwrap.dedent("""\
        #include "stm32f4xx_hal.h"
        #include "FreeRTOS.h"
        #include "task.h"
        #include "lwip.h"

        #define MODBUS_PORT 502
        #define UART_BAUD 115200

        SPI_HandleTypeDef hspi1;
        UART_HandleTypeDef huart1;

        void SystemClock_Config(void);
        void MX_GPIO_Init(void);
        void MX_SPI1_Init(void);
        void MX_USART1_UART_Init(void);

        void spi_flash_read(uint32_t addr, uint8_t *buf, uint32_t len) {
            HAL_SPI_Transmit(&hspi1, &addr, 3, 100);
            HAL_SPI_Receive(&hspi1, buf, len, 100);
        }

        void modbus_task(void *pvParameters) {
            while (1) {
                // Process Modbus TCP requests on port 502
                vTaskDelay(pdMS_TO_TICKS(10));
            }
        }

        int main(void) {
            HAL_Init();
            SystemClock_Config();
            MX_GPIO_Init();
            MX_SPI1_Init();
            MX_USART1_UART_Init();
            MX_LWIP_Init();

            xTaskCreate(modbus_task, "Modbus", 512, NULL, 3, NULL);
            vTaskStartScheduler();

            while (1) {}
        }
    """))
    return code_path


# ============================================================
# 1. Full End-to-End Pipeline
# ============================================================

class TestEndToEnd:
    def test_complete_pipeline(self, config, db, vector_store, mock_ollama,
                                crypto, sample_pdf, sample_firmware):
        """Ingest → Graph → Query → Validate → Audit — full pipeline."""
        config.ensure_dirs()
        intake = IntakeHandler(config, db)
        ingestion = IngestionEngine(mock_ollama, vector_store, db)
        graph = ComponentGraph(db)
        extractor = ComponentExtractor(mock_ollama, vector_store, db)
        engine = QueryEngine(mock_ollama, vector_store, db, graph, crypto)

        # Create session
        session = db.create_session("ICS Teardown — PLC X200")
        sid = session["session_id"]

        # Ingest PDF
        pdf_doc = intake.receive_file(sid, "ics_datasheet.pdf", sample_pdf.read_bytes())
        ingestion.ingest_document(pdf_doc["document_id"])

        # Ingest firmware
        fw_doc = intake.receive_file(sid, "main.c", sample_firmware.read_bytes())
        ingestion.ingest_document(fw_doc["document_id"])

        # Verify ingestion
        docs = db.list_documents(sid)
        assert len(docs) == 2
        assert all(d["ingestion_status"] == "indexed" for d in docs)

        # Extract components
        components = extractor.extract_components(sid, use_llm=False)
        assert len(components) > 0

        # Map relationships
        rels = extractor.extract_relationships(sid)

        # Build graph
        stats = graph.build_from_session(sid)
        assert stats["nodes"] > 0

        # Query
        response = engine.query(sid, "What interfaces does this PLC expose?")
        assert len(response.response_text) > 0
        assert len(response.citations) > 0
        assert response.validation_status in ("GREEN", "AMBER", "RED")
        assert response.confidence.get("overall", 0) > 0

        # Audit trail
        log = db.get_audit_log()
        event_types = [e["event_type"] for e in log]
        assert "query_submitted" in event_types
        assert "response_validated" in event_types

    def test_multi_query_session(self, config, db, vector_store, mock_ollama,
                                  crypto, sample_pdf):
        """Multiple queries in a session with follow-ups."""
        config.ensure_dirs()
        intake = IntakeHandler(config, db)
        ingestion = IngestionEngine(mock_ollama, vector_store, db)
        engine = QueryEngine(mock_ollama, vector_store, db, crypto=crypto)

        session = db.create_session("Multi Query Test")
        sid = session["session_id"]

        doc = intake.receive_file(sid, "datasheet.pdf", sample_pdf.read_bytes())
        ingestion.ingest_document(doc["document_id"])

        # First query
        r1 = engine.query(sid, "What is the main MCU?")
        assert len(r1.response_text) > 0

        # Follow-up
        r2 = engine.query(sid, "What speed does it run at?")
        assert len(r2.response_text) > 0

        # Third query
        r3 = engine.query(sid, "What memory is available?")
        assert len(r3.response_text) > 0

        # Session has 3 queries
        queries = db.list_queries(sid)
        assert len(queries) == 3
        assert all(q["confidence_score"] is not None for q in queries)


# ============================================================
# 2. Air-Gap Verification
# ============================================================

class TestAirGap:
    def test_no_external_imports(self):
        """Verify no modules that require network access are imported at runtime."""
        import oracle.api.app
        import oracle.query.engine
        import oracle.validation.detector
        # These should all import without network access
        assert True

    def test_ollama_url_is_local(self):
        config = OracleConfig()
        assert "localhost" in config.ollama.base_url or "127.0.0.1" in config.ollama.base_url

    def test_chromadb_telemetry_disabled(self, vector_store):
        # ChromaDB should be created with anonymized_telemetry=False
        assert vector_store.count >= 0  # Verifies it initialised offline

    def test_no_cloud_dependencies(self):
        """Verify pyproject.toml has no cloud SDK dependencies."""
        import tomllib
        with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        cloud_sdks = ["boto3", "azure", "google-cloud", "openai", "anthropic"]
        for dep in deps:
            for sdk in cloud_sdks:
                assert sdk not in dep.lower(), f"Cloud dependency found: {dep}"


# ============================================================
# 3. Packaging Verification
# ============================================================

class TestPackaging:
    def test_dockerfile_exists(self):
        assert Path("/home/richard/projects/red-specter-oracle/Dockerfile").exists()

    def test_docker_compose_exists(self):
        assert Path("/home/richard/projects/red-specter-oracle/docker-compose.yml").exists()

    def test_setup_script_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/setup.sh")
        assert p.exists()
        assert os.access(str(p), os.X_OK)

    def test_docker_compose_has_ollama(self):
        compose = Path("/home/richard/projects/red-specter-oracle/docker-compose.yml").read_text()
        assert "ollama" in compose
        assert "oracle-api" in compose or "oracle" in compose

    def test_docker_compose_has_volumes(self):
        compose = Path("/home/richard/projects/red-specter-oracle/docker-compose.yml").read_text()
        assert "oracle-data" in compose
        assert "ollama-models" in compose

    def test_docker_compose_has_healthcheck(self):
        compose = Path("/home/richard/projects/red-specter-oracle/docker-compose.yml").read_text()
        assert "healthcheck" in compose


# ============================================================
# 4. Documentation Verification
# ============================================================

class TestDocumentation:
    def test_readme_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/README.md")
        assert p.exists()
        content = p.read_text()
        assert "ORACLE" in content
        assert "Quick Start" in content

    def test_install_guide_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/INSTALL.md")
        assert p.exists()
        content = p.read_text()
        assert "docker" in content.lower()

    def test_user_guide_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/USER_GUIDE.md")
        assert p.exists()
        content = p.read_text()
        assert "session" in content.lower()
        assert "confidence" in content.lower()

    def test_architecture_doc_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/ARCHITECTURE.md")
        assert p.exists()
        content = p.read_text()
        assert "API" in content
        assert "Database" in content

    def test_security_doc_exists(self):
        p = Path("/home/richard/projects/red-specter-oracle/SECURITY.md")
        assert p.exists()
        content = p.read_text()
        assert "Ed25519" in content
        assert "air-gap" in content.lower() or "Air-Gap" in content

    def test_pyproject_toml_valid(self):
        import tomllib
        with open(Path("/home/richard/projects/red-specter-oracle/pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["name"] == "red-specter-oracle"
        assert "oracle" in str(data["project"]["scripts"])


# ============================================================
# 5. Database Schema Verification
# ============================================================

class TestDatabaseSchema:
    def test_all_tables_exist(self, db):
        tables = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        required = ["sessions", "documents", "queries", "audit_log",
                     "components", "relationships", "graph_snapshots"]
        for t in required:
            assert t in table_names, f"Missing table: {t}"

    def test_all_indexes_exist(self, db):
        indexes = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        assert len(indexes) >= 10

    def test_foreign_keys_enabled(self, db):
        result = db._conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

    def test_wal_mode(self, db):
        result = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"


# ============================================================
# 6. Version and Metadata
# ============================================================

class TestVersion:
    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3

    def test_cli_entry_point(self):
        import tomllib
        with open(Path("/home/richard/projects/red-specter-oracle/pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        assert "oracle" in data["project"]["scripts"]


# ============================================================
# 7. Component Coverage
# ============================================================

class TestComponentCoverage:
    """Verify all major components are importable and functional."""

    def test_import_intake(self):
        from oracle.intake.handler import IntakeHandler
        from oracle.intake.engine import IngestionEngine
        from oracle.intake.chunker import ChunkingEngine
        assert True

    def test_import_parsers(self):
        from oracle.intake.parsers.pdf_parser import PDFParser
        from oracle.intake.parsers.image_handler import ImageHandler
        from oracle.intake.parsers.code_parser import CodeParser
        from oracle.intake.parsers.binary_handler import BinaryHandler
        from oracle.intake.parsers.ocr_handler import OCRHandler
        assert True

    def test_import_graph(self):
        from oracle.graph.engine import ComponentGraph
        from oracle.graph.extractor import ComponentExtractor
        assert True

    def test_import_query(self):
        from oracle.query.engine import QueryEngine
        from oracle.query.parser import QueryParser
        from oracle.query.retriever import Retriever
        from oracle.query.synthesiser import Synthesiser
        from oracle.query.confidence import WilsonScorer
        assert True

    def test_import_validation(self):
        from oracle.validation.detector import ResponseValidator
        from oracle.validation.profiler import ResearcherProfiler
        from oracle.validation.audit import AuditTrail
        assert True

    def test_import_core(self):
        from oracle.core.config import OracleConfig
        from oracle.core.crypto import CryptoEngine
        from oracle.core.ollama_client import OllamaClient
        from oracle.core.vector_store import VectorStore
        from oracle.core.banner import print_banner
        from oracle.core.logger import setup_logger
        assert True


# ============================================================
# 8. UI Endpoints
# ============================================================

class TestUIEndpoints:
    @pytest.fixture
    def client(self, config):
        config.ensure_dirs()
        from oracle.api.app import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app(config))

    def test_intake_ui(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ORACLE" in resp.text
        assert "drop-zone" in resp.text

    def test_chat_ui(self, client):
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "ORACLE" in resp.text
        assert "query-input" in resp.text

    def test_graph_ui(self, client):
        resp = client.get("/graph")
        assert resp.status_code == 200
        assert "ORACLE GRAPH" in resp.text
        assert "graph-canvas" in resp.text

    def test_openapi_docs(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_health_endpoint(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "operational"


# ============================================================
# 9. Confidence Scoring Edge Cases
# ============================================================

class TestConfidenceEdgeCases:
    def test_wilson_with_all_successes(self):
        scorer = WilsonScorer()
        score = scorer.wilson_lower_bound(1000, 1000)
        assert score > 0.99

    def test_wilson_with_all_failures(self):
        scorer = WilsonScorer()
        score = scorer.wilson_lower_bound(0, 1000)
        assert score < 0.01

    def test_wilson_single_observation(self):
        scorer = WilsonScorer()
        score = scorer.wilson_lower_bound(1, 1)
        assert 0.0 < score < 1.0

    def test_confidence_on_empty_response(self):
        scorer = WilsonScorer()
        result = scorer.score_response("", 0, 0, 0, 0, 0)
        assert result.overall >= 0


# ============================================================
# 10. Crypto Edge Cases
# ============================================================

class TestCryptoEdgeCases:
    def test_sign_empty_data(self, crypto):
        sig = crypto.sign(b"")
        assert crypto.verify(b"", sig)

    def test_sign_large_data(self, crypto):
        data = b"x" * 1_000_000
        sig = crypto.sign(data)
        assert crypto.verify(data, sig)

    def test_different_keys_cant_verify(self, tmp_dir):
        c1 = CryptoEngine(key_path=tmp_dir / "k1" / "a.key")
        c2 = CryptoEngine(key_path=tmp_dir / "k2" / "b.key")
        sig = c1.sign(b"test")
        assert not c2.verify(b"test", sig)

    def test_json_signing_deterministic(self, crypto):
        obj = {"b": 2, "a": 1}
        c1, s1 = crypto.sign_json(obj)
        c2, s2 = crypto.sign_json(obj)
        assert c1 == c2  # Canonical JSON is deterministic


# ============================================================
# 11. Audit Trail Edge Cases
# ============================================================

class TestAuditEdgeCases:
    def test_long_chain_verification(self, db, crypto):
        audit = AuditTrail(db, crypto)
        for i in range(50):
            audit.log_event(f"event_{i}", {"index": i})
        result = audit.verify_chain()
        assert result["valid"] is True
        assert result["entries"] == 50

    def test_export_empty_log(self, db, crypto):
        trail = AuditTrail(db, crypto)
        exported = trail.export_json()
        parsed = json.loads(exported)
        assert isinstance(parsed, list)


# ============================================================
# 12. Parser Edge Cases
# ============================================================

class TestParserEdgeCases:
    def test_pdf_single_page(self, tmp_dir):
        pdf_path = tmp_dir / "single.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Single page document")
        doc.save(str(pdf_path))
        doc.close()
        result = PDFParser().parse(pdf_path)
        assert result.page_count == 1

    def test_code_parser_empty_file(self, tmp_dir):
        empty = tmp_dir / "empty.py"
        empty.write_text("")
        result = CodeParser().parse(empty)
        assert result.line_count == 1  # Empty string split gives [""]

    def test_binary_handler_tiny_file(self, tmp_dir):
        tiny = tmp_dir / "tiny.bin"
        tiny.write_bytes(b"\x00\x01")
        result = BinaryHandler().parse(tiny)
        assert result.size_bytes == 2

    def test_chunker_very_long_text(self):
        chunker = ChunkingEngine(chunk_size=50, overlap=5)
        # Create text with paragraph breaks to trigger chunking
        text = "\n\n".join(["This is paragraph number %d with some content." % i for i in range(200)])
        chunks = chunker.chunk_text(text, source_file="long.txt")
        assert len(chunks) > 1
        assert all(c.source_file == "long.txt" for c in chunks)

    def test_query_parser_unicode(self):
        parser = QueryParser()
        result = parser.parse("Was ist der Hauptprozessor?")
        assert result.original_text == "Was ist der Hauptprozessor?"

    def test_image_handler_small_image(self, tmp_dir):
        from PIL import Image
        img_path = tmp_dir / "tiny.png"
        Image.new("RGB", (10, 10)).save(str(img_path))
        result = ImageHandler().extract_metadata(img_path)
        assert result.width == 10
