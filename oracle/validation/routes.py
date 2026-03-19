"""ORACLE Validation API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from oracle.db.database import Database
from oracle.validation.audit import AuditTrail
from oracle.validation.profiler import ResearcherProfiler

validation_router = APIRouter(prefix="/api/v1/validation")

_db: Database | None = None
_audit: AuditTrail | None = None
_profiler: ResearcherProfiler | None = None


def init_validation_routes(
    db: Database,
    audit: AuditTrail,
    profiler: ResearcherProfiler,
) -> None:
    global _db, _audit, _profiler
    _db = db
    _audit = audit
    _profiler = profiler


@validation_router.get("/audit")
def get_audit_log(limit: int = 100) -> list[dict[str, Any]]:
    if not _db:
        raise HTTPException(status_code=503)
    return _db.get_audit_log(limit=limit)


@validation_router.get("/audit/verify")
def verify_audit_chain() -> dict[str, Any]:
    if not _audit:
        raise HTTPException(status_code=503)
    return _audit.verify_chain()


@validation_router.get("/audit/export/json")
def export_audit_json(limit: int = 10000) -> dict[str, Any]:
    if not _audit:
        raise HTTPException(status_code=503)
    return {"format": "json", "data": _audit.export_json(limit)}


@validation_router.get("/audit/export/csv")
def export_audit_csv(limit: int = 10000) -> dict[str, Any]:
    if not _audit:
        raise HTTPException(status_code=503)
    return {"format": "csv", "data": _audit.export_csv(limit)}


@validation_router.get("/profile/{session_id}")
def get_researcher_profile(session_id: str) -> dict[str, Any]:
    if not _profiler:
        raise HTTPException(status_code=503)
    profile = _profiler.get_profile(session_id)
    if not profile:
        return {"session_id": session_id, "profile": None}
    return profile
