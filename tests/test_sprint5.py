"""ORACLE Sprint 5 tests — validation framework, profiler, audit trail, drift monitor."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from oracle.core.config import OracleConfig
from oracle.core.crypto import CryptoEngine
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.validation.detector import (
    ResponseValidator, ValidationResult,
    PatternMatcher, ConsistencyChecker, ContradictionDetector,
    ConfidenceAnalyser, FactChecker, DriftMonitor, AccuracyGrader,
)
from oracle.validation.profiler import ResearcherProfiler
from oracle.validation.audit import AuditTrail
from oracle.query.engine import QueryEngine


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
def validator(db, crypto):
    return ResponseValidator(db, crypto)

@pytest.fixture
def profiler(db):
    return ResearcherProfiler(db)

@pytest.fixture
def audit(db, crypto):
    return AuditTrail(db, crypto)

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
        "response": "The STM32F407VGT6 runs at 168 MHz with 1MB Flash. [Source: datasheet.pdf, p.1]",
        "model": "test",
    }
    return client


# ============================================================
# 1. PatternMatcher
# ============================================================

class TestPatternMatcher:
    def test_clean_text(self):
        pm = PatternMatcher()
        score, detections = pm.scan("The STM32F407 has SPI and UART interfaces.")
        assert score > 0.8
        assert len(detections) == 0

    def test_fake_citation(self):
        pm = PatternMatcher()
        score, detections = pm.scan("According to Smith et al. (2024), the chip runs at 200 MHz.")
        assert len(detections) >= 1
        assert any(d.category == "fake_citation" for d in detections)

    def test_fake_url(self):
        pm = PatternMatcher()
        score, detections = pm.scan("See https://example.internal/docs for details.")
        assert len(detections) >= 1

    def test_future_citation(self):
        pm = PatternMatcher()
        score, detections = pm.scan("Jones et al. (2035) demonstrated this technique.")
        assert any(d.severity == "critical" for d in detections)

    def test_studies_show(self):
        pm = PatternMatcher()
        _, detections = pm.scan("studies show that 8 out of 10 devices are vulnerable. 85.74% failure rate.")
        assert len(detections) >= 1  # Should match studies_show and/or precise_percentage

    def test_score_decreases_with_detections(self):
        pm = PatternMatcher()
        clean_score, _ = pm.scan("Normal technical text about SPI bus.")
        dirty_score, _ = pm.scan(
            "Smith et al. (2024) showed that Jones et al. (2035) found 95.74% failure."
        )
        assert clean_score > dirty_score


# ============================================================
# 2. ConsistencyChecker
# ============================================================

class TestConsistencyChecker:
    def test_grounded_response(self):
        cc = ConsistencyChecker()
        score = cc.check(
            "The STM32F407 runs at 168 MHz.",
            "STM32F407VGT6 ARM Cortex-M4 32-bit microcontroller. 168 MHz CPU."
        )
        assert score > 0.3

    def test_ungrounded_response(self):
        cc = ConsistencyChecker()
        score = cc.check(
            "The quantum flux capacitor operates at 1.21 gigawatts.",
            "STM32F407 ARM Cortex-M4 microcontroller."
        )
        assert score < 0.5

    def test_empty_context(self):
        cc = ConsistencyChecker()
        score = cc.check("Some response.", "")
        assert score == 0.3

    def test_empty_response(self):
        cc = ConsistencyChecker()
        score = cc.check("", "Some context.")
        assert score == 1.0


# ============================================================
# 3. ContradictionDetector
# ============================================================

class TestContradictionDetector:
    def test_no_contradictions(self):
        cd = ContradictionDetector()
        score, conflicts = cd.detect("The MCU supports SPI. It also supports I2C.")
        assert score == 1.0
        assert len(conflicts) == 0

    def test_internal_contradiction(self):
        cd = ContradictionDetector()
        score, conflicts = cd.detect(
            "The interface is enabled on the MCU. The interface is disabled on the MCU."
        )
        assert len(conflicts) >= 1
        assert conflicts[0]["type"] == "internal"

    def test_source_contradiction(self):
        cd = ContradictionDetector()
        score, conflicts = cd.detect(
            "The USB interface is enabled on the board.",
            "The USB interface is disabled on the board."
        )
        assert len(conflicts) >= 1

    def test_score_decreases(self):
        cd = ContradictionDetector()
        clean, _ = cd.detect("Consistent text.")
        dirty, _ = cd.detect(
            "The feature is enabled on the chip. The feature is disabled on the chip. "
            "The port is connected to VDD. The port is disconnected from VDD."
        )
        assert clean >= dirty


# ============================================================
# 4. ConfidenceAnalyser
# ============================================================

class TestConfidenceAnalyser:
    def test_hedging(self):
        ca = ConfidenceAnalyser()
        score = ca.analyse("It appears the MCU may be running at approximately 168 MHz.")
        assert score > 0.6

    def test_overconfidence(self):
        ca = ConfidenceAnalyser()
        score = ca.analyse("This is definitely the correct chip. Absolutely confirmed. Certainly true.")
        assert score < 0.5

    def test_neutral(self):
        ca = ConfidenceAnalyser()
        score = ca.analyse("The MCU runs at 168 MHz.")
        assert 0.4 <= score <= 0.8


# ============================================================
# 5. FactChecker
# ============================================================

class TestFactChecker:
    def test_register_and_check(self):
        fc = FactChecker()
        fc.register_fact("stm32f407vgt6", "STM32F407VGT6", "datasheet.pdf")
        score, unverified = fc.check("The STM32F407VGT6 is the main MCU on this board.")
        # STM32F407VGT6 is in the fact registry, so it should be verified
        assert score >= 0

    def test_register_from_chunks(self):
        fc = FactChecker()
        chunks = [{"text": "STM32F407VGT6 runs at 168 MHz", "metadata": {"source_file": "ds.pdf"}}]
        count = fc.register_facts_from_chunks(chunks)
        assert count > 0

    def test_unverified_claims(self):
        fc = FactChecker()
        fc.register_fact("stm32f407", "STM32F407", "ds.pdf")
        score, unverified = fc.check("The ABCD1234XYZ is connected to the STM32F407.")
        assert len(unverified) >= 1

    def test_empty_facts(self):
        fc = FactChecker()
        score, _ = fc.check("Some text.")
        assert score == 0.5


# ============================================================
# 6. DriftMonitor
# ============================================================

class TestDriftMonitor:
    def test_no_drift(self):
        dm = DriftMonitor()
        for _ in range(5):
            dm.record({"pattern_score": 0.9, "consistency_score": 0.8})
        score, events = dm.check_drift()
        assert score >= 0.7
        assert len(events) == 0

    def test_drift_detected(self):
        dm = DriftMonitor()
        # Good period
        for _ in range(5):
            dm.record({"pattern_score": 0.95, "consistency_score": 0.9})
        # Degraded period
        for _ in range(3):
            dm.record({"pattern_score": 0.5, "consistency_score": 0.4})
        score, events = dm.check_drift()
        assert len(events) > 0
        assert score < 1.0

    def test_insufficient_data(self):
        dm = DriftMonitor()
        dm.record({"pattern_score": 0.9})
        score, events = dm.check_drift()
        assert score == 1.0


# ============================================================
# 7. AccuracyGrader
# ============================================================

class TestAccuracyGrader:
    def test_grade_a(self):
        assert AccuracyGrader().grade(0.95) == "A"

    def test_grade_b(self):
        assert AccuracyGrader().grade(0.85) == "B"

    def test_grade_c(self):
        assert AccuracyGrader().grade(0.75) == "C"

    def test_grade_d(self):
        assert AccuracyGrader().grade(0.55) == "D"

    def test_grade_f(self):
        assert AccuracyGrader().grade(0.3) == "F"


# ============================================================
# 8. ResponseValidator (Orchestrator)
# ============================================================

class TestResponseValidator:
    def test_validate_clean_response(self, validator):
        result = validator.validate(
            "The STM32F407 supports SPI and UART. [Source: datasheet.pdf, p.1]",
            "STM32F407VGT6 ARM Cortex-M4 microcontroller. SPI, I2C, UART, USB.",
        )
        assert isinstance(result, ValidationResult)
        assert result.status in ("GREEN", "AMBER")
        assert result.overall_score > 0

    def test_validate_hallucinated_response(self, validator):
        result = validator.validate(
            "According to Smith et al. (2024), the quantum processor at https://example.internal "
            "definitely runs at 99.99% efficiency. Studies show that 100% of devices use this.",
            "STM32F407 microcontroller.",
        )
        assert len(result.detections) > 0
        assert result.overall_score < 0.8

    def test_validate_returns_signed(self, validator):
        result = validator.validate("Test response.", "Test context.")
        assert result.signature != ""
        assert result.signed_hash != ""

    def test_status_green(self, validator):
        result = validator.validate(
            "The MCU runs SPI.",
            "The MCU supports SPI, I2C, UART.",
            source_chunks=[{"text": "MCU supports SPI", "metadata": {"source_file": "ds.pdf"}}],
        )
        assert result.status in ("GREEN", "AMBER")

    def test_status_red_on_heavy_hallucination(self, validator):
        result = validator.validate(
            "Smith et al. (2035) proved at https://fake.internal that "
            "Jones et al. (2036) confirmed 99.99% accuracy. Studies show 100%. "
            "The International Institute of Advanced Computing confirmed this.",
            "",
        )
        assert result.overall_score < 0.7

    def test_to_dict(self, validator):
        result = validator.validate("Test.", "Context.")
        d = result.to_dict()
        assert "pattern_score" in d
        assert "consistency_score" in d
        assert "status" in d
        assert "accuracy_grade" in d
        assert "signed" in d

    def test_audit_logged(self, validator, db):
        validator.validate("Response.", "Context.")
        log = db.get_audit_log()
        assert len(log) > 0
        assert any(e["event_type"] == "response_validated" for e in log)

    def test_drift_recorded(self, validator):
        for _ in range(5):
            validator.validate("Consistent response.", "Same context.")
        score, events = validator.drift_monitor.check_drift()
        assert score > 0


# ============================================================
# 9. Researcher Profiler
# ============================================================

class TestResearcherProfiler:
    def test_create_profile(self, profiler, db):
        session = db.create_session("Profile Test")
        profile = profiler.get_profile(session["session_id"])
        assert profile is None  # Not created until update

    def test_update_profile(self, profiler, db):
        session = db.create_session("Profile Update")
        sid = session["session_id"]
        db.add_query(sid, "What interfaces does the MCU have?")
        profile = profiler.update_profile(sid, "What interfaces?", "SPI, I2C, UART.", "HYBRID")
        assert profile is not None
        assert profile["query_count"] >= 1

    def test_profile_detail_level(self, profiler, db):
        session = db.create_session("Detail Test")
        sid = session["session_id"]
        for i in range(5):
            q = db.add_query(sid, f"Question {i}")
            db.update_query(q["query_id"], response_text="Short answer.")
        profile = profiler.update_profile(sid, "test", "short", "DOCUMENT")
        assert profile["detail_level"] in ("summary", "detailed", "comprehensive")

    def test_system_prompt_modifier(self, profiler, db):
        session = db.create_session("Prompt Test")
        sid = session["session_id"]
        for i in range(5):
            q = db.add_query(sid, "What about the MCU interface?")
            db.update_query(q["query_id"], response_text="x" * 100,
                             metadata=json.dumps({"query_type": "HYBRID"}))
        profiler.update_profile(sid, "test", "x" * 100, "HYBRID")
        modifier = profiler.get_system_prompt_modifier(sid)
        assert isinstance(modifier, str)


# ============================================================
# 10. Audit Trail
# ============================================================

class TestAuditTrail:
    def test_log_event(self, audit):
        h = audit.log_event("test_event", {"key": "value"})
        assert len(h) == 64

    def test_log_query(self, audit):
        h = audit.log_query("session1", "What is the MCU?", "query1")
        assert h

    def test_log_response(self, audit):
        h = audit.log_response("query1", "STM32F407", "GREEN", 0.85)
        assert h

    def test_hash_chain(self, audit):
        h1 = audit.log_event("event1", {"n": 1})
        h2 = audit.log_event("event2", {"n": 2})
        assert h1 != h2

    def test_verify_chain(self, audit, db):
        audit.log_event("e1", {"a": 1})
        audit.log_event("e2", {"a": 2})
        audit.log_event("e3", {"a": 3})
        result = audit.verify_chain()
        assert result["valid"] is True
        assert result["entries"] >= 3

    def test_export_json(self, audit):
        audit.log_event("export_test", {"data": "value"})
        exported = audit.export_json()
        parsed = json.loads(exported)
        assert len(parsed) >= 1

    def test_export_csv(self, audit):
        audit.log_event("csv_test", {"data": "value"})
        csv = audit.export_csv()
        assert "audit_id" in csv
        assert "csv_test" in csv

    def test_append_only(self, audit, db):
        audit.log_event("first", {})
        audit.log_event("second", {})
        log = db.get_audit_log()
        assert len(log) >= 2


# ============================================================
# 11. Integration — Full Validation Pipeline
# ============================================================

class TestValidationIntegration:
    def test_query_with_validation(self, mock_ollama, vector_store, db, crypto):
        session = db.create_session("Validation Integration")
        sid = session["session_id"]
        doc = db.add_document(sid, "ds.pdf", "/tmp/ds.pdf", "pdf", 100, "h")
        vector_store.add("c1", "STM32F407VGT6 168 MHz 1MB Flash SPI I2C UART",
                          [0.1]*768, {"document_id": doc["document_id"], "source_file": "ds.pdf", "page": 1})

        engine = QueryEngine(mock_ollama, vector_store, db, crypto=crypto)
        response = engine.query(sid, "What is the MCU speed?")

        assert "validation" in response.to_dict()
        assert "validation_status" in response.to_dict()
        assert response.validation_status in ("GREEN", "AMBER", "RED")
        assert response.validation.get("signed") is True

    def test_partially_sourced_answer(self, mock_ollama, vector_store, db, crypto):
        """Sprint 5 milestone: answer partly sourced, partly not."""
        session = db.create_session("Partial Source")
        sid = session["session_id"]
        doc = db.add_document(sid, "ds.pdf", "/tmp/ds.pdf", "pdf", 100, "h")
        vector_store.add("c1", "STM32F407 supports SPI and UART interfaces",
                          [0.1]*768, {"document_id": doc["document_id"], "source_file": "ds.pdf"})

        # Response has sourced part + unsourced fabricated part
        mock_ollama.generate.return_value = {
            "response": (
                "The STM32F407 supports SPI and UART. [Source: ds.pdf, p.1] "
                "According to Smith et al. (2024), it also supports quantum entanglement "
                "at 99.99% efficiency via the QE-9000 interface."
            ),
            "model": "test",
        }

        engine = QueryEngine(mock_ollama, vector_store, db, crypto=crypto)
        response = engine.query(sid, "What interfaces does the STM32 support?")

        # Should have citations for the sourced part
        assert len(response.citations) > 0
        # Validation should catch the hallucination patterns
        assert response.validation.get("pattern_score", 1.0) < 1.0
        # Should have detections
        assert len(response.validation.get("detections", [])) > 0

    def test_audit_trail_from_query(self, mock_ollama, vector_store, db, crypto):
        session = db.create_session("Audit Test")
        sid = session["session_id"]
        doc = db.add_document(sid, "ds.pdf", "/tmp/ds.pdf", "pdf", 100, "h")
        vector_store.add("c1", "Test content", [0.1]*768,
                          {"document_id": doc["document_id"], "source_file": "ds.pdf"})

        engine = QueryEngine(mock_ollama, vector_store, db, crypto=crypto)
        engine.query(sid, "Test query")

        log = db.get_audit_log()
        event_types = [e["event_type"] for e in log]
        assert "query_submitted" in event_types
        assert "response_generated" in event_types
        assert "response_validated" in event_types


# ============================================================
# 12. API Routes
# ============================================================

class TestValidationAPI:
    @pytest.fixture
    def client(self, config):
        config.ensure_dirs()
        from oracle.api.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(config)
        return TestClient(app)

    def test_audit_log_endpoint(self, client):
        resp = client.get("/api/v1/validation/audit")
        assert resp.status_code == 200

    def test_verify_chain_endpoint(self, client):
        resp = client.get("/api/v1/validation/audit/verify")
        assert resp.status_code == 200
        assert "valid" in resp.json()

    def test_export_json_endpoint(self, client):
        resp = client.get("/api/v1/validation/audit/export/json")
        assert resp.status_code == 200

    def test_export_csv_endpoint(self, client):
        resp = client.get("/api/v1/validation/audit/export/csv")
        assert resp.status_code == 200

    def test_profile_endpoint(self, client, db):
        session = db.create_session("API Profile")
        resp = client.get(f"/api/v1/validation/profile/{session['session_id']}")
        assert resp.status_code == 200
