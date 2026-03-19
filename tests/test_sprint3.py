"""ORACLE Sprint 3 tests — component graph, extractor, relationships, trust chain."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.graph.engine import ComponentGraph, BlastRadiusResult, LAYER_ORDER
from oracle.graph.extractor import ComponentExtractor


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
    client.is_available.return_value = False
    client.has_model.return_value = False
    client.config = MagicMock()
    client.config.vision_model = "minicpm-v"
    client.config.embedding_model = "nomic-embed-text"
    return client


@pytest.fixture
def graph(db):
    return ComponentGraph(db)


@pytest.fixture
def extractor(mock_ollama, vector_store, db):
    return ComponentExtractor(mock_ollama, vector_store, db)


@pytest.fixture
def populated_session(db):
    """Session with components and relationships already added."""
    session = db.create_session("Test Teardown")
    sid = session["session_id"]

    # Hardware layer
    mcu = db.add_component(sid, "STM32F407VGT6", "mcu", part_number="STM32F407VGT6",
                            manufacturer="STMicroelectronics", layer="hardware",
                            source_doc="datasheet.pdf", source_page=1, confidence=0.95)
    flash = db.add_component(sid, "W25Q128", "memory", part_number="W25Q128JVSIQ",
                              manufacturer="Winbond", layer="hardware",
                              source_doc="datasheet.pdf", source_page=3, confidence=0.9)
    eth_phy = db.add_component(sid, "LAN8720A", "ic", part_number="LAN8720A",
                                manufacturer="Microchip", layer="hardware",
                                source_doc="schematic.pdf", source_page=2, confidence=0.85)
    usb_conn = db.add_component(sid, "USB Type-C", "connector", layer="hardware",
                                 source_doc="schematic.pdf", source_page=1, confidence=0.8)
    power = db.add_component(sid, "AMS1117-3.3", "power", part_number="AMS1117-3.3",
                              manufacturer="AMS", layer="hardware",
                              source_doc="schematic.pdf", source_page=4, confidence=0.9)

    # Firmware/software layer
    fw = db.add_component(sid, "STM32 HAL", "firmware", version="1.27.1",
                           manufacturer="STMicroelectronics", layer="firmware",
                           source_doc="firmware.c", confidence=0.7)
    rtos = db.add_component(sid, "FreeRTOS", "os", version="10.5.1", layer="os",
                             source_doc="config.json", confidence=0.8)
    lwip = db.add_component(sid, "lwIP", "library", version="2.1.3", layer="application",
                             source_doc="firmware.c", confidence=0.7)

    # Protocols
    spi = db.add_component(sid, "SPI", "protocol", layer="protocol",
                            source_doc="datasheet.pdf", source_page=5, confidence=0.95)
    uart = db.add_component(sid, "UART", "protocol", layer="protocol",
                             source_doc="datasheet.pdf", source_page=6, confidence=0.95)

    # Relationships
    db.add_relationship(sid, mcu["component_id"], flash["component_id"],
                         "CONNECTS_TO", evidence="SPI Flash connected to SPI1",
                         source_doc="schematic.pdf", confidence=0.9)
    db.add_relationship(sid, mcu["component_id"], eth_phy["component_id"],
                         "CONNECTS_TO", evidence="RMII interface to LAN8720A",
                         source_doc="schematic.pdf", confidence=0.85)
    db.add_relationship(sid, mcu["component_id"], usb_conn["component_id"],
                         "CONNECTS_TO", evidence="USB OTG FS to Type-C",
                         source_doc="schematic.pdf", confidence=0.8)
    db.add_relationship(sid, power["component_id"], mcu["component_id"],
                         "CONTROLS", evidence="3.3V power rail to MCU",
                         source_doc="schematic.pdf", confidence=0.9)
    db.add_relationship(sid, fw["component_id"], mcu["component_id"],
                         "RUNS_ON", evidence="HAL firmware runs on STM32F407",
                         source_doc="firmware.c", confidence=0.7)
    db.add_relationship(sid, rtos["component_id"], fw["component_id"],
                         "DEPENDS_ON", evidence="FreeRTOS uses HAL drivers",
                         source_doc="config.json", confidence=0.8)
    db.add_relationship(sid, lwip["component_id"], rtos["component_id"],
                         "RUNS_ON", evidence="lwIP stack runs on FreeRTOS",
                         source_doc="firmware.c", confidence=0.7)
    db.add_relationship(sid, mcu["component_id"], spi["component_id"],
                         "COMMUNICATES_VIA", evidence="SPI1 peripheral",
                         source_doc="datasheet.pdf", confidence=0.95)
    db.add_relationship(sid, mcu["component_id"], uart["component_id"],
                         "COMMUNICATES_VIA", evidence="USART1 debug console",
                         source_doc="datasheet.pdf", confidence=0.9)

    return {
        "session_id": sid,
        "mcu": mcu, "flash": flash, "eth_phy": eth_phy, "usb_conn": usb_conn,
        "power": power, "fw": fw, "rtos": rtos, "lwip": lwip,
        "spi": spi, "uart": uart,
    }


# ============================================================
# 1. Database — Components & Relationships
# ============================================================

class TestDatabaseGraph:
    def test_add_component(self, db):
        session = db.create_session("Test")
        comp = db.add_component(session["session_id"], "STM32F4", "mcu",
                                 part_number="STM32F407VGT6")
        assert comp["name"] == "STM32F4"
        assert comp["component_type"] == "mcu"

    def test_get_component(self, db):
        session = db.create_session("Test")
        comp = db.add_component(session["session_id"], "W25Q128", "memory")
        fetched = db.get_component(comp["component_id"])
        assert fetched["name"] == "W25Q128"

    def test_list_components(self, db):
        session = db.create_session("Test")
        db.add_component(session["session_id"], "MCU", "mcu")
        db.add_component(session["session_id"], "Flash", "memory")
        comps = db.list_components(session["session_id"])
        assert len(comps) == 2

    def test_find_component_by_name(self, db):
        session = db.create_session("Test")
        db.add_component(session["session_id"], "STM32F407", "mcu")
        found = db.find_component_by_name(session["session_id"], "STM32F407")
        assert found is not None
        assert found["name"] == "STM32F407"

    def test_find_component_not_found(self, db):
        session = db.create_session("Test")
        assert db.find_component_by_name(session["session_id"], "nonexistent") is None

    def test_add_relationship(self, db):
        session = db.create_session("Test")
        c1 = db.add_component(session["session_id"], "MCU", "mcu")
        c2 = db.add_component(session["session_id"], "Flash", "memory")
        rel = db.add_relationship(session["session_id"],
                                   c1["component_id"], c2["component_id"],
                                   "CONNECTS_TO", evidence="SPI bus")
        assert rel["relationship_type"] == "CONNECTS_TO"

    def test_list_relationships(self, db):
        session = db.create_session("Test")
        c1 = db.add_component(session["session_id"], "MCU", "mcu")
        c2 = db.add_component(session["session_id"], "Flash", "memory")
        db.add_relationship(session["session_id"], c1["component_id"],
                             c2["component_id"], "CONNECTS_TO")
        rels = db.list_relationships(session["session_id"])
        assert len(rels) == 1

    def test_save_graph_snapshot(self, db):
        session = db.create_session("Test")
        snap_id = db.save_graph_snapshot(session["session_id"], '{"nodes":[],"edges":[]}')
        assert snap_id

    def test_get_latest_snapshot(self, db):
        session = db.create_session("Test")
        db.save_graph_snapshot(session["session_id"], '{"v":1}')
        db.save_graph_snapshot(session["session_id"], '{"v":2}')
        latest = db.get_latest_graph_snapshot(session["session_id"])
        assert latest is not None
        assert '"v":2' in latest["graph_data"] or '"v": 2' in latest["graph_data"]

    def test_stats_include_components(self, db):
        session = db.create_session("Test")
        db.add_component(session["session_id"], "MCU", "mcu")
        stats = db.get_stats()
        assert stats["components"] == 1
        assert stats["relationships"] == 0


# ============================================================
# 2. Component Graph Engine
# ============================================================

class TestComponentGraph:
    def test_build_from_session(self, graph, populated_session):
        stats = graph.build_from_session(populated_session["session_id"])
        assert stats["nodes"] == 10
        assert stats["edges"] == 9

    def test_node_count(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        assert graph.node_count == 10

    def test_edge_count(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        assert graph.edge_count == 9

    def test_components_by_type(self, graph, populated_session):
        stats = graph.build_from_session(populated_session["session_id"])
        by_type = stats["components_by_type"]
        assert by_type["mcu"] == 1
        assert by_type["memory"] == 1
        assert by_type["protocol"] == 2

    def test_components_by_layer(self, graph, populated_session):
        stats = graph.build_from_session(populated_session["session_id"])
        by_layer = stats["components_by_layer"]
        assert by_layer["hardware"] == 5
        assert by_layer["firmware"] == 1
        assert by_layer["os"] == 1

    def test_blast_radius_mcu(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        mcu_id = populated_session["mcu"]["component_id"]
        result = graph.calculate_blast_radius(mcu_id)
        assert isinstance(result, BlastRadiusResult)
        assert result.component_name == "STM32F407VGT6"
        assert result.directly_connected > 0
        assert result.transitively_reachable > 0

    def test_blast_radius_peripheral(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        flash_id = populated_session["flash"]["component_id"]
        result = graph.calculate_blast_radius(flash_id)
        # Flash is a leaf — smaller blast radius
        assert result.transitively_reachable < 10

    def test_blast_radius_nonexistent(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        result = graph.calculate_blast_radius("nonexistent")
        assert result.directly_connected == 0

    def test_critical_nodes(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        critical = graph.get_critical_nodes(top_n=3)
        assert len(critical) > 0
        # MCU should be most central (most connections)
        assert critical[0]["name"] == "STM32F407VGT6"
        assert critical[0]["centrality_score"] > 0

    def test_trust_chain(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        chain = graph.get_trust_chain()
        assert "layers" in chain
        assert "cross_layer_edges" in chain
        assert "hardware" in chain["layers"]
        assert len(chain["layers"]["hardware"]) == 5

    def test_trust_chain_cross_layer_edges(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        chain = graph.get_trust_chain()
        # firmware → hardware should be a cross-layer edge
        assert len(chain["cross_layer_edges"]) > 0

    def test_trust_chain_unverified_links(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        chain = graph.get_trust_chain()
        assert "unverified_links" in chain

    def test_version_conflicts_none(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        conflicts = graph.get_version_conflicts()
        assert len(conflicts) == 0

    def test_to_dict(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        data = graph.to_dict()
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert len(data["nodes"]) == 10

    def test_to_json(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        j = graph.to_json()
        parsed = json.loads(j)
        assert "nodes" in parsed

    def test_node_has_colour(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        data = graph.to_dict()
        for node in data["nodes"]:
            assert "colour" in node

    def test_edge_has_relationship_type(self, graph, populated_session):
        graph.build_from_session(populated_session["session_id"])
        data = graph.to_dict()
        for edge in data["edges"]:
            assert "relationship_type" in edge

    def test_empty_session(self, graph, db):
        session = db.create_session("Empty")
        stats = graph.build_from_session(session["session_id"])
        assert stats["nodes"] == 0
        assert stats["edges"] == 0

    def test_snapshot_saved(self, graph, populated_session, db):
        graph.build_from_session(populated_session["session_id"])
        snap = db.get_latest_graph_snapshot(populated_session["session_id"])
        assert snap is not None
        data = json.loads(snap["graph_data"])
        assert len(data["nodes"]) == 10


# ============================================================
# 3. Component Extractor
# ============================================================

class TestComponentExtractor:
    def test_regex_extraction(self, extractor):
        text = "The board uses an STM32F407VGT6 MCU connected via SPI to a W25Q128 flash chip. Debug via UART."
        results = extractor._extract_with_regex(text)
        names = [r["name"] for r in results]
        assert "STM32F407VGT6" in names
        assert "SPI" in names
        assert "UART" in names

    def test_regex_extraction_protocols(self, extractor):
        text = "Interfaces include I2C, SPI, JTAG, and USB."
        results = extractor._extract_with_regex(text)
        names = [r["name"] for r in results]
        assert "I2C" in names
        assert "JTAG" in names

    def test_regex_extraction_empty(self, extractor):
        results = extractor._extract_with_regex("No components here.")
        assert len(results) == 0

    def test_regex_relationship_extraction(self, extractor):
        text = "The STM32F407VGT6 communicates with the W25Q128 via SPI."
        components = ["STM32F407VGT6", "W25Q128", "SPI"]
        rels = extractor._extract_relationships_with_regex(text, components)
        assert len(rels) > 0
        assert rels[0]["type"] == "CONNECTS_TO"

    def test_regex_relationship_no_components(self, extractor):
        text = "Nothing relevant here."
        rels = extractor._extract_relationships_with_regex(text, ["STM32F407"])
        assert len(rels) == 0

    def test_parse_json_response_array(self, extractor):
        response = '[{"name": "STM32F4", "type": "mcu"}]'
        result = extractor._parse_json_response(response)
        assert len(result) == 1
        assert result[0]["name"] == "STM32F4"

    def test_parse_json_response_with_markdown(self, extractor):
        response = '```json\n[{"name": "STM32F4", "type": "mcu"}]\n```'
        result = extractor._parse_json_response(response)
        assert len(result) == 1

    def test_parse_json_response_empty(self, extractor):
        assert extractor._parse_json_response("") == []
        assert extractor._parse_json_response("[]") == []

    def test_parse_json_response_invalid(self, extractor):
        assert extractor._parse_json_response("not json at all") == []

    def test_parse_json_response_single_object(self, extractor):
        response = '{"name": "MCU", "type": "mcu"}'
        result = extractor._parse_json_response(response)
        assert len(result) == 1

    def test_extract_components_no_chunks(self, extractor, db):
        session = db.create_session("Empty")
        result = extractor.extract_components(session["session_id"])
        assert len(result) == 0

    def test_extract_components_with_chunks(self, extractor, db, vector_store, mock_ollama):
        session = db.create_session("With Chunks")
        sid = session["session_id"]
        # Add a document and a chunk to ChromaDB
        doc = db.add_document(sid, "ds.pdf", "/tmp/ds.pdf", "pdf", 100, "hash1")
        vector_store.add("chunk1", "STM32F407VGT6 ARM Cortex-M4 with SPI and UART",
                          [0.1] * 768, {"document_id": doc["document_id"], "source_file": "ds.pdf"})
        result = extractor.extract_components(sid, use_llm=False)
        names = [c["name"] for c in result]
        assert "STM32F407VGT6" in names

    def test_extract_deduplicates(self, extractor, db, vector_store):
        session = db.create_session("Dedup")
        sid = session["session_id"]
        doc = db.add_document(sid, "ds.pdf", "/tmp/ds.pdf", "pdf", 100, "hash1")
        # Two chunks mentioning same component
        vector_store.add("c1", "STM32F407VGT6 MCU datasheet",
                          [0.1] * 768, {"document_id": doc["document_id"], "source_file": "ds.pdf"})
        vector_store.add("c2", "The STM32F407VGT6 supports USB OTG",
                          [0.2] * 768, {"document_id": doc["document_id"], "source_file": "ds.pdf"})
        result = extractor.extract_components(sid, use_llm=False)
        stm_count = sum(1 for c in result if c["name"] == "STM32F407VGT6")
        assert stm_count == 1


# ============================================================
# 4. API Routes
# ============================================================

class TestGraphAPI:
    @pytest.fixture
    def client(self, config):
        config.ensure_dirs()
        from oracle.api.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(config)
        return TestClient(app)

    def test_list_components_empty(self, client, db):
        session = db.create_session("API Test")
        resp = client.get(f"/api/v1/graph/sessions/{session['session_id']}/components")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_component_not_found(self, client):
        resp = client.get("/api/v1/graph/components/nonexistent")
        assert resp.status_code == 404

    def test_build_graph(self, client, db):
        session = db.create_session("Build Test")
        sid = session["session_id"]
        db.add_component(sid, "MCU", "mcu")
        db.add_component(sid, "Flash", "memory")
        resp = client.post(f"/api/v1/graph/sessions/{sid}/build")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == 2

    def test_get_graph_data(self, client, db):
        session = db.create_session("Data Test")
        sid = session["session_id"]
        db.add_component(sid, "MCU", "mcu")
        client.post(f"/api/v1/graph/sessions/{sid}/build")
        resp = client.get(f"/api/v1/graph/sessions/{sid}/data")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data

    def test_get_critical_nodes(self, client, db):
        session = db.create_session("Critical Test")
        sid = session["session_id"]
        c1 = db.add_component(sid, "MCU", "mcu")
        c2 = db.add_component(sid, "Flash", "memory")
        db.add_relationship(sid, c1["component_id"], c2["component_id"], "CONNECTS_TO")
        client.post(f"/api/v1/graph/sessions/{sid}/build")
        resp = client.get(f"/api/v1/graph/sessions/{sid}/critical-nodes")
        assert resp.status_code == 200

    def test_get_trust_chain(self, client, db):
        session = db.create_session("Trust Test")
        sid = session["session_id"]
        db.add_component(sid, "MCU", "mcu", layer="hardware")
        db.add_component(sid, "FW", "firmware", layer="firmware")
        resp = client.get(f"/api/v1/graph/sessions/{sid}/trust-chain")
        assert resp.status_code == 200
        data = resp.json()
        assert "layers" in data

    def test_graph_ui(self, client):
        resp = client.get("/graph")
        assert resp.status_code == 200
        assert "ORACLE GRAPH" in resp.text
        assert "graph-canvas" in resp.text

    def test_list_relationships(self, client, db):
        session = db.create_session("Rel Test")
        resp = client.get(f"/api/v1/graph/sessions/{session['session_id']}/relationships")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_extract_components_endpoint(self, client, db):
        session = db.create_session("Extract Test")
        resp = client.post(f"/api/v1/graph/sessions/{session['session_id']}/extract?use_llm=false")
        assert resp.status_code == 200

    def test_version_conflicts(self, client, db):
        session = db.create_session("Conflict Test")
        resp = client.get(f"/api/v1/graph/sessions/{session['session_id']}/version-conflicts")
        assert resp.status_code == 200


# ============================================================
# 5. Integration — Full Graph Pipeline
# ============================================================

class TestGraphIntegration:
    def test_full_graph_pipeline(self, db, graph, populated_session):
        """Build graph → query centrality → blast radius → trust chain."""
        sid = populated_session["session_id"]

        # Build
        stats = graph.build_from_session(sid)
        assert stats["nodes"] == 10
        assert stats["edges"] == 9

        # Critical nodes — MCU should be most central
        critical = graph.get_critical_nodes(top_n=3)
        assert critical[0]["name"] == "STM32F407VGT6"

        # Blast radius for MCU
        mcu_id = populated_session["mcu"]["component_id"]
        blast = graph.calculate_blast_radius(mcu_id)
        assert blast.directly_connected >= 5  # connects to flash, eth, usb, spi, uart + power
        assert blast.transitively_reachable > 0

        # Trust chain
        chain = graph.get_trust_chain()
        assert len(chain["layers"]["hardware"]) == 5
        assert len(chain["layers"]["firmware"]) == 1
        assert len(chain["layers"]["os"]) == 1
        assert len(chain["cross_layer_edges"]) > 0

        # Graph data for visualisation
        data = graph.to_dict()
        assert len(data["nodes"]) == 10
        assert all("colour" in n for n in data["nodes"])
        assert all("relationship_type" in e for e in data["edges"])

    def test_graph_with_source_citations(self, db, graph, populated_session):
        """Every node and edge should cite its source document."""
        graph.build_from_session(populated_session["session_id"])
        data = graph.to_dict()

        for node in data["nodes"]:
            assert node.get("source_doc"), f"Node {node['name']} missing source_doc"

        for edge in data["edges"]:
            assert edge.get("source_doc") or edge.get("evidence"), \
                f"Edge {edge['source']} → {edge['target']} missing source citation"
