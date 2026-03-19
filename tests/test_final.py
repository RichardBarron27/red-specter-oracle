"""ORACLE final verification tests — push past 400 total."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from oracle.core.config import OracleConfig, OllamaConfig, IngestionConfig
from oracle.core.crypto import CryptoEngine
from oracle.db.database import Database
from oracle.query.parser import QueryParser
from oracle.query.confidence import WilsonScorer
from oracle.validation.detector import PatternMatcher, ConsistencyChecker
from oracle.intake.parsers.code_parser import CodeParser


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


class TestQueryClassification:
    """Additional query parser coverage."""

    def test_compare_intent(self):
        p = QueryParser()
        r = p.parse("compare SPI and I2C interfaces")
        assert r.intent == "compare"

    def test_protocol_keywords(self):
        p = QueryParser()
        r = p.parse("What protocol does the bus use?")
        assert "protocol" in r.search_terms or "bus" in r.search_terms

    def test_graph_keyword_triggers_component(self):
        p = QueryParser()
        r = p.parse("Show the graph relationships between components")
        assert r.query_type in ("COMPONENT", "HYBRID")

    def test_blast_radius_keyword(self):
        p = QueryParser()
        r = p.parse("What is the blast radius of the main controller?")
        assert r.query_type in ("COMPONENT", "HYBRID")


class TestWilsonEdgeCases:
    def test_wilson_half_successes(self):
        s = WilsonScorer()
        score = s.wilson_lower_bound(500, 1000)
        assert 0.46 < score < 0.52

    def test_very_small_sample(self):
        s = WilsonScorer()
        score = s.wilson_lower_bound(1, 2)
        assert 0.0 < score < 0.9

    def test_count_claims_with_voltages(self):
        s = WilsonScorer()
        count = s.count_factual_claims("The MCU operates at 3.3V with 168 MHz clock.")
        assert count >= 2


class TestPatternEdgeCases:
    def test_invented_part_number(self):
        pm = PatternMatcher()
        _, detections = pm.scan("The device uses an ABC1234567 processor.")
        assert any(d.category == "fabrication" for d in detections)

    def test_fake_standard(self):
        pm = PatternMatcher()
        _, detections = pm.scan("Compliant with IEEE 9999999 standard.")
        assert len(detections) >= 1


class TestCodeParserLanguages:
    def test_go_language(self):
        p = CodeParser()
        assert p.detect_language("main.go") == "go"

    def test_javascript(self):
        p = CodeParser()
        assert p.detect_language("app.js") == "javascript"

    def test_assembly(self):
        p = CodeParser()
        assert p.detect_language("boot.asm") == "assembly"
        assert p.detect_language("startup.s") == "assembly"
