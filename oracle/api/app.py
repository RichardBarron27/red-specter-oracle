"""ORACLE FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from oracle import __version__
from oracle.api.routes import init_routes, router
from oracle.api.ui import INTAKE_HTML
from oracle.graph.routes import graph_router, init_graph_routes
from oracle.graph.ui import GRAPH_HTML
from oracle.core.config import OracleConfig
from oracle.core.ollama_client import OllamaClient
from oracle.core.vector_store import VectorStore
from oracle.db.database import Database
from oracle.intake.handler import IntakeHandler
from oracle.intake.engine import IngestionEngine
from oracle.graph.engine import ComponentGraph
from oracle.core.crypto import CryptoEngine
from oracle.query.engine import QueryEngine
from oracle.query.ui import CHAT_HTML
from oracle.validation.routes import validation_router, init_validation_routes
from oracle.validation.audit import AuditTrail
from oracle.validation.profiler import ResearcherProfiler


def create_app(config: OracleConfig | None = None) -> FastAPI:
    """Create and configure the ORACLE FastAPI application."""
    config = config or OracleConfig()
    config.ensure_dirs()

    app = FastAPI(
        title="ORACLE",
        description="Offline Research Assistant for Component-Level Exploitation Analysis",
        version=__version__,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialise core components
    db = Database(config.db_path)
    ollama = OllamaClient(config.ollama)
    vector_store = VectorStore(config.chroma_dir)
    intake = IntakeHandler(config, db)
    ingestion = IngestionEngine(
        ollama=ollama,
        vector_store=vector_store,
        db=db,
        image_output_dir=config.documents_dir / "_images",
    )

    crypto = CryptoEngine(key_path=config.key_path)
    component_graph = ComponentGraph(db)
    query_engine = QueryEngine(
        ollama=ollama,
        vector_store=vector_store,
        db=db,
        graph=component_graph,
        crypto=crypto,
    )

    audit = AuditTrail(db, crypto)
    profiler = ResearcherProfiler(db)

    init_routes(db, config, ollama, vector_store, intake, ingestion, query_engine)
    init_graph_routes(db, ollama, vector_store)
    init_validation_routes(db, audit, profiler)
    app.include_router(router)
    app.include_router(graph_router)
    app.include_router(validation_router)

    @app.get("/", response_class=HTMLResponse)
    def intake_ui():
        return INTAKE_HTML

    @app.get("/chat", response_class=HTMLResponse)
    def chat_ui():
        return CHAT_HTML

    @app.get("/graph", response_class=HTMLResponse)
    def graph_ui():
        return GRAPH_HTML

    @app.on_event("shutdown")
    def shutdown():
        db.close()
        ollama.close()

    return app
