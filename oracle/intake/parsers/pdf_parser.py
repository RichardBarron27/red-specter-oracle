"""ORACLE PDF parser — text, tables, metadata, embedded images."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger("oracle.parsers.pdf")


@dataclass
class PDFPage:
    """Parsed content from a single PDF page."""
    page_number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass
class PDFResult:
    """Complete parsed PDF result."""
    filename: str
    title: str
    author: str
    page_count: int
    pages: list[PDFPage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    def all_images(self) -> list[dict[str, Any]]:
        images = []
        for p in self.pages:
            for img in p.images:
                img["page"] = p.page_number
                images.append(img)
        return images


class PDFParser:
    """Extract text, tables, metadata, and images from PDFs using PyMuPDF."""

    def __init__(self, image_output_dir: Path | None = None):
        self.image_output_dir = image_output_dir

    def parse(self, file_path: Path) -> PDFResult:
        """Parse a PDF file and extract all content."""
        doc = fitz.open(str(file_path))
        metadata = doc.metadata or {}

        result = PDFResult(
            filename=file_path.name,
            title=metadata.get("title", ""),
            author=metadata.get("author", ""),
            page_count=len(doc),
            metadata={k: v for k, v in metadata.items() if v},
        )

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_data = self._extract_page(page, page_num + 1, file_path)
            result.pages.append(page_data)

        doc.close()
        logger.info(f"Parsed {file_path.name}: {result.page_count} pages, "
                     f"{sum(len(p.images) for p in result.pages)} images")
        return result

    def parse_bytes(self, data: bytes, filename: str = "document.pdf") -> PDFResult:
        """Parse PDF from bytes."""
        doc = fitz.open(stream=data, filetype="pdf")
        metadata = doc.metadata or {}

        result = PDFResult(
            filename=filename,
            title=metadata.get("title", ""),
            author=metadata.get("author", ""),
            page_count=len(doc),
            metadata={k: v for k, v in metadata.items() if v},
        )

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_data = self._extract_page(page, page_num + 1)
            result.pages.append(page_data)

        doc.close()
        return result

    def _extract_page(self, page: fitz.Page, page_number: int,
                      source_path: Path | None = None) -> PDFPage:
        """Extract all content from a single page."""
        # Text extraction with layout preservation
        text = page.get_text("text")

        # Extract links
        links = []
        for link in page.get_links():
            if "uri" in link:
                links.append(link["uri"])

        # Extract images
        images = self._extract_images(page, page_number, source_path)

        # Table detection via text blocks
        tables = self._detect_tables(page)

        return PDFPage(
            page_number=page_number,
            text=text.strip(),
            tables=tables,
            images=images,
            links=links,
        )

    def _extract_images(self, page: fitz.Page, page_number: int,
                        source_path: Path | None = None) -> list[dict[str, Any]]:
        """Extract embedded images from a page."""
        images = []
        image_list = page.get_images(full=True)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = page.parent.extract_image(xref)
                if not base_image:
                    continue

                img_data = base_image["image"]
                img_ext = base_image.get("ext", "png")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                image_record: dict[str, Any] = {
                    "index": img_idx,
                    "page": page_number,
                    "width": width,
                    "height": height,
                    "format": img_ext,
                    "size_bytes": len(img_data),
                    "xref": xref,
                }

                # Save image to disk if output dir set
                if self.image_output_dir:
                    self.image_output_dir.mkdir(parents=True, exist_ok=True)
                    stem = source_path.stem if source_path else "doc"
                    img_filename = f"{stem}_p{page_number}_img{img_idx}.{img_ext}"
                    img_path = self.image_output_dir / img_filename
                    img_path.write_bytes(img_data)
                    image_record["saved_path"] = str(img_path)

                image_record["data"] = img_data
                images.append(image_record)

            except Exception as e:
                logger.warning(f"Failed to extract image {img_idx} from page {page_number}: {e}")

        return images

    def _detect_tables(self, page: fitz.Page) -> list[list[list[str]]]:
        """Simple table detection using text block positions."""
        tables = []
        try:
            # Use PyMuPDF's find_tables if available (v1.23+)
            tab_finder = page.find_tables()
            if tab_finder and tab_finder.tables:
                for table in tab_finder.tables:
                    rows = []
                    for row in table.extract():
                        rows.append([cell if cell else "" for cell in row])
                    if rows:
                        tables.append(rows)
        except Exception:
            pass
        return tables
