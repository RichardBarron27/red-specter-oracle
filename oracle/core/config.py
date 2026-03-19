"""ORACLE configuration management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_DIR = Path.home() / ".oracle"
DEFAULT_DB_PATH = DEFAULT_CONFIG_DIR / "oracle.db"
DEFAULT_SESSIONS_DIR = DEFAULT_CONFIG_DIR / "sessions"
DEFAULT_DOCUMENTS_DIR = DEFAULT_CONFIG_DIR / "documents"
DEFAULT_CHROMA_DIR = DEFAULT_CONFIG_DIR / "chroma"
DEFAULT_KEY_PATH = DEFAULT_CONFIG_DIR / "keys" / "oracle.key"


@dataclass
class OllamaConfig:
    """Ollama LLM configuration."""
    base_url: str = "http://localhost:11434"
    reasoning_model: str = "mistral-small:24b-instruct-2501-q4_K_M"
    vision_model: str = "minicpm-v:8b-2.6-q4_K_M"
    embedding_model: str = "nomic-embed-text"
    timeout: float = 300.0


@dataclass
class IngestionConfig:
    """Document ingestion settings."""
    max_file_size_mb: int = 500
    supported_extensions: list[str] = field(default_factory=lambda: [
        ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
        ".py", ".c", ".h", ".cpp", ".rs", ".go", ".java", ".js", ".ts",
        ".asm", ".s", ".v", ".vhd", ".sv",
        ".json", ".yaml", ".yml", ".xml", ".csv", ".txt", ".md",
        ".bin", ".hex", ".elf", ".fw",
    ])
    ocr_languages: str = "eng"


@dataclass
class OracleConfig:
    """Main ORACLE configuration."""
    config_dir: Path = DEFAULT_CONFIG_DIR
    db_path: Path = DEFAULT_DB_PATH
    sessions_dir: Path = DEFAULT_SESSIONS_DIR
    documents_dir: Path = DEFAULT_DOCUMENTS_DIR
    chroma_dir: Path = DEFAULT_CHROMA_DIR
    key_path: Path = DEFAULT_KEY_PATH
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    api_host: str = "127.0.0.1"
    api_port: int = 8200
    output_format: str = "json"

    def save(self, path: Path | None = None) -> Path:
        """Save configuration to file."""
        target = path or (self.config_dir / "config.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        for key in ("config_dir", "db_path", "sessions_dir", "documents_dir", "chroma_dir", "key_path"):
            data[key] = str(data[key])
        target.write_text(json.dumps(data, indent=2))
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> OracleConfig:
        """Load configuration from file."""
        target = path or (DEFAULT_CONFIG_DIR / "config.json")
        if not target.exists():
            return cls()
        data = json.loads(target.read_text())
        for key in ("config_dir", "db_path", "sessions_dir", "documents_dir", "chroma_dir", "key_path"):
            if key in data:
                data[key] = Path(data[key])
        if "ollama" in data:
            data["ollama"] = OllamaConfig(**data["ollama"])
        if "ingestion" in data:
            data["ingestion"] = IngestionConfig(**data["ingestion"])
        return cls(**data)

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        for d in (self.config_dir, self.sessions_dir, self.documents_dir, self.chroma_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        for key in ("config_dir", "db_path", "sessions_dir", "documents_dir", "chroma_dir", "key_path"):
            data[key] = str(data[key])
        return data
