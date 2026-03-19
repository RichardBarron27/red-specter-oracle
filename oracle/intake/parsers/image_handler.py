"""ORACLE image handler — metadata extraction and vision model characterisation."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from oracle.core.ollama_client import OllamaClient

logger = logging.getLogger("oracle.parsers.image")

SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}


@dataclass
class ImageResult:
    """Parsed image result."""
    filename: str
    width: int
    height: int
    format: str
    mode: str
    size_bytes: int
    file_hash: str
    description: str = ""
    labels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageHandler:
    """Handle image files — extract metadata and characterise via vision model."""

    def __init__(self, ollama: OllamaClient | None = None):
        self.ollama = ollama

    def extract_metadata(self, file_path: Path) -> ImageResult:
        """Extract image metadata without vision model."""
        data = file_path.read_bytes()
        img = Image.open(file_path)

        result = ImageResult(
            filename=file_path.name,
            width=img.width,
            height=img.height,
            format=img.format or file_path.suffix.lstrip(".").upper(),
            mode=img.mode,
            size_bytes=len(data),
            file_hash=hashlib.sha256(data).hexdigest(),
        )

        # Extract EXIF/metadata if available
        exif = {}
        try:
            info = img.info
            if info:
                for k, v in info.items():
                    if isinstance(v, (str, int, float)):
                        exif[str(k)] = v
        except Exception:
            pass
        result.metadata = exif

        img.close()
        return result

    def extract_metadata_bytes(self, data: bytes, filename: str = "image.png") -> ImageResult:
        """Extract metadata from image bytes."""
        import io
        img = Image.open(io.BytesIO(data))

        result = ImageResult(
            filename=filename,
            width=img.width,
            height=img.height,
            format=img.format or Path(filename).suffix.lstrip(".").upper(),
            mode=img.mode,
            size_bytes=len(data),
            file_hash=hashlib.sha256(data).hexdigest(),
        )
        img.close()
        return result

    def characterise(self, file_path: Path, prompt: str | None = None) -> ImageResult:
        """Extract metadata and characterise image using MiniCPM-V."""
        result = self.extract_metadata(file_path)

        if not self.ollama:
            logger.warning("No Ollama client — skipping vision characterisation")
            return result

        if not prompt:
            prompt = (
                "Describe this image in detail for a security researcher. "
                "If it is a schematic or circuit diagram, identify component labels, "
                "part numbers, IC names, interface types (SPI, I2C, UART, JTAG), "
                "and connections. If it is a photograph, describe what hardware "
                "or equipment is visible. Be specific and technical."
            )

        try:
            data = file_path.read_bytes()
            b64_data = base64.b64encode(data).decode()

            result_response = self.ollama.generate_with_image(
                prompt=prompt,
                image_b64=b64_data,
            )
            result.description = result_response.get("response", "")
            logger.info(f"Vision characterisation complete for {file_path.name}")
        except Exception as e:
            logger.warning(f"Vision characterisation failed for {file_path.name}: {e}")

        return result

    def characterise_bytes(self, data: bytes, filename: str = "image.png",
                           prompt: str | None = None) -> ImageResult:
        """Characterise image from bytes using vision model."""
        result = self.extract_metadata_bytes(data, filename)

        if not self.ollama:
            return result

        if not prompt:
            prompt = (
                "Describe this image in detail for a security researcher. "
                "Identify any component labels, part numbers, IC names, "
                "interface types, and connections visible."
            )

        try:
            b64_data = base64.b64encode(data).decode()
            result_response = self.ollama.generate_with_image(
                prompt=prompt,
                image_b64=b64_data,
            )
            result.description = result_response.get("response", "")
        except Exception as e:
            logger.warning(f"Vision characterisation failed for {filename}: {e}")

        return result
