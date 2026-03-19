"""ORACLE binary file handler — extract strings, headers, magic bytes."""

from __future__ import annotations

import hashlib
import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("oracle.parsers.binary")

# Common file magic bytes
MAGIC_BYTES = {
    b"\x7fELF": "ELF executable",
    b"\x4d\x5a": "PE/DOS executable",
    b"\xfe\xed\xfa": "Mach-O binary",
    b"\xca\xfe\xba\xbe": "Java class / Mach-O fat",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"PK\x03\x04": "ZIP archive",
    b"\x1f\x8b": "GZIP compressed",
    b":10": "Intel HEX",
    b"S0": "Motorola S-record",
    b"\x00\x00\x01\x00": "ICO image",
    b"RIFF": "RIFF container (WAV/AVI)",
    b"\x42\x4d": "BMP image",
}


@dataclass
class BinaryResult:
    """Parsed binary file result."""
    filename: str
    size_bytes: int
    file_hash: str
    magic_type: str
    magic_bytes_hex: str
    strings: list[str] = field(default_factory=list)
    headers: dict[str, Any] = field(default_factory=dict)
    entropy: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class BinaryHandler:
    """Handle binary files — extract strings, headers, magic bytes."""

    def __init__(self, min_string_length: int = 6):
        self.min_string_length = min_string_length

    def parse(self, file_path: Path) -> BinaryResult:
        """Parse a binary file."""
        data = file_path.read_bytes()
        return self.parse_bytes(data, file_path.name)

    def parse_bytes(self, data: bytes, filename: str = "binary.bin") -> BinaryResult:
        """Parse binary data."""
        magic_type = self._identify_magic(data)
        magic_hex = data[:16].hex() if len(data) >= 16 else data.hex()

        result = BinaryResult(
            filename=filename,
            size_bytes=len(data),
            file_hash=hashlib.sha256(data).hexdigest(),
            magic_type=magic_type,
            magic_bytes_hex=magic_hex,
        )

        # Extract printable strings
        result.strings = self._extract_strings(data)

        # Extract headers based on type
        result.headers = self._extract_headers(data, magic_type)

        # Calculate entropy
        result.entropy = self._calculate_entropy(data)

        # Metadata summary
        result.metadata = {
            "string_count": len(result.strings),
            "entropy": round(result.entropy, 4),
            "magic_type": magic_type,
            "has_elf_header": magic_type == "ELF executable",
            "has_pe_header": magic_type == "PE/DOS executable",
        }

        logger.info(f"Parsed {filename}: {magic_type}, {len(data)} bytes, "
                     f"{len(result.strings)} strings, entropy={result.entropy:.2f}")
        return result

    def _identify_magic(self, data: bytes) -> str:
        """Identify file type from magic bytes."""
        for magic, file_type in MAGIC_BYTES.items():
            if data[:len(magic)] == magic:
                return file_type
        return "unknown"

    def _extract_strings(self, data: bytes) -> list[str]:
        """Extract printable ASCII strings from binary data."""
        # Match sequences of printable ASCII chars
        pattern = rb"[\x20-\x7e]{" + str(self.min_string_length).encode() + rb",}"
        matches = re.findall(pattern, data)

        strings = []
        seen = set()
        for match in matches:
            s = match.decode("ascii", errors="replace").strip()
            if s and s not in seen:
                seen.add(s)
                strings.append(s)

        return strings[:500]  # Cap at 500 strings

    def _extract_headers(self, data: bytes, magic_type: str) -> dict[str, Any]:
        """Extract file-type-specific header information."""
        headers: dict[str, Any] = {}

        if magic_type == "ELF executable" and len(data) >= 64:
            headers = self._parse_elf_header(data)
        elif magic_type == "PE/DOS executable" and len(data) >= 64:
            headers = self._parse_pe_header(data)
        elif magic_type == "Intel HEX":
            headers = {"format": "Intel HEX", "lines": data.count(b"\n")}

        return headers

    def _parse_elf_header(self, data: bytes) -> dict[str, Any]:
        """Parse basic ELF header fields."""
        try:
            ei_class = data[4]  # 1=32bit, 2=64bit
            ei_data = data[5]   # 1=LE, 2=BE
            ei_osabi = data[7]

            endian = "<" if ei_data == 1 else ">"
            bits = 32 if ei_class == 1 else 64

            e_type = struct.unpack(f"{endian}H", data[16:18])[0]
            e_machine = struct.unpack(f"{endian}H", data[18:20])[0]

            type_map = {0: "NONE", 1: "REL", 2: "EXEC", 3: "DYN", 4: "CORE"}
            machine_map = {
                3: "x86", 8: "MIPS", 20: "PowerPC", 40: "ARM",
                62: "x86_64", 183: "AArch64", 243: "RISC-V",
            }

            return {
                "format": "ELF",
                "bits": bits,
                "endian": "little" if ei_data == 1 else "big",
                "type": type_map.get(e_type, f"0x{e_type:x}"),
                "machine": machine_map.get(e_machine, f"0x{e_machine:x}"),
                "osabi": ei_osabi,
            }
        except Exception:
            return {"format": "ELF", "error": "parse_failed"}

    def _parse_pe_header(self, data: bytes) -> dict[str, Any]:
        """Parse basic PE header fields."""
        try:
            e_lfanew = struct.unpack("<I", data[60:64])[0]
            if e_lfanew + 6 > len(data):
                return {"format": "PE", "error": "truncated"}

            pe_sig = data[e_lfanew:e_lfanew + 4]
            if pe_sig != b"PE\x00\x00":
                return {"format": "PE/DOS", "pe_signature": False}

            machine = struct.unpack("<H", data[e_lfanew + 4:e_lfanew + 6])[0]
            machine_map = {
                0x14c: "x86", 0x8664: "x86_64", 0x1c0: "ARM",
                0xaa64: "AArch64",
            }

            return {
                "format": "PE",
                "pe_signature": True,
                "machine": machine_map.get(machine, f"0x{machine:x}"),
            }
        except Exception:
            return {"format": "PE", "error": "parse_failed"}

    def _calculate_entropy(self, data: bytes) -> float:
        """Calculate Shannon entropy of binary data."""
        import math
        if not data:
            return 0.0

        freq = [0] * 256
        for byte in data:
            freq[byte] += 1

        length = len(data)
        entropy = 0.0
        for count in freq:
            if count > 0:
                p = count / length
                entropy -= p * math.log2(p)

        return entropy
