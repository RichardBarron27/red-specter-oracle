"""ORACLE document intake handler — receives and stores files."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

from oracle.core.config import OracleConfig
from oracle.db.database import Database

logger = logging.getLogger("oracle.intake")

# File type classification
FILE_TYPES = {
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".tiff": "image", ".tif": "image", ".bmp": "image",
    ".py": "code", ".c": "code", ".h": "code", ".cpp": "code",
    ".rs": "code", ".go": "code", ".java": "code", ".js": "code",
    ".ts": "code", ".asm": "code", ".s": "code",
    ".v": "code", ".vhd": "code", ".sv": "code",
    ".json": "structured", ".yaml": "structured", ".yml": "structured",
    ".xml": "structured", ".csv": "structured",
    ".txt": "text", ".md": "text",
    ".bin": "binary", ".hex": "binary", ".elf": "binary", ".fw": "binary",
}


class IntakeHandler:
    """Handles document intake — file reception and storage."""

    def __init__(self, config: OracleConfig, db: Database):
        self.config = config
        self.db = db
        self.documents_dir = config.documents_dir
        self.documents_dir.mkdir(parents=True, exist_ok=True)

    def receive_file(
        self,
        session_id: str,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        """Receive a file, store it, and register in the database."""
        # Validate session exists
        session = self.db.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        # Validate file extension
        ext = Path(filename).suffix.lower()
        if ext not in self.config.ingestion.supported_extensions:
            raise ValueError(f"Unsupported file type: {ext}")

        # Check file size
        size_mb = len(content) / (1024 * 1024)
        if size_mb > self.config.ingestion.max_file_size_mb:
            raise ValueError(
                f"File too large: {size_mb:.1f}MB (max {self.config.ingestion.max_file_size_mb}MB)"
            )

        # Compute hash
        file_hash = hashlib.sha256(content).hexdigest()

        # Store file
        session_dir = self.documents_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / f"{file_hash[:12]}_{filename}"
        file_path.write_bytes(content)

        # Classify file type
        file_type = FILE_TYPES.get(ext, "unknown")

        # Register in database
        doc = self.db.add_document(
            session_id=session_id,
            filename=filename,
            file_path=str(file_path),
            file_type=file_type,
            file_size=len(content),
            file_hash=file_hash,
        )

        logger.info(
            f"Received {filename} ({file_type}, {len(content)} bytes) "
            f"into session {session_id[:8]}..."
        )

        return doc

    def get_supported_types(self) -> list[str]:
        """Return list of supported file extensions."""
        return sorted(self.config.ingestion.supported_extensions)
