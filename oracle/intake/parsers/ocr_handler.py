"""ORACLE OCR handler — Tesseract with image preprocessing for handwritten annotations."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger("oracle.parsers.ocr")

TESSERACT_AVAILABLE = False
try:
    import os
    import pytesseract
    # Ensure tessdata is findable
    user_tessdata = Path.home() / ".local" / "share" / "tessdata"
    if user_tessdata.exists() and "TESSDATA_PREFIX" not in os.environ:
        os.environ["TESSDATA_PREFIX"] = str(user_tessdata)
    TESSERACT_AVAILABLE = True
except ImportError:
    pass


@dataclass
class OCRResult:
    """OCR extraction result."""
    filename: str
    text: str
    confidence: float
    word_count: int
    preprocessing: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class OCRHandler:
    """Handle handwritten annotation OCR via Tesseract with preprocessing."""

    def __init__(self, language: str = "eng"):
        self.language = language
        if not TESSERACT_AVAILABLE:
            logger.warning("pytesseract not installed — OCR unavailable")

    def process(self, file_path: Path) -> OCRResult:
        """Process an image file through OCR."""
        img = Image.open(file_path)
        return self._run_ocr(img, file_path.name)

    def process_bytes(self, data: bytes, filename: str = "scan.png") -> OCRResult:
        """Process image bytes through OCR."""
        img = Image.open(io.BytesIO(data))
        return self._run_ocr(img, filename)

    def _run_ocr(self, img: Image.Image, filename: str) -> OCRResult:
        """Run OCR pipeline on an image."""
        if not TESSERACT_AVAILABLE:
            return OCRResult(
                filename=filename, text="", confidence=0.0,
                word_count=0, metadata={"error": "pytesseract not installed"},
            )

        # Preprocessing pipeline
        preprocessing_steps = []
        processed = self._preprocess(img, preprocessing_steps)

        # Run Tesseract with confidence data
        try:
            ocr_data = pytesseract.image_to_data(
                processed, lang=self.language, output_type=pytesseract.Output.DICT,
            )
            text = pytesseract.image_to_string(processed, lang=self.language).strip()

            # Calculate average confidence from word-level data
            confidences = [
                int(c) for c in ocr_data.get("conf", [])
                if str(c).lstrip("-").isdigit() and int(c) > 0
            ]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            word_count = len([w for w in ocr_data.get("text", []) if w.strip()])

        except Exception as e:
            logger.error(f"OCR failed for {filename}: {e}")
            return OCRResult(
                filename=filename, text="", confidence=0.0,
                word_count=0, metadata={"error": str(e)},
            )

        result = OCRResult(
            filename=filename,
            text=text,
            confidence=round(avg_confidence, 2),
            word_count=word_count,
            preprocessing=preprocessing_steps,
            metadata={
                "language": self.language,
                "original_size": f"{img.width}x{img.height}",
                "processed_size": f"{processed.width}x{processed.height}",
            },
        )

        logger.info(f"OCR {filename}: {word_count} words, confidence={avg_confidence:.1f}%")
        return result

    def _preprocess(self, img: Image.Image, steps: list[str]) -> Image.Image:
        """Preprocess image for better OCR — deskew, denoise, binarise."""
        processed = img.copy()

        # Convert to grayscale
        if processed.mode != "L":
            processed = processed.convert("L")
            steps.append("grayscale")

        # Resize if too small (< 300 DPI equivalent)
        if processed.width < 1000 or processed.height < 1000:
            scale = max(1000 / processed.width, 1000 / processed.height, 1)
            if scale > 1:
                new_size = (int(processed.width * scale), int(processed.height * scale))
                processed = processed.resize(new_size, Image.LANCZOS)
                steps.append(f"upscale_{scale:.1f}x")

        # Denoise with median filter
        processed = processed.filter(ImageFilter.MedianFilter(size=3))
        steps.append("denoise_median")

        # Increase contrast
        processed = ImageOps.autocontrast(processed, cutoff=2)
        steps.append("autocontrast")

        # Binarise (Otsu-style threshold)
        threshold = self._otsu_threshold(processed)
        processed = processed.point(lambda x: 255 if x > threshold else 0, mode="1")
        steps.append(f"binarise_t{threshold}")

        # Convert back to L for Tesseract
        processed = processed.convert("L")

        return processed

    def _otsu_threshold(self, img: Image.Image) -> int:
        """Calculate Otsu's threshold for binarisation."""
        histogram = img.histogram()
        total = sum(histogram)

        sum_total = sum(i * histogram[i] for i in range(256))
        sum_bg = 0
        weight_bg = 0
        max_variance = 0
        threshold = 0

        for i in range(256):
            weight_bg += histogram[i]
            if weight_bg == 0:
                continue
            weight_fg = total - weight_bg
            if weight_fg == 0:
                break

            sum_bg += i * histogram[i]
            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_total - sum_bg) / weight_fg

            variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
            if variance > max_variance:
                max_variance = variance
                threshold = i

        return threshold
