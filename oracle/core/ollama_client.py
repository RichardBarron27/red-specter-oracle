"""ORACLE Ollama client — local LLM interface."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from oracle.core.config import OllamaConfig

logger = logging.getLogger("oracle.ollama")


class OllamaClient:
    """Client for the local Ollama LLM server."""

    def __init__(self, config: OllamaConfig | None = None):
        self.config = config or OllamaConfig()
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            resp = self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """List all downloaded models."""
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def has_model(self, model_name: str) -> bool:
        """Check if a specific model is downloaded."""
        models = self.list_models()
        return any(m.get("name", "").startswith(model_name.split(":")[0]) for m in models)

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Generate a response from the reasoning model."""
        model = model or self.config.reasoning_model
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        try:
            resp = self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return {"error": str(e), "response": ""}

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate embeddings for text."""
        model = model or self.config.embedding_model
        try:
            resp = self._client.post(
                "/api/embed",
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [[]])
            return embeddings[0] if embeddings else []
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []

    def generate_with_image(
        self,
        prompt: str,
        image_b64: str,
        model: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Generate a response from the vision model with an image."""
        model = model or self.config.vision_model
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": stream,
        }

        try:
            resp = self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Vision generation failed: {e}")
            return {"error": str(e), "response": ""}

    def model_status(self) -> dict[str, Any]:
        """Get status of required models."""
        models = self.list_models()
        model_names = [m.get("name", "") for m in models]

        def check(target: str) -> str:
            return "loaded" if any(n.startswith(target.split(":")[0]) for n in model_names) else "missing"

        return {
            "ollama_available": self.is_available(),
            "reasoning_model": {
                "name": self.config.reasoning_model,
                "status": check(self.config.reasoning_model),
            },
            "vision_model": {
                "name": self.config.vision_model,
                "status": check(self.config.vision_model),
            },
            "embedding_model": {
                "name": self.config.embedding_model,
                "status": check(self.config.embedding_model),
            },
        }

    def close(self) -> None:
        self._client.close()
