"""ORACLE Audit Trail — hardened, append-only, Ed25519 signed."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from oracle.core.crypto import CryptoEngine
from oracle.db.database import Database

logger = logging.getLogger("oracle.validation.audit")


class AuditTrail:
    """Hardened audit trail with Ed25519 signatures and hash chaining."""

    def __init__(self, db: Database, crypto: CryptoEngine | None = None):
        self.db = db
        self.crypto = crypto or CryptoEngine()
        self._last_hash: str | None = None

        # Get last hash for chain continuity
        log = db.get_audit_log(limit=1)
        if log:
            self._last_hash = log[0].get("hash")

    def log_event(
        self,
        event_type: str,
        data: dict[str, Any],
        actor: str = "system",
    ) -> str:
        """Log an event with signature and hash chain."""
        event_data = {
            "actor": actor,
            "timestamp": time.time(),
            **data,
        }
        event_json = json.dumps(event_data, sort_keys=True)

        # Hash chain
        data_bytes = event_json.encode()
        if self._last_hash:
            entry_hash = CryptoEngine.hash_chain(self._last_hash, data_bytes)
        else:
            entry_hash = CryptoEngine.hash_data(data_bytes)

        # Sign
        _, sig = self.crypto.sign_json({"hash": entry_hash, "event": event_type})

        self.db.add_audit_entry(
            event_type=event_type,
            event_data=event_json,
            entry_hash=entry_hash,
            previous_hash=self._last_hash,
        )

        self._last_hash = entry_hash
        return entry_hash

    def log_query(self, session_id: str, query_text: str, query_id: str) -> str:
        return self.log_event("query_submitted", {
            "session_id": session_id,
            "query_id": query_id,
            "query_text": query_text[:500],
        }, actor="researcher")

    def log_response(self, query_id: str, response_summary: str,
                     validation_status: str, confidence: float) -> str:
        return self.log_event("response_generated", {
            "query_id": query_id,
            "summary": response_summary[:200],
            "validation_status": validation_status,
            "confidence": round(confidence, 3),
        })

    def log_validation(self, query_id: str, result: dict[str, Any]) -> str:
        return self.log_event("response_validated", {
            "query_id": query_id,
            "status": result.get("status", "unknown"),
            "grade": result.get("accuracy_grade", "?"),
            "overall_score": result.get("overall_score", 0),
        })

    def verify_chain(self) -> dict[str, Any]:
        """Verify the audit log hash chain integrity."""
        log = self.db.get_audit_log(limit=10000)
        if not log:
            return {"valid": True, "entries": 0, "breaks": []}

        # Reverse to chronological order
        entries = list(reversed(log))
        breaks = []

        for i, entry in enumerate(entries):
            if i == 0:
                continue
            expected_prev = entries[i - 1].get("hash")
            actual_prev = entry.get("previous_hash")
            if actual_prev and actual_prev != expected_prev:
                breaks.append({
                    "index": i,
                    "expected": expected_prev,
                    "actual": actual_prev,
                    "event": entry.get("event_type"),
                })

        return {
            "valid": len(breaks) == 0,
            "entries": len(entries),
            "breaks": breaks,
        }

    def export_json(self, limit: int = 10000) -> str:
        """Export audit log as JSON."""
        log = self.db.get_audit_log(limit=limit)
        return json.dumps(list(reversed(log)), indent=2, default=str)

    def export_csv(self, limit: int = 10000) -> str:
        """Export audit log as CSV."""
        log = self.db.get_audit_log(limit=limit)
        lines = ["audit_id,event_type,timestamp,hash,previous_hash"]
        for entry in reversed(log):
            lines.append(
                f"{entry['audit_id']},{entry['event_type']},"
                f"{entry['timestamp']},{entry['hash']},{entry.get('previous_hash', '')}"
            )
        return "\n".join(lines)
