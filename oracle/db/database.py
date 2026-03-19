"""ORACLE SQLite database — sessions, documents, queries."""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'received',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    response_text TEXT,
    confidence_score REAL,
    sources TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    response_time_ms REAL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL,
    timestamp REAL NOT NULL,
    hash TEXT NOT NULL,
    previous_hash TEXT
);

CREATE TABLE IF NOT EXISTS components (
    component_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    part_number TEXT,
    manufacturer TEXT,
    version TEXT,
    layer TEXT DEFAULT 'hardware',
    source_doc TEXT,
    source_page INTEGER,
    confidence REAL DEFAULT 0.5,
    metadata TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_component TEXT NOT NULL,
    target_component TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    evidence TEXT,
    source_doc TEXT,
    confidence REAL DEFAULT 0.5,
    metadata TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (source_component) REFERENCES components(component_id),
    FOREIGN KEY (target_component) REFERENCES components(component_id)
);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    graph_data TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_session ON documents(session_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(ingestion_status);
CREATE INDEX IF NOT EXISTS idx_queries_session ON queries(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_components_session ON components(session_id);
CREATE INDEX IF NOT EXISTS idx_components_type ON components(component_type);
CREATE INDEX IF NOT EXISTS idx_components_name ON components(name);
CREATE INDEX IF NOT EXISTS idx_relationships_session ON relationships(session_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_component);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_component);
"""


class Database:
    """ORACLE SQLite database manager."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- Sessions ---

    def create_session(self, name: str) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            "INSERT INTO sessions (session_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, name, now, now),
        )
        self._conn.commit()
        return {"session_id": session_id, "name": name, "created_at": now, "status": "active"}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id: str, **kwargs: Any) -> None:
        kwargs["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        self._conn.execute(
            f"UPDATE sessions SET {sets} WHERE session_id = ?", vals
        )
        self._conn.commit()

    # --- Documents ---

    def add_document(
        self,
        session_id: str,
        filename: str,
        file_path: str,
        file_type: str,
        file_size: int,
        file_hash: str,
    ) -> dict[str, Any]:
        document_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO documents
            (document_id, session_id, filename, file_path, file_type, file_size, file_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, session_id, filename, file_path, file_type, file_size, file_hash, now, now),
        )
        self._conn.commit()
        self.update_session(session_id)
        return {
            "document_id": document_id,
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "ingestion_status": "received",
        }

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_document(self, document_id: str, **kwargs: Any) -> None:
        kwargs["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [document_id]
        self._conn.execute(
            f"UPDATE documents SET {sets} WHERE document_id = ?", vals
        )
        self._conn.commit()

    def get_document_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # --- Queries ---

    def add_query(self, session_id: str, query_text: str) -> dict[str, Any]:
        query_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            "INSERT INTO queries (query_id, session_id, query_text, created_at) VALUES (?, ?, ?, ?)",
            (query_id, session_id, query_text, now),
        )
        self._conn.commit()
        self.update_session(session_id)
        return {"query_id": query_id, "query_text": query_text, "created_at": now}

    def update_query(self, query_id: str, **kwargs: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [query_id]
        self._conn.execute(
            f"UPDATE queries SET {sets} WHERE query_id = ?", vals
        )
        self._conn.commit()

    def list_queries(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM queries WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Audit ---

    def add_audit_entry(self, event_type: str, event_data: str, entry_hash: str, previous_hash: str | None = None) -> None:
        audit_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO audit_log (audit_id, event_type, event_data, timestamp, hash, previous_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (audit_id, event_type, event_data, time.time(), entry_hash, previous_hash),
        )
        self._conn.commit()

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Components ---

    def add_component(
        self,
        session_id: str,
        name: str,
        component_type: str,
        part_number: str | None = None,
        manufacturer: str | None = None,
        version: str | None = None,
        layer: str = "hardware",
        source_doc: str | None = None,
        source_page: int | None = None,
        confidence: float = 0.5,
        metadata: str = "{}",
    ) -> dict[str, Any]:
        component_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO components
            (component_id, session_id, name, component_type, part_number, manufacturer,
             version, layer, source_doc, source_page, confidence, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (component_id, session_id, name, component_type, part_number, manufacturer,
             version, layer, source_doc, source_page, confidence, metadata, now),
        )
        self._conn.commit()
        return {
            "component_id": component_id, "name": name, "component_type": component_type,
            "part_number": part_number, "manufacturer": manufacturer, "version": version,
            "layer": layer, "confidence": confidence,
        }

    def get_component(self, component_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM components WHERE component_id = ?", (component_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_components(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM components WHERE session_id = ? ORDER BY name",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_component_by_name(self, session_id: str, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM components WHERE session_id = ? AND name = ?",
            (session_id, name),
        ).fetchone()
        return dict(row) if row else None

    # --- Relationships ---

    def add_relationship(
        self,
        session_id: str,
        source_component: str,
        target_component: str,
        relationship_type: str,
        evidence: str | None = None,
        source_doc: str | None = None,
        confidence: float = 0.5,
        metadata: str = "{}",
    ) -> dict[str, Any]:
        relationship_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO relationships
            (relationship_id, session_id, source_component, target_component,
             relationship_type, evidence, source_doc, confidence, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (relationship_id, session_id, source_component, target_component,
             relationship_type, evidence, source_doc, confidence, metadata, now),
        )
        self._conn.commit()
        return {
            "relationship_id": relationship_id,
            "source_component": source_component,
            "target_component": target_component,
            "relationship_type": relationship_type,
            "confidence": confidence,
        }

    def list_relationships(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relationships WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Graph Snapshots ---

    def save_graph_snapshot(self, session_id: str, graph_data: str) -> str:
        snapshot_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            "INSERT INTO graph_snapshots (snapshot_id, session_id, graph_data, created_at) VALUES (?, ?, ?, ?)",
            (snapshot_id, session_id, graph_data, now),
        )
        self._conn.commit()
        return snapshot_id

    def get_latest_graph_snapshot(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM graph_snapshots WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    # --- Stats ---

    def get_stats(self) -> dict[str, Any]:
        sessions = self._conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()["cnt"]
        documents = self._conn.execute("SELECT COUNT(*) as cnt FROM documents").fetchone()["cnt"]
        queries = self._conn.execute("SELECT COUNT(*) as cnt FROM queries").fetchone()["cnt"]
        components = self._conn.execute("SELECT COUNT(*) as cnt FROM components").fetchone()["cnt"]
        relationships = self._conn.execute("SELECT COUNT(*) as cnt FROM relationships").fetchone()["cnt"]
        return {
            "sessions": sessions, "documents": documents, "queries": queries,
            "components": components, "relationships": relationships,
        }
