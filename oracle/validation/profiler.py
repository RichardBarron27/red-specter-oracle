"""ORACLE Researcher Profiling Engine — adapts responses to researcher preferences."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from typing import Any

from oracle.db.database import Database

logger = logging.getLogger("oracle.validation.profiler")


class ResearcherProfiler:
    """Build and maintain a researcher profile from query history."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_profile_table()

    def _ensure_profile_table(self) -> None:
        self.db._conn.execute("""
            CREATE TABLE IF NOT EXISTS researcher_profile (
                profile_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                detail_level TEXT DEFAULT 'detailed',
                preferred_format TEXT DEFAULT 'technical',
                top_component_types TEXT DEFAULT '[]',
                top_query_intents TEXT DEFAULT '[]',
                query_count INTEGER DEFAULT 0,
                avg_response_length INTEGER DEFAULT 0,
                updated_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        self.db._conn.commit()

    def update_profile(self, session_id: str, query_text: str,
                       response_text: str, query_type: str = "") -> dict[str, Any]:
        """Update researcher profile based on latest interaction."""
        profile = self._get_or_create(session_id)
        profile_id = profile["profile_id"]

        # Analyse query patterns
        queries = self.db.list_queries(session_id)
        query_count = len(queries)

        # Detect preferred detail level
        avg_len = sum(len(q.get("response_text") or "") for q in queries) // max(query_count, 1)
        detail_level = "summary" if avg_len < 200 else "detailed" if avg_len < 800 else "comprehensive"

        # Top component types queried
        type_counter = Counter()
        intent_counter = Counter()
        for q in queries:
            text = (q.get("query_text") or "").lower()
            meta = {}
            try:
                meta = json.loads(q.get("metadata") or "{}")
            except:
                pass

            if "mcu" in text or "microcontroller" in text:
                type_counter["mcu"] += 1
            if "interface" in text or "spi" in text or "uart" in text or "i2c" in text:
                type_counter["interface"] += 1
            if "pin" in text or "pinout" in text:
                type_counter["connector"] += 1
            if "firmware" in text or "software" in text:
                type_counter["firmware"] += 1
            if "power" in text or "voltage" in text:
                type_counter["power"] += 1

            qt = meta.get("query_type", "DOCUMENT")
            intent_counter[qt] += 1

        top_types = [t for t, _ in type_counter.most_common(5)]
        top_intents = [t for t, _ in intent_counter.most_common(3)]

        # Update
        self.db._conn.execute("""
            UPDATE researcher_profile SET
                detail_level = ?, preferred_format = ?, top_component_types = ?,
                top_query_intents = ?, query_count = ?, avg_response_length = ?,
                updated_at = ?
            WHERE profile_id = ?
        """, (detail_level, "technical", json.dumps(top_types),
              json.dumps(top_intents), query_count, avg_len,
              time.time(), profile_id))
        self.db._conn.commit()

        return self.get_profile(session_id)

    def get_profile(self, session_id: str) -> dict[str, Any] | None:
        row = self.db._conn.execute(
            "SELECT * FROM researcher_profile WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row:
            d = dict(row)
            d["top_component_types"] = json.loads(d.get("top_component_types", "[]"))
            d["top_query_intents"] = json.loads(d.get("top_query_intents", "[]"))
            return d
        return None

    def _get_or_create(self, session_id: str) -> dict[str, Any]:
        existing = self.get_profile(session_id)
        if existing:
            return existing

        profile_id = str(uuid.uuid4())
        now = time.time()
        self.db._conn.execute(
            """INSERT INTO researcher_profile
            (profile_id, session_id, updated_at) VALUES (?, ?, ?)""",
            (profile_id, session_id, now),
        )
        self.db._conn.commit()
        return {"profile_id": profile_id, "session_id": session_id}

    def get_system_prompt_modifier(self, session_id: str) -> str:
        """Generate a system prompt modifier based on researcher profile."""
        profile = self.get_profile(session_id)
        if not profile or profile.get("query_count", 0) < 3:
            return ""

        parts = []
        detail = profile.get("detail_level", "detailed")
        if detail == "summary":
            parts.append("The researcher prefers concise summaries. Keep responses brief.")
        elif detail == "comprehensive":
            parts.append("The researcher prefers comprehensive detail. Include all relevant specifications.")

        top_types = profile.get("top_component_types", [])
        if top_types:
            parts.append(f"The researcher frequently queries about: {', '.join(top_types)}.")

        return " ".join(parts)
