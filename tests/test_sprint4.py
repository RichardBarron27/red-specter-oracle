"""ORACLE Sprint 4 tests — query parser, retriever, synthesiser, confidence, engine."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.graph.engine import ComponentGraph
from oracle.query.parser import QueryParser, ParsedQuery
from oracle.query.retriever import Retriever, RetrievalResult
from oracle.query.synthesiser import Synthesiser, SynthesisResult, Citation
from oracle.query.confidence import WilsonScorer, ConfidenceScore
from oracle.query.engine import QueryEngine, QueryResponse


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
    client = MagicMock(spec=OllamaClient)
    client.embed.return_value = [0.1] * 768
    client.is_available.return_value = True
    client.has_model.return_value = False
    client.config = MagicMock()
    client.config.reasoning_model = "mistral-small:24b"
    client.config.vision_model = "minicpm-v"
    client.config.embedding_model = "nomic-embed-text"
    client.generate.return_value = {
        "response": "The STM32F407VGT6 exposes SPI, I2C, UART, USB, CAN, and Ethernet interfaces. "
                    "[Source: datasheet.pdf, p.1] The SPI bus connects to the W25Q128 flash memory. "
                    "[Source: schematic.pdf, p.2]",
        "model": "mistral-small:24b",
    }
    return client


@pytest.fixture
def parser():
    return QueryParser()


@pytest.fixture
def scorer():
    return WilsonScorer()


@pytest.fixture
def populated_session(db, vector_store):
    """Session with documents, chunks, and components."""
    session = db.create_session("Sprint 4 Test")
    sid = session["session_id"]

    doc = db.add_document(sid, "datasheet.pdf", "/tmp/ds.pdf", "pdf", 1000, "hash1")

    # Add chunks to ChromaDB
    chunks = [
        ("c1", "STM32F407VGT6 ARM Cortex-M4 32-bit microcontroller. 168 MHz, 1MB Flash, 192KB SRAM. "
               "Interfaces: SPI, I2C, UART, USB OTG, CAN, Ethernet.",
         {"document_id": doc["document_id"], "source_file": "datasheet.pdf", "page": 1,
          "content_type": "text", "chunk_index": 0}),
        ("c2", "Pin Configuration: Pin 1 VDD, Pin 2 PA0 (GPIO/UART4_TX), Pin 3 PA1 (GPIO/UART4_RX).",
         {"document_id": doc["document_id"], "source_file": "datasheet.pdf", "page": 2,
          "content_type": "text", "chunk_index": 1}),
        ("c3", "SPI1 connected to W25Q128 flash memory via pins PA5 (SCK), PA6 (MISO), PA7 (MOSI).",
         {"document_id": doc["document_id"], "source_file": "schematic.pdf", "page": 2,
          "content_type": "text", "chunk_index": 2}),
    ]
    for cid, text, meta in chunks:
        vector_store.add(cid, text, [0.1] * 768, meta)

    # Add components
    mcu = db.add_component(sid, "STM32F407VGT6", "mcu", part_number="STM32F407VGT6",
                            source_doc="datasheet.pdf", source_page=1, confidence=0.95)
    flash = db.add_component(sid, "W25Q128", "memory", part_number="W25Q128",
                              source_doc="schematic.pdf", source_page=2, confidence=0.9)
    db.add_component(sid, "SPI", "protocol", source_doc="datasheet.pdf", confidence=0.95)

    db.add_relationship(sid, mcu["component_id"], flash["component_id"],
                         "CONNECTS_TO", evidence="SPI bus", source_doc="schematic.pdf")

    return {"session_id": sid, "doc": doc, "mcu": mcu, "flash": flash}


# ============================================================
# 1. Query Parser
# ============================================================

class TestQueryParser:
    def test_document_query(self, parser):
        result = parser.parse("What does the datasheet say about power consumption?")
        assert result.query_type == "DOCUMENT"

    def test_component_query(self, parser):
        result = parser.parse("Show the blast radius for the STM32F407")
        assert result.query_type in ("COMPONENT", "HYBRID")

    def test_hybrid_query(self, parser):
        result = parser.parse("What interfaces does the MCU component expose?")
        assert result.query_type in ("COMPONENT", "HYBRID")

    def test_part_number_triggers_component(self, parser):
        result = parser.parse("Tell me about the STM32F407VGT6")
        assert result.query_type in ("COMPONENT", "HYBRID")

    def test_intent_list(self, parser):
        result = parser.parse("List all interfaces on the board")
        assert result.intent == "list"

    def test_intent_explain(self, parser):
        result = parser.parse("How does the SPI bus work?")
        assert result.intent == "explain"

    def test_intent_find(self, parser):
        result = parser.parse("Find the UART configuration")
        assert result.intent == "find"

    def test_intent_trace(self, parser):
        result = parser.parse("Trace the trust chain from hardware to software")
        assert result.intent == "trace"

    def test_search_terms_extracted(self, parser):
        result = parser.parse("What interfaces does this device expose?")
        assert "interfaces" in result.search_terms
        assert "expose" in result.search_terms

    def test_stop_words_filtered(self, parser):
        result = parser.parse("What is the main MCU?")
        assert "what" not in result.search_terms
        assert "the" not in result.search_terms

    def test_original_text_preserved(self, parser):
        text = "Show me the pin configuration"
        result = parser.parse(text)
        assert result.original_text == text

    def test_simple_question(self, parser):
        result = parser.parse("What is this?")
        assert isinstance(result, ParsedQuery)
        assert result.query_type in ("DOCUMENT", "COMPONENT", "HYBRID")


# ============================================================
# 2. Retriever
# ============================================================

class TestRetriever:
    def test_retrieve_document_chunks(self, mock_ollama, vector_store, db, populated_session):
        retriever = Retriever(mock_ollama, vector_store, db)
        parsed = ParsedQuery("What interfaces?", "DOCUMENT", ["interfaces"], "list")
        result = retriever.retrieve(parsed, populated_session["session_id"])
        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) > 0

    def test_retrieve_component_query(self, mock_ollama, vector_store, db, populated_session):
        graph = ComponentGraph(db)
        graph.build_from_session(populated_session["session_id"])
        retriever = Retriever(mock_ollama, vector_store, db, graph)
        parsed = ParsedQuery("STM32F407 connections", "COMPONENT", ["STM32F407"], "describe")
        result = retriever.retrieve(parsed, populated_session["session_id"])
        assert len(result.graph_nodes) > 0 or len(result.chunks) > 0

    def test_build_context(self, mock_ollama, vector_store, db, populated_session):
        retriever = Retriever(mock_ollama, vector_store, db)
        parsed = ParsedQuery("interfaces", "DOCUMENT", ["interfaces"], "list")
        result = retriever.retrieve(parsed, populated_session["session_id"])
        context = result.build_context()
        assert "SOURCE DOCUMENTS" in context
        assert len(context) > 0

    def test_empty_session_returns_empty(self, mock_ollama, vector_store, db):
        session = db.create_session("Empty")
        retriever = Retriever(mock_ollama, vector_store, db)
        parsed = ParsedQuery("anything", "DOCUMENT", ["anything"], "describe")
        result = retriever.retrieve(parsed, session["session_id"])
        assert len(result.chunks) == 0

    def test_context_max_chars(self, mock_ollama, vector_store, db, populated_session):
        retriever = Retriever(mock_ollama, vector_store, db)
        parsed = ParsedQuery("test", "DOCUMENT", ["test"], "describe")
        result = retriever.retrieve(parsed, populated_session["session_id"])
        context = result.build_context(max_chars=100)
        assert len(context) <= 120  # Allow for truncation message


# ============================================================
# 3. Synthesiser
# ============================================================

class TestSynthesiser:
    def test_synthesise_response(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        retrieval = RetrievalResult(
            chunks=[{
                "chunk_id": "c1",
                "text": "STM32F407 has SPI, I2C, UART interfaces",
                "metadata": {"source_file": "datasheet.pdf", "page": 1},
                "relevance": 0.9,
            }],
        )
        result = synth.synthesise("What interfaces?", retrieval)
        assert isinstance(result, SynthesisResult)
        assert len(result.response_text) > 0

    def test_citations_extracted(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        retrieval = RetrievalResult(
            chunks=[{
                "chunk_id": "c1", "text": "test",
                "metadata": {"source_file": "datasheet.pdf", "page": 1},
                "relevance": 0.9,
            }],
        )
        result = synth.synthesise("test", retrieval)
        assert len(result.citations) > 0
        assert result.citations[0].source_file == "datasheet.pdf"

    def test_citation_page_extracted(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        retrieval = RetrievalResult(chunks=[{
            "chunk_id": "c1", "text": "test",
            "metadata": {"source_file": "datasheet.pdf", "page": 1},
            "relevance": 0.9,
        }])
        result = synth.synthesise("test", retrieval)
        # Mock response has [Source: datasheet.pdf, p.1]
        page_citations = [c for c in result.citations if c.page == 1]
        assert len(page_citations) > 0

    def test_unmatched_claims_detected(self, mock_ollama):
        # Response mentions specific data without citation
        mock_ollama.generate.return_value = {
            "response": "The MCU runs at 168 MHz and has 1MB Flash. The UART operates at 115200 baud.",
            "model": "test",
        }
        synth = Synthesiser(mock_ollama)
        result = synth.synthesise("test", RetrievalResult())
        assert len(result.unmatched_claims) > 0

    def test_conversation_history_included(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        history = [{"query": "What is the MCU?", "response": "STM32F407"}]
        result = synth.synthesise("What interfaces?", RetrievalResult(), history)
        # Verify generate was called with history in prompt
        call_args = mock_ollama.generate.call_args
        assert "STM32F407" in call_args.kwargs.get("prompt", "") or \
               "STM32F407" in str(call_args)

    def test_summary_generated(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        result = synth.synthesise("test", RetrievalResult())
        assert len(result.summary) > 0

    def test_response_time_tracked(self, mock_ollama):
        synth = Synthesiser(mock_ollama)
        result = synth.synthesise("test", RetrievalResult())
        assert result.response_time_ms > 0


# ============================================================
# 4. Wilson Confidence Scorer
# ============================================================

class TestWilsonScorer:
    def test_wilson_lower_bound_basic(self, scorer):
        # 95 out of 100 successes
        score = scorer.wilson_lower_bound(95, 100)
        assert 0.88 < score < 0.97

    def test_wilson_lower_bound_zero(self, scorer):
        assert scorer.wilson_lower_bound(0, 0) == 0.0

    def test_wilson_lower_bound_perfect(self, scorer):
        score = scorer.wilson_lower_bound(100, 100)
        assert score > 0.95

    def test_wilson_lower_bound_small_sample(self, scorer):
        # Small samples should have wider confidence intervals (lower bound)
        small = scorer.wilson_lower_bound(3, 3)
        large = scorer.wilson_lower_bound(300, 300)
        assert small < large  # Larger sample = tighter bound

    def test_wilson_lower_bound_50_50(self, scorer):
        score = scorer.wilson_lower_bound(50, 100)
        assert 0.39 < score < 0.51

    def test_score_response_high_confidence(self, scorer):
        result = scorer.score_response(
            response_text="The MCU is STM32F407. [Source: ds.pdf, p.1] It runs at 168 MHz. [Source: ds.pdf, p.2]",
            citations_found=2,
            total_claims=3,
            chunks_used=5,
            chunks_available=10,
            unmatched_claims=1,
        )
        assert isinstance(result, ConfidenceScore)
        assert result.accuracy > 0
        assert result.overall > 0

    def test_score_response_no_citations(self, scorer):
        result = scorer.score_response(
            response_text="The device has SPI and UART.",
            citations_found=0,
            total_claims=2,
            chunks_used=0,
            chunks_available=5,
            unmatched_claims=2,
        )
        assert result.requires_review is True
        assert result.accuracy < 0.5

    def test_score_response_honest_gap(self, scorer):
        result = scorer.score_response(
            response_text="I cannot find this in the indexed sources.",
            citations_found=0,
            total_claims=0,
            chunks_used=0,
            chunks_available=5,
            unmatched_claims=0,
        )
        assert result.requires_review is False
        assert result.accuracy > 0.8

    def test_count_factual_claims(self, scorer):
        text = "The STM32F407 runs at 168 MHz with 1MB Flash. It supports SPI and UART."
        count = scorer.count_factual_claims(text)
        assert count >= 3  # MHz, MB, SPI, UART, STM32

    def test_count_factual_claims_empty(self, scorer):
        assert scorer.count_factual_claims("No specific data here.") == 0

    def test_confidence_score_to_dict(self, scorer):
        result = scorer.score_response("test", 1, 1, 1, 1, 0)
        d = result.to_dict()
        assert "accuracy" in d
        assert "completeness" in d
        assert "confidence" in d
        assert "overall" in d
        assert "requires_review" in d

    def test_review_threshold(self, scorer):
        # Many unmatched claims should trigger review
        result = scorer.score_response(
            response_text="Lots of claims here about 168 MHz and SPI and I2C",
            citations_found=1,
            total_claims=5,
            chunks_used=2,
            chunks_available=10,
            unmatched_claims=4,
        )
        assert result.requires_review is True


# ============================================================
# 5. Query Engine
# ============================================================

class TestQueryEngine:
    def test_full_query_pipeline(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        response = engine.query(populated_session["session_id"],
                                 "What interfaces does this device expose?")
        assert isinstance(response, QueryResponse)
        assert len(response.response_text) > 0
        assert response.query_type in ("DOCUMENT", "COMPONENT", "HYBRID")
        assert "accuracy" in response.confidence

    def test_query_saved_to_db(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        engine.query(populated_session["session_id"], "Test query")
        queries = db.list_queries(populated_session["session_id"])
        assert len(queries) == 1
        assert queries[0]["response_text"] is not None

    def test_confidence_scores_saved(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        engine.query(populated_session["session_id"], "What MCU is used?")
        queries = db.list_queries(populated_session["session_id"])
        assert queries[0]["confidence_score"] is not None
        assert queries[0]["confidence_score"] > 0

    def test_follow_up_query(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        # First query
        engine.query(populated_session["session_id"], "What interfaces?")
        # Follow-up
        mock_ollama.generate.return_value = {
            "response": "Of the interfaces mentioned, none are wireless. "
                        "[Source: datasheet.pdf, p.1]",
            "model": "test",
        }
        response = engine.query(populated_session["session_id"],
                                 "Which of those are wireless?")
        assert len(response.response_text) > 0

    def test_conversation_history_in_context(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        engine.query(populated_session["session_id"], "What is the MCU?")
        engine.query(populated_session["session_id"], "What speed does it run at?")
        # Check that generate was called with history
        calls = mock_ollama.generate.call_args_list
        last_call = calls[-1]
        prompt = last_call.kwargs.get("prompt", str(last_call))
        assert "MCU" in prompt or "What is" in prompt

    def test_ollama_unavailable(self, mock_ollama, vector_store, db, populated_session):
        mock_ollama.is_available.return_value = False
        engine = QueryEngine(mock_ollama, vector_store, db)
        response = engine.query(populated_session["session_id"], "test")
        assert "not available" in response.response_text.lower()
        assert response.requires_review is True

    def test_response_to_dict(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        response = engine.query(populated_session["session_id"], "test")
        d = response.to_dict()
        assert "query_id" in d
        assert "response_text" in d
        assert "citations" in d
        assert "confidence" in d

    def test_sources_cited(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        response = engine.query(populated_session["session_id"],
                                 "What interfaces does the STM32 have?")
        assert len(response.citations) > 0
        assert any("datasheet" in c.get("source_file", "") for c in response.citations)

    def test_response_time_tracked(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        response = engine.query(populated_session["session_id"], "test")
        assert response.response_time_ms > 0


# ============================================================
# 6. Session Memory
# ============================================================

class TestSessionMemory:
    def test_session_persists_queries(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        sid = populated_session["session_id"]
        engine.query(sid, "First question")
        engine.query(sid, "Second question")
        engine.query(sid, "Third question")
        queries = db.list_queries(sid)
        assert len(queries) == 3

    def test_session_resumable(self, mock_ollama, vector_store, db, populated_session):
        sid = populated_session["session_id"]
        # First "session"
        engine1 = QueryEngine(mock_ollama, vector_store, db)
        engine1.query(sid, "Day 1 question")

        # Simulate closing and reopening (new engine, same db)
        engine2 = QueryEngine(mock_ollama, vector_store, db)
        engine2.query(sid, "Day 2 follow-up")

        queries = db.list_queries(sid)
        assert len(queries) == 2

    def test_history_includes_previous_responses(self, mock_ollama, vector_store, db, populated_session):
        engine = QueryEngine(mock_ollama, vector_store, db)
        sid = populated_session["session_id"]
        engine.query(sid, "What MCU?")
        # Second query should have history
        engine.query(sid, "What speed?")
        history = engine._get_conversation_history(sid, context_window=5)
        assert len(history) >= 1


# ============================================================
# 7. API Routes
# ============================================================

class TestQueryAPI:
    @pytest.fixture
    def client(self, config):
        config.ensure_dirs()
        from oracle.api.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(config)
        return TestClient(app)

    def test_ask_endpoint(self, client, db, vector_store):
        session = db.create_session("API Query Test")
        sid = session["session_id"]
        doc = db.add_document(sid, "test.pdf", "/tmp/test.pdf", "pdf", 100, "h")
        vector_store.add("c1", "Test content about MCU", [0.1]*768,
                          {"document_id": doc["document_id"], "source_file": "test.pdf"})
        resp = client.post(f"/api/v1/sessions/{sid}/ask",
                            json={"query": "What is the MCU?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response_text" in data
        assert "confidence" in data

    def test_list_queries_endpoint(self, client, db):
        session = db.create_session("List Test")
        resp = client.get(f"/api/v1/sessions/{session['session_id']}/queries")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_chat_ui(self, client):
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "ORACLE" in resp.text
        assert "query-input" in resp.text

    def test_ask_nonexistent_session(self, client):
        resp = client.post("/api/v1/sessions/nonexistent/ask",
                            json={"query": "test"})
        assert resp.status_code == 404


# ============================================================
# 8. Integration — MVP Milestone
# ============================================================

class TestMVPMilestone:
    def test_mvp_full_pipeline(self, mock_ollama, vector_store, db, populated_session):
        """MVP: drag in datasheet → ask question → get cited answer → follow up → session persists."""
        sid = populated_session["session_id"]
        engine = QueryEngine(mock_ollama, vector_store, db)

        # Ask: "What interfaces does this device expose?"
        r1 = engine.query(sid, "What interfaces does this device expose?")
        assert len(r1.response_text) > 0
        assert len(r1.citations) > 0
        assert "accuracy" in r1.confidence
        assert r1.confidence["overall"] > 0

        # Follow-up: "Which of those are wireless?"
        mock_ollama.generate.return_value = {
            "response": "Based on the interfaces listed (SPI, I2C, UART, USB, CAN, Ethernet), "
                        "none are wireless protocols. [Source: datasheet.pdf, p.1] "
                        "All interfaces are wired connections.",
            "model": "test",
        }
        r2 = engine.query(sid, "Which of those are wireless?")
        assert len(r2.response_text) > 0
        assert len(r2.citations) > 0

        # Session persists
        queries = db.list_queries(sid)
        assert len(queries) == 2
        assert all(q["response_text"] for q in queries)
        assert all(q["confidence_score"] is not None for q in queries)

        # Verify source citations on both responses
        for r in [r1, r2]:
            assert any("datasheet" in c.get("source_file", "") for c in r.citations)
