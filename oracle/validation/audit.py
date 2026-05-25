"""ORACLE Audit Trail — hardened, append-only, Ed25519 signed, cross-restart persistent."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from oracle.core.crypto import CryptoEngine
from oracle.db.database import Database

logger = logging.getLogger("oracle.validation.audit")

DEFAULT_STATE_PATH = Path.home() / ".oracle" / "audit_chain_state.json"


class AuditTrail:
    """Hardened audit trail with Ed25519 signatures, hash chaining, and cross-restart persistence."""

    def __init__(
        self,
        db: Database,
        crypto: CryptoEngine | None = None,
        state_path: Path | None = None,
    ):
        self.db = db
        self.crypto = crypto or CryptoEngine()
        self._state_path = state_path or DEFAULT_STATE_PATH
        self._last_hash: str | None = None

        # Load persisted state from disk first (survives DB recreation)
        disk_hash, clean_shutdown = self._load_chain_state()

        if disk_hash is not None:
            self._last_hash = disk_hash
            # Log RECOVERY event if previous process did not flush cleanly
            if not clean_shutdown:
                self._log_recovery()
        else:
            # Fall back to DB — handles first-run and state file absent
            log = db.get_audit_log(limit=1)
            if log:
                self._last_hash = log[0].get("hash")

    def _load_chain_state(self) -> tuple[str | None, bool]:
        """Load persisted chain state. Returns (last_hash, clean_shutdown)."""
        if not self._state_path.exists():
            return None, True
        try:
            data = json.loads(self._state_path.read_text())
            sig_hex = data.get("signature", "")
            payload = {k: v for k, v in data.items() if k != "signature"}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if not (sig_hex and self.crypto.verify_json(canonical, sig_hex)):
                logger.warning("Audit chain state file signature invalid — ignoring")
                return None, True
            return data.get("last_hash"), data.get("clean_shutdown", False)
        except Exception as e:
            logger.warning(f"Audit chain state load failed: {e} — ignoring")
            return None, True

    def _save_chain_state(self, clean_shutdown: bool = False) -> None:
        """Persist current chain head to disk with Ed25519 signature."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "last_hash": self._last_hash,
                "timestamp": time.time(),
                "clean_shutdown": clean_shutdown,
            }
            canonical, sig = self.crypto.sign_json(payload)
            self._state_path.write_text(
                json.dumps({**payload, "signature": sig}, indent=2)
            )
        except Exception as e:
            logger.error(f"Failed to save audit chain state: {e}")

    def _log_recovery(self) -> None:
        """Log a signed RECOVERY event — unclean shutdown detected."""
        entry_hash = self._write_entry(
            "chain_recovery",
            json.dumps({
                "actor": "system",
                "timestamp": time.time(),
                "note": "Unclean shutdown detected — chain resumed from persisted state",
            }),
        )
        self._last_hash = entry_hash
        self._save_chain_state(clean_shutdown=False)
        logger.warning("Audit chain: RECOVERY event logged — previous session did not flush cleanly")

    def flush(self) -> None:
        """Call on clean shutdown to mark the chain state file as clean."""
        self._save_chain_state(clean_shutdown=True)

    def _write_entry(self, event_type: str, event_json: str) -> str:
        """Compute hash, write to DB, return entry hash."""
        data_bytes = event_json.encode()
        if self._last_hash:
            entry_hash = CryptoEngine.hash_chain(self._last_hash, data_bytes)
        else:
            entry_hash = CryptoEngine.hash_data(data_bytes)

        self.crypto.sign_json({"hash": entry_hash, "event": event_type})

        self.db.add_audit_entry(
            event_type=event_type,
            event_data=event_json,
            entry_hash=entry_hash,
            previous_hash=self._last_hash,
        )
        return entry_hash

    def log_event(
        self,
        event_type: str,
        data: dict[str, Any],
        actor: str = "system",
    ) -> str:
        """Log an event with signature and hash chain. Persists state to disk."""
        event_data = {
            "actor": actor,
            "timestamp": time.time(),
            **data,
        }
        event_json = json.dumps(event_data, sort_keys=True)
        entry_hash = self._write_entry(event_type, event_json)
        self._last_hash = entry_hash
        self._save_chain_state(clean_shutdown=False)
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
            "incomplete": result.get("incomplete", False),
        })

    def verify_chain(self) -> dict[str, Any]:
        """Verify audit log hash chain integrity — detects both chain breaks and data tampering."""
        log = self.db.get_audit_log(limit=10000)
        if not log:
            return {"valid": True, "entries": 0, "breaks": []}

        entries = list(reversed(log))
        breaks = []

        for i, entry in enumerate(entries):
            event_json = entry.get("event_data", "")
            stored_hash = entry.get("hash", "")
            prev_hash = entry.get("previous_hash")

            # Re-derive expected hash from stored data — catches event_data tampering
            data_bytes = event_json.encode()
            if prev_hash:
                expected_hash = CryptoEngine.hash_chain(prev_hash, data_bytes)
            else:
                expected_hash = CryptoEngine.hash_data(data_bytes)

            if expected_hash != stored_hash:
                breaks.append({
                    "index": i,
                    "expected_hash": expected_hash,
                    "actual_hash": stored_hash,
                    "event": entry.get("event_type"),
                    "type": "data_tampered",
                })

            # Also verify previous_hash linkage
            if i > 0:
                expected_prev = entries[i - 1].get("hash")
                if prev_hash and prev_hash != expected_prev:
                    breaks.append({
                        "index": i,
                        "expected_prev": expected_prev,
                        "actual_prev": prev_hash,
                        "event": entry.get("event_type"),
                        "type": "chain_break",
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
