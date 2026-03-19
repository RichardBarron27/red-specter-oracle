"""ORACLE FastAPI routes."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.handler import IntakeHandler
from oracle.intake.engine import IngestionEngine
from oracle.query.engine import QueryEngine


class SessionCreate(BaseModel):
    name: str


class QueryRequest(BaseModel):
    query: str


router = APIRouter(prefix="/api/v1")

# These get set during app startup
_db: Database | None = None
_config: OracleConfig | None = None
_ollama: OllamaClient | None = None
_vector_store: VectorStore | None = None
_intake: IntakeHandler | None = None
_ingestion: IngestionEngine | None = None
_query_engine: QueryEngine | None = None


def init_routes(
    db: Database,
    config: OracleConfig,
    ollama: OllamaClient,
    vector_store: VectorStore,
    intake: IntakeHandler,
    ingestion: IngestionEngine | None = None,
    query_engine: QueryEngine | None = None,
) -> None:
    """Initialise route dependencies."""
    global _db, _config, _ollama, _vector_store, _intake, _ingestion, _query_engine
    _db = db
    _config = config
    _ollama = ollama
    _vector_store = vector_store
    _intake = intake
    _ingestion = ingestion
    _query_engine = query_engine


# --- Health ---

@router.get("/health")
def health() -> dict[str, Any]:
    """System health check."""
    stats = _db.get_stats() if _db else {}
    ollama_status = _ollama.model_status() if _ollama else {}
    vector_stats = _vector_store.get_stats() if _vector_store else {}
    return {
        "status": "operational",
        "timestamp": time.time(),
        "database": stats,
        "ollama": ollama_status,
        "vector_store": vector_stats,
    }


# --- Sessions ---

@router.post("/sessions")
def create_session(body: SessionCreate) -> dict[str, Any]:
    """Create a new research session."""
    return _db.create_session(body.name)


@router.get("/sessions")
def list_sessions() -> list[dict[str, Any]]:
    """List all research sessions."""
    return _db.list_sessions()


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    """Get session details."""
    session = _db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["documents"] = _db.list_documents(session_id)
    session["document_count"] = len(session["documents"])
    session["query_count"] = len(_db.list_queries(session_id))
    return session


# --- Documents ---

@router.post("/sessions/{session_id}/documents")
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a document to a session."""
    if not _intake:
        raise HTTPException(status_code=503, detail="Intake not initialised")
    content = await file.read()
    try:
        doc = _intake.receive_file(
            session_id=session_id,
            filename=file.filename or "unnamed",
            content=content,
        )
        return doc
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}/documents")
def list_documents(session_id: str) -> list[dict[str, Any]]:
    """List documents in a session."""
    return _db.list_documents(session_id)


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict[str, Any]:
    """Get document details."""
    doc = _db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# --- Ingestion ---

@router.post("/documents/{document_id}/ingest")
def ingest_document(document_id: str) -> dict[str, Any]:
    """Trigger ingestion (parse, chunk, embed) for a document."""
    if not _ingestion:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialised")
    doc = _db.get_document(document_id) if _db else None
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        result = _ingestion.ingest_document(document_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/ingest-all")
def ingest_all_documents(session_id: str) -> dict[str, Any]:
    """Trigger ingestion for all documents in a session."""
    if not _ingestion or not _db:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialised")
    docs = _db.list_documents(session_id)
    if not docs:
        raise HTTPException(status_code=404, detail="No documents found")

    results = []
    for doc in docs:
        if doc["ingestion_status"] in ("received", "failed"):
            try:
                result = _ingestion.ingest_document(doc["document_id"])
                results.append({"document_id": doc["document_id"], "status": "success", **result})
            except Exception as e:
                results.append({"document_id": doc["document_id"], "status": "error", "error": str(e)})

    return {"session_id": session_id, "documents_processed": len(results), "results": results}


@router.post("/search")
def search_chunks(body: QueryRequest, n_results: int = 5) -> dict[str, Any]:
    """Raw similarity search against the vector store."""
    if not _ingestion:
        raise HTTPException(status_code=503, detail="Ingestion engine not initialised")
    results = _ingestion.embedder.search(body.query, n_results=n_results)
    return {"query": body.query, "results": results, "count": len(results)}


# --- Queries ---

@router.post("/sessions/{session_id}/ask")
def ask_query(session_id: str, body: QueryRequest) -> dict[str, Any]:
    """Submit a natural language query with full RAG pipeline."""
    if not _db:
        raise HTTPException(status_code=503)
    session = _db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not _query_engine:
        raise HTTPException(status_code=503, detail="Query engine not initialised")

    response = _query_engine.query(session_id, body.query)
    return response.to_dict()


@router.post("/sessions/{session_id}/query")
def submit_query_legacy(session_id: str, body: QueryRequest) -> dict[str, Any]:
    """Submit a query (legacy endpoint — redirects to /ask)."""
    return ask_query(session_id, body)


@router.get("/sessions/{session_id}/queries")
def list_session_queries(session_id: str) -> list[dict[str, Any]]:
    """List all queries and responses for a session."""
    if not _db:
        raise HTTPException(status_code=503)
    return _db.list_queries(session_id)


# --- Ollama Status ---

@router.get("/ollama/status")
def ollama_status() -> dict[str, Any]:
    """Check Ollama and model status."""
    if not _ollama:
        return {"error": "Ollama client not initialised"}
    return _ollama.model_status()


# --- Stats ---

@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """Get system statistics."""
    db_stats = _db.get_stats() if _db else {}
    vector_stats = _vector_store.get_stats() if _vector_store else {}
    return {
        "database": db_stats,
        "vector_store": vector_stats,
        "timestamp": time.time(),
    }
