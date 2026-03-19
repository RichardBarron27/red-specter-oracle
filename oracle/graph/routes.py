"""ORACLE Graph API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.graph.engine import ComponentGraph
from oracle.graph.extractor import ComponentExtractor

graph_router = APIRouter(prefix="/api/v1/graph")

_db: Database | None = None
_graph: ComponentGraph | None = None
_extractor: ComponentExtractor | None = None


def init_graph_routes(
    db: Database,
    ollama: OllamaClient,
    vector_store: VectorStore,
) -> None:
    """Initialise graph route dependencies."""
    global _db, _graph, _extractor
    _db = db
    _graph = ComponentGraph(db)
    _extractor = ComponentExtractor(ollama, vector_store, db)


# --- Build ---

@graph_router.post("/sessions/{session_id}/extract")
def extract_components(session_id: str, use_llm: bool = True) -> dict[str, Any]:
    """Extract components from indexed documents."""
    if not _extractor:
        raise HTTPException(status_code=503, detail="Extractor not initialised")
    components = _extractor.extract_components(session_id, use_llm=use_llm)
    return {"session_id": session_id, "components_extracted": len(components), "components": components}


@graph_router.post("/sessions/{session_id}/map-relationships")
def map_relationships(session_id: str) -> dict[str, Any]:
    """Extract relationships between components."""
    if not _extractor:
        raise HTTPException(status_code=503, detail="Extractor not initialised")
    rels = _extractor.extract_relationships(session_id)
    return {"session_id": session_id, "relationships_extracted": len(rels), "relationships": rels}


@graph_router.post("/sessions/{session_id}/build")
def build_graph(session_id: str) -> dict[str, Any]:
    """Build the component graph from extracted data."""
    if not _graph:
        raise HTTPException(status_code=503, detail="Graph engine not initialised")
    stats = _graph.build_from_session(session_id)
    return {"session_id": session_id, **stats}


# --- Query ---

@graph_router.get("/sessions/{session_id}/components")
def list_components(session_id: str) -> list[dict[str, Any]]:
    """List all components in a session."""
    if not _db:
        raise HTTPException(status_code=503)
    return _db.list_components(session_id)


@graph_router.get("/components/{component_id}")
def get_component(component_id: str) -> dict[str, Any]:
    """Get full component detail."""
    if not _db:
        raise HTTPException(status_code=503)
    comp = _db.get_component(component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Component not found")
    return comp


@graph_router.get("/sessions/{session_id}/relationships")
def list_relationships(session_id: str) -> list[dict[str, Any]]:
    """List all relationships in a session."""
    if not _db:
        raise HTTPException(status_code=503)
    return _db.list_relationships(session_id)


@graph_router.get("/sessions/{session_id}/trust-chain")
def get_trust_chain(session_id: str) -> dict[str, Any]:
    """Get the full trust chain view."""
    if not _graph:
        raise HTTPException(status_code=503)
    _graph.build_from_session(session_id)
    return _graph.get_trust_chain(session_id)


@graph_router.get("/components/{component_id}/blast-radius")
def get_blast_radius(component_id: str, session_id: str) -> dict[str, Any]:
    """Calculate blast radius for a component."""
    if not _graph or not _db:
        raise HTTPException(status_code=503)
    comp = _db.get_component(component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Component not found")
    _graph.build_from_session(comp["session_id"])
    result = _graph.calculate_blast_radius(component_id)
    return result.to_dict()


@graph_router.get("/sessions/{session_id}/critical-nodes")
def get_critical_nodes(session_id: str, top_n: int = 10) -> list[dict[str, Any]]:
    """Get highest centrality components."""
    if not _graph:
        raise HTTPException(status_code=503)
    _graph.build_from_session(session_id)
    return _graph.get_critical_nodes(top_n)


@graph_router.get("/sessions/{session_id}/version-conflicts")
def get_version_conflicts(session_id: str) -> list[dict[str, Any]]:
    """Find components with conflicting versions."""
    if not _graph:
        raise HTTPException(status_code=503)
    _graph.build_from_session(session_id)
    return _graph.get_version_conflicts()


@graph_router.get("/sessions/{session_id}/data")
def get_graph_data(session_id: str) -> dict[str, Any]:
    """Get full graph data for visualisation."""
    if not _graph:
        raise HTTPException(status_code=503)
    _graph.build_from_session(session_id)
    return _graph.to_dict()
