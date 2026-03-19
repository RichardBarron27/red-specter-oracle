"""ORACLE Sprint 1 tests — infrastructure, database, intake, API, crypto, config."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from oracle import __version__
from oracle.core.config import OracleConfig, OllamaConfig, IngestionConfig
from oracle.core.crypto import CryptoEngine
from oracle.core.banner import print_banner
from oracle.core.logger import setup_logger
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.handler import IntakeHandler, FILE_TYPES


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
def intake(config, db):
    return IntakeHandler(config, db)


@pytest.fixture
def crypto(tmp_dir):
    return CryptoEngine(key_path=tmp_dir / "keys" / "test.key")


@pytest.fixture
def vector_store(tmp_dir):
    return VectorStore(tmp_dir / "chroma")


# ============================================================
# 1. Version
# ============================================================

class TestVersion:
    def test_version_exists(self):
        assert __version__ == "1.0.0"

    def test_version_is_string(self):
        assert isinstance(__version__, str)


# ============================================================
# 2. Configuration
# ============================================================

class TestConfig:
    def test_default_config_created(self):
        config = OracleConfig()
        assert config.api_port == 8200
        assert config.api_host == "127.0.0.1"

    def test_default_dirs(self):
        config = OracleConfig()
        assert config.config_dir == Path.home() / ".oracle"
        assert config.db_path == Path.home() / ".oracle" / "oracle.db"

    def test_ollama_defaults(self):
        config = OracleConfig()
        assert "mistral" in config.ollama.reasoning_model.lower() or "mistral-small" in config.ollama.reasoning_model
        assert config.ollama.base_url == "http://localhost:11434"

    def test_ingestion_defaults(self):
        config = OracleConfig()
        assert ".pdf" in config.ingestion.supported_extensions
        assert ".py" in config.ingestion.supported_extensions
        assert ".bin" in config.ingestion.supported_extensions
        assert config.ingestion.max_file_size_mb == 500

    def test_save_and_load(self, tmp_dir):
        config = OracleConfig(
            config_dir=tmp_dir,
            db_path=tmp_dir / "test.db",
            sessions_dir=tmp_dir / "sess",
            documents_dir=tmp_dir / "docs",
            chroma_dir=tmp_dir / "chroma",
            key_path=tmp_dir / "keys" / "k.key",
        )
        saved = config.save(tmp_dir / "config.json")
        assert saved.exists()

        loaded = OracleConfig.load(tmp_dir / "config.json")
        assert loaded.api_port == 8200
        assert loaded.db_path == tmp_dir / "test.db"

    def test_ensure_dirs(self, config):
        config.ensure_dirs()
        assert config.config_dir.exists()
        assert config.sessions_dir.exists()
        assert config.documents_dir.exists()
        assert config.chroma_dir.exists()

    def test_to_dict(self, config):
        d = config.to_dict()
        assert isinstance(d, dict)
        assert "api_port" in d
        assert "ollama" in d

    def test_load_missing_file(self, tmp_dir):
        loaded = OracleConfig.load(tmp_dir / "nonexistent.json")
        assert loaded.api_port == 8200

    def test_supported_extensions_include_hardware(self):
        config = OracleConfig()
        assert ".v" in config.ingestion.supported_extensions
        assert ".vhd" in config.ingestion.supported_extensions
        assert ".sv" in config.ingestion.supported_extensions
        assert ".elf" in config.ingestion.supported_extensions
        assert ".fw" in config.ingestion.supported_extensions


# ============================================================
# 3. Database
# ============================================================

class TestDatabase:
    def test_schema_creation(self, db):
        stats = db.get_stats()
        assert stats["sessions"] == 0
        assert stats["documents"] == 0
        assert stats["queries"] == 0

    def test_create_session(self, db):
        session = db.create_session("Test Teardown")
        assert session["session_id"]
        assert session["name"] == "Test Teardown"
        assert session["status"] == "active"

    def test_get_session(self, db):
        created = db.create_session("Lookup Test")
        fetched = db.get_session(created["session_id"])
        assert fetched is not None
        assert fetched["name"] == "Lookup Test"

    def test_get_session_not_found(self, db):
        assert db.get_session("nonexistent") is None

    def test_list_sessions(self, db):
        db.create_session("Session A")
        db.create_session("Session B")
        sessions = db.list_sessions()
        assert len(sessions) == 2

    def test_update_session(self, db):
        s = db.create_session("Updatable")
        db.update_session(s["session_id"], status="archived")
        fetched = db.get_session(s["session_id"])
        assert fetched["status"] == "archived"

    def test_add_document(self, db):
        s = db.create_session("Doc Session")
        doc = db.add_document(
            session_id=s["session_id"],
            filename="datasheet.pdf",
            file_path="/tmp/datasheet.pdf",
            file_type="pdf",
            file_size=1024,
            file_hash="abc123",
        )
        assert doc["filename"] == "datasheet.pdf"
        assert doc["ingestion_status"] == "received"

    def test_get_document(self, db):
        s = db.create_session("Doc Get")
        doc = db.add_document(s["session_id"], "test.pdf", "/tmp/test.pdf", "pdf", 100, "hash1")
        fetched = db.get_document(doc["document_id"])
        assert fetched is not None
        assert fetched["filename"] == "test.pdf"

    def test_get_document_not_found(self, db):
        assert db.get_document("nonexistent") is None

    def test_list_documents(self, db):
        s = db.create_session("Multi Doc")
        db.add_document(s["session_id"], "a.pdf", "/a", "pdf", 100, "h1")
        db.add_document(s["session_id"], "b.png", "/b", "image", 200, "h2")
        docs = db.list_documents(s["session_id"])
        assert len(docs) == 2

    def test_update_document(self, db):
        s = db.create_session("Update Doc")
        doc = db.add_document(s["session_id"], "up.pdf", "/up", "pdf", 100, "h1")
        db.update_document(doc["document_id"], ingestion_status="indexed")
        fetched = db.get_document(doc["document_id"])
        assert fetched["ingestion_status"] == "indexed"

    def test_document_count(self, db):
        s = db.create_session("Count")
        assert db.get_document_count(s["session_id"]) == 0
        db.add_document(s["session_id"], "a.pdf", "/a", "pdf", 100, "h1")
        assert db.get_document_count(s["session_id"]) == 1

    def test_add_query(self, db):
        s = db.create_session("Query Session")
        q = db.add_query(s["session_id"], "What is the main MCU?")
        assert q["query_text"] == "What is the main MCU?"

    def test_update_query(self, db):
        s = db.create_session("Update Query")
        q = db.add_query(s["session_id"], "Test query")
        db.update_query(q["query_id"], response_text="STM32F4", confidence_score=0.85)
        queries = db.list_queries(s["session_id"])
        assert queries[0]["response_text"] == "STM32F4"
        assert queries[0]["confidence_score"] == 0.85

    def test_list_queries(self, db):
        s = db.create_session("List Queries")
        db.add_query(s["session_id"], "Q1")
        db.add_query(s["session_id"], "Q2")
        queries = db.list_queries(s["session_id"])
        assert len(queries) == 2

    def test_audit_log(self, db):
        db.add_audit_entry("document_received", '{"file":"test.pdf"}', "hash123")
        log = db.get_audit_log()
        assert len(log) == 1
        assert log[0]["event_type"] == "document_received"

    def test_audit_chain(self, db):
        db.add_audit_entry("event1", "{}", "hash1", None)
        db.add_audit_entry("event2", "{}", "hash2", "hash1")
        log = db.get_audit_log()
        assert len(log) == 2

    def test_stats(self, db):
        s = db.create_session("Stats")
        db.add_document(s["session_id"], "f.pdf", "/f", "pdf", 100, "h")
        db.add_query(s["session_id"], "test")
        stats = db.get_stats()
        assert stats["sessions"] == 1
        assert stats["documents"] == 1
        assert stats["queries"] == 1

    def test_session_updated_on_document_add(self, db):
        s = db.create_session("Timestamp")
        original = db.get_session(s["session_id"])["updated_at"]
        time.sleep(0.05)
        db.add_document(s["session_id"], "f.pdf", "/f", "pdf", 100, "h")
        updated = db.get_session(s["session_id"])["updated_at"]
        assert updated > original


# ============================================================
# 4. Crypto
# ============================================================

class TestCrypto:
    def test_key_generation(self, crypto):
        assert crypto.get_public_key_hex()
        assert len(crypto.get_public_key_hex()) == 64

    def test_key_persistence(self, tmp_dir):
        key_path = tmp_dir / "keys" / "persist.key"
        c1 = CryptoEngine(key_path=key_path)
        pub1 = c1.get_public_key_hex()
        c2 = CryptoEngine(key_path=key_path)
        pub2 = c2.get_public_key_hex()
        assert pub1 == pub2

    def test_sign_and_verify(self, crypto):
        data = b"test data"
        sig = crypto.sign(data)
        assert crypto.verify(data, sig)

    def test_verify_fails_wrong_data(self, crypto):
        sig = crypto.sign(b"original")
        assert not crypto.verify(b"tampered", sig)

    def test_sign_json(self, crypto):
        obj = {"key": "value", "num": 42}
        canonical, sig_hex = crypto.sign_json(obj)
        assert crypto.verify_json(canonical, sig_hex)

    def test_verify_json_fails_tampered(self, crypto):
        obj = {"key": "value"}
        _, sig_hex = crypto.sign_json(obj)
        assert not crypto.verify_json('{"key":"tampered"}', sig_hex)

    def test_hash_data(self):
        h = CryptoEngine.hash_data(b"test")
        assert len(h) == 64
        assert h == hashlib.sha256(b"test").hexdigest()

    def test_hash_chain(self):
        h1 = CryptoEngine.hash_data(b"first")
        h2 = CryptoEngine.hash_chain(h1, b"second")
        assert h2 != h1
        assert len(h2) == 64

    def test_key_file_permissions(self, tmp_dir):
        key_path = tmp_dir / "keys" / "perms.key"
        CryptoEngine(key_path=key_path)
        mode = oct(key_path.stat().st_mode)[-3:]
        assert mode == "600"

    def test_public_key_file_created(self, tmp_dir):
        key_path = tmp_dir / "keys" / "pubtest.key"
        CryptoEngine(key_path=key_path)
        assert key_path.with_suffix(".pub").exists()


# ============================================================
# 5. Intake Handler
# ============================================================

class TestIntake:
    def test_receive_pdf(self, intake, db):
        s = db.create_session("Intake Test")
        doc = intake.receive_file(s["session_id"], "datasheet.pdf", b"%PDF-1.4 test content")
        assert doc["filename"] == "datasheet.pdf"
        assert doc["file_type"] == "pdf"
        assert doc["ingestion_status"] == "received"

    def test_receive_image(self, intake, db):
        s = db.create_session("Image Test")
        doc = intake.receive_file(s["session_id"], "schematic.png", b"\x89PNG fake image")
        assert doc["file_type"] == "image"

    def test_receive_code(self, intake, db):
        s = db.create_session("Code Test")
        doc = intake.receive_file(s["session_id"], "firmware.c", b"#include <stdio.h>")
        assert doc["file_type"] == "code"

    def test_receive_binary(self, intake, db):
        s = db.create_session("Binary Test")
        doc = intake.receive_file(s["session_id"], "dump.bin", b"\x00\x01\x02\x03")
        assert doc["file_type"] == "binary"

    def test_receive_structured(self, intake, db):
        s = db.create_session("JSON Test")
        doc = intake.receive_file(s["session_id"], "config.json", b'{"key": "value"}')
        assert doc["file_type"] == "structured"

    def test_receive_text(self, intake, db):
        s = db.create_session("Text Test")
        doc = intake.receive_file(s["session_id"], "notes.txt", b"Handwritten notes transcription")
        assert doc["file_type"] == "text"

    def test_receive_verilog(self, intake, db):
        s = db.create_session("HDL Test")
        doc = intake.receive_file(s["session_id"], "fpga.v", b"module top;")
        assert doc["file_type"] == "code"

    def test_receive_firmware(self, intake, db):
        s = db.create_session("FW Test")
        doc = intake.receive_file(s["session_id"], "update.fw", b"\xDE\xAD\xBE\xEF")
        assert doc["file_type"] == "binary"

    def test_file_stored_on_disk(self, intake, db, config):
        s = db.create_session("Disk Test")
        content = b"stored content check"
        intake.receive_file(s["session_id"], "check.txt", content)
        session_dir = config.documents_dir / s["session_id"]
        assert session_dir.exists()
        files = list(session_dir.iterdir())
        assert len(files) == 1
        assert files[0].read_bytes() == content

    def test_file_hash_in_filename(self, intake, db, config):
        s = db.create_session("Hash Test")
        content = b"hash me"
        expected_hash = hashlib.sha256(content).hexdigest()[:12]
        intake.receive_file(s["session_id"], "test.pdf", content)
        session_dir = config.documents_dir / s["session_id"]
        files = list(session_dir.iterdir())
        assert expected_hash in files[0].name

    def test_reject_unsupported_extension(self, intake, db):
        s = db.create_session("Reject Test")
        with pytest.raises(ValueError, match="Unsupported"):
            intake.receive_file(s["session_id"], "malware.exe", b"bad file")

    def test_reject_oversize_file(self, intake, db):
        s = db.create_session("Size Test")
        intake.config.ingestion.max_file_size_mb = 0
        with pytest.raises(ValueError, match="too large"):
            intake.receive_file(s["session_id"], "big.pdf", b"x" * 1024)

    def test_reject_invalid_session(self, intake):
        with pytest.raises(ValueError, match="Session not found"):
            intake.receive_file("nonexistent", "test.pdf", b"data")

    def test_supported_types_list(self, intake):
        types = intake.get_supported_types()
        assert ".pdf" in types
        assert ".py" in types
        assert isinstance(types, list)

    def test_file_type_mapping_complete(self):
        config = OracleConfig()
        for ext in config.ingestion.supported_extensions:
            assert ext in FILE_TYPES, f"Missing mapping for {ext}"

    def test_multiple_files_same_session(self, intake, db):
        s = db.create_session("Multi")
        intake.receive_file(s["session_id"], "a.pdf", b"pdf content")
        intake.receive_file(s["session_id"], "b.png", b"png content")
        intake.receive_file(s["session_id"], "c.py", b"python content")
        docs = db.list_documents(s["session_id"])
        assert len(docs) == 3


# ============================================================
# 6. Ollama Client
# ============================================================

class TestOllamaClient:
    def test_client_creation(self):
        client = OllamaClient()
        assert client.config.base_url == "http://localhost:11434"
        client.close()

    def test_custom_config(self):
        config = OllamaConfig(base_url="http://custom:1234")
        client = OllamaClient(config)
        assert client.config.base_url == "http://custom:1234"
        client.close()

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_is_available_true(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.return_value = MagicMock(status_code=200)
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        assert client.is_available()

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_is_available_false(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        assert not client.is_available()

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_list_models(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"models": [{"name": "mistral-small:24b"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        models = client.list_models()
        assert len(models) == 1

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_has_model(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"models": [{"name": "mistral-small:24b"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        assert client.has_model("mistral-small")

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_model_status(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"models": [{"name": "mistral-small:24b"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        status = client.model_status()
        assert "ollama_available" in status
        assert "reasoning_model" in status

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_generate(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "The MCU is an STM32F4"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        result = client.generate("What is the main MCU?")
        assert "STM32F4" in result["response"]

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_embed(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        emb = client.embed("test text")
        assert len(emb) == 3

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_generate_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("timeout")
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        result = client.generate("test")
        assert "error" in result

    @patch("oracle.core.ollama_client.httpx.Client")
    def test_embed_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("timeout")
        mock_client_cls.return_value = mock_client
        client = OllamaClient()
        emb = client.embed("test")
        assert emb == []


# ============================================================
# 7. Vector Store
# ============================================================

class TestVectorStore:
    def test_creation(self, vector_store):
        assert vector_store.count == 0

    def test_add_and_count(self, vector_store):
        vector_store.add("doc1", "test text", [0.1] * 384, {"source": "test.pdf"})
        assert vector_store.count == 1

    def test_add_multiple(self, vector_store):
        for i in range(5):
            vector_store.add(f"doc{i}", f"text {i}", [0.1 * i] * 384)
        assert vector_store.count == 5

    def test_query(self, vector_store):
        vec1 = [1.0] + [0.0] * 383
        vec2 = [0.0] + [1.0] + [0.0] * 382
        vector_store.add("doc1", "STM32F4 datasheet", vec1, {"source": "ds.pdf"})
        vector_store.add("doc2", "power supply schematic", vec2, {"source": "sch.pdf"})
        results = vector_store.query(vec1, n_results=1)
        assert results["ids"][0][0] == "doc1"

    def test_delete(self, vector_store):
        vector_store.add("del1", "delete me", [0.5] * 384)
        assert vector_store.count == 1
        vector_store.delete("del1")
        assert vector_store.count == 0

    def test_delete_nonexistent(self, vector_store):
        vector_store.delete("nonexistent")

    def test_get_stats(self, vector_store):
        stats = vector_store.get_stats()
        assert "total_chunks" in stats
        assert "persist_dir" in stats

    def test_metadata_stored(self, vector_store):
        vector_store.add("meta1", "with metadata", [0.5] * 384, {"source": "test.pdf", "page": "3"})
        results = vector_store.query([0.5] * 384, n_results=1)
        assert results["metadatas"][0][0]["source"] == "test.pdf"


# ============================================================
# 8. Banner and Logger
# ============================================================

class TestBannerAndLogger:
    def test_banner_prints(self, capsys):
        from rich.console import Console
        c = Console(file=open(os.devnull, "w"))
        print_banner(c)

    def test_logger_creation(self, tmp_dir):
        logger = setup_logger("test_oracle", tmp_dir / "test.log")
        assert logger.name == "test_oracle"
        logger.info("test message")
        assert (tmp_dir / "test.log").exists()

    def test_logger_no_file(self):
        logger = setup_logger("test_no_file")
        assert logger.name == "test_no_file"


# ============================================================
# 9. API Routes
# ============================================================

class TestAPI:
    @pytest.fixture
    def client(self, config):
        config.ensure_dirs()
        from oracle.api.app import create_app
        app = create_app(config)
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"
        assert "database" in data
        assert "ollama" in data

    def test_create_session(self, client):
        resp = client.post("/api/v1/sessions", json={"name": "Test Teardown"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Teardown"
        assert "session_id" in data

    def test_list_sessions(self, client):
        client.post("/api/v1/sessions", json={"name": "S1"})
        client.post("/api/v1/sessions", json={"name": "S2"})
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_session(self, client):
        create = client.post("/api/v1/sessions", json={"name": "Detail"}).json()
        resp = client.get(f"/api/v1/sessions/{create['session_id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Detail"
        assert "documents" in resp.json()

    def test_get_session_not_found(self, client):
        resp = client.get("/api/v1/sessions/nonexistent")
        assert resp.status_code == 404

    def test_upload_document(self, client):
        session = client.post("/api/v1/sessions", json={"name": "Upload"}).json()
        resp = client.post(
            f"/api/v1/sessions/{session['session_id']}/documents",
            files={"file": ("test.pdf", b"%PDF content", "application/pdf")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.pdf"
        assert data["ingestion_status"] == "received"

    def test_upload_multiple_documents(self, client):
        session = client.post("/api/v1/sessions", json={"name": "Multi Upload"}).json()
        sid = session["session_id"]
        client.post(f"/api/v1/sessions/{sid}/documents",
                     files={"file": ("a.pdf", b"pdf", "application/pdf")})
        client.post(f"/api/v1/sessions/{sid}/documents",
                     files={"file": ("b.png", b"png", "image/png")})
        resp = client.get(f"/api/v1/sessions/{sid}/documents")
        assert len(resp.json()) == 2

    def test_upload_unsupported_type(self, client):
        session = client.post("/api/v1/sessions", json={"name": "Bad Type"}).json()
        resp = client.post(
            f"/api/v1/sessions/{session['session_id']}/documents",
            files={"file": ("malware.exe", b"bad", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_to_nonexistent_session(self, client):
        resp = client.post(
            "/api/v1/sessions/nonexistent/documents",
            files={"file": ("test.pdf", b"pdf", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_get_document(self, client):
        session = client.post("/api/v1/sessions", json={"name": "Get Doc"}).json()
        doc = client.post(
            f"/api/v1/sessions/{session['session_id']}/documents",
            files={"file": ("detail.pdf", b"content", "application/pdf")},
        ).json()
        resp = client.get(f"/api/v1/documents/{doc['document_id']}")
        assert resp.status_code == 200
        assert resp.json()["filename"] == "detail.pdf"

    def test_get_document_not_found(self, client):
        resp = client.get("/api/v1/documents/nonexistent")
        assert resp.status_code == 404

    def test_stats(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "database" in data
        assert "vector_store" in data

    def test_ollama_status(self, client):
        resp = client.get("/api/v1/ollama/status")
        assert resp.status_code == 200

    def test_intake_ui(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ORACLE" in resp.text
        assert "drop-zone" in resp.text

    def test_query_placeholder(self, client):
        session = client.post("/api/v1/sessions", json={"name": "Query Test"}).json()
        resp = client.post(
            f"/api/v1/sessions/{session['session_id']}/query",
            json={"query": "What is the main MCU?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_text"] == "What is the main MCU?"

    def test_query_nonexistent_session(self, client):
        resp = client.post(
            "/api/v1/sessions/nonexistent/query",
            json={"query": "test"},
        )
        assert resp.status_code == 404


# ============================================================
# 10. Integration — End-to-End Flow
# ============================================================

class TestIntegration:
    def test_full_intake_flow(self, config, db, intake):
        """Session → upload multiple files → verify all stored."""
        session = db.create_session("Full Flow Test")
        sid = session["session_id"]

        files = [
            ("datasheet.pdf", b"%PDF-1.4 STM32F4 datasheet content"),
            ("schematic.png", b"\x89PNG schematic data"),
            ("firmware.c", b'#include "stm32f4xx.h"\nvoid main() {}'),
            ("config.json", b'{"mcu": "STM32F407VGT6"}'),
            ("dump.bin", b"\x08\x00\x00\x20\x00\x01\x00\x08"),
        ]

        for name, content in files:
            doc = intake.receive_file(sid, name, content)
            assert doc["ingestion_status"] == "received"

        docs = db.list_documents(sid)
        assert len(docs) == 5

        types = {d["file_type"] for d in docs}
        assert types == {"pdf", "image", "code", "structured", "binary"}

        stats = db.get_stats()
        assert stats["documents"] == 5

    def test_session_isolation(self, config, db, intake):
        """Documents in one session don't leak to another."""
        s1 = db.create_session("Session 1")
        s2 = db.create_session("Session 2")
        intake.receive_file(s1["session_id"], "s1.pdf", b"session 1 data")
        intake.receive_file(s2["session_id"], "s2.pdf", b"session 2 data")
        assert len(db.list_documents(s1["session_id"])) == 1
        assert len(db.list_documents(s2["session_id"])) == 1

    def test_crypto_signs_audit_data(self, crypto, db):
        """Crypto engine can sign audit entries."""
        db.add_audit_entry("test_event", '{"action":"test"}', "hash1")
        log = db.get_audit_log()
        canonical, sig = crypto.sign_json({"event": log[0]["event_type"]})
        assert crypto.verify_json(canonical, sig)
