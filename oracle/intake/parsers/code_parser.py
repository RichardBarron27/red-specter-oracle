"""ORACLE source code parser — extract functions, classes, imports, comments."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("oracle.parsers.code")

# Language detection by extension
LANGUAGE_MAP = {
    ".py": "python", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".java": "java", ".js": "javascript", ".ts": "typescript",
    ".rs": "rust", ".go": "go", ".asm": "assembly", ".s": "assembly",
    ".v": "verilog", ".vhd": "vhdl", ".sv": "systemverilog",
    ".rb": "ruby", ".php": "php", ".sh": "shell", ".bash": "shell",
}

# Regex patterns for function/class extraction by language
PATTERNS = {
    "python": {
        "function": re.compile(r"^([ \t]*)def\s+(\w+)\s*\(", re.MULTILINE),
        "class": re.compile(r"^class\s+(\w+)", re.MULTILINE),
        "import": re.compile(r"^(?:from\s+\S+\s+)?import\s+(.+)$", re.MULTILINE),
        "comment": re.compile(r"#\s*(.+)$", re.MULTILINE),
    },
    "c": {
        "function": re.compile(
            r"^[\w\s\*]+\s+(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE
        ),
        "include": re.compile(r'#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
        "comment": re.compile(r"//\s*(.+)$", re.MULTILINE),
        "define": re.compile(r"#define\s+(\w+)", re.MULTILINE),
        "struct": re.compile(r"(?:typedef\s+)?struct\s+(\w+)", re.MULTILINE),
    },
    "java": {
        "function": re.compile(
            r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{",
            re.MULTILINE,
        ),
        "class": re.compile(r"(?:public|private|abstract)\s+class\s+(\w+)", re.MULTILINE),
        "import": re.compile(r"^import\s+(.+);$", re.MULTILINE),
        "comment": re.compile(r"//\s*(.+)$", re.MULTILINE),
    },
    "rust": {
        "function": re.compile(r"(?:pub\s+)?fn\s+(\w+)", re.MULTILINE),
        "struct": re.compile(r"(?:pub\s+)?struct\s+(\w+)", re.MULTILINE),
        "import": re.compile(r"^use\s+(.+);$", re.MULTILINE),
        "comment": re.compile(r"//\s*(.+)$", re.MULTILINE),
    },
    "go": {
        "function": re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.MULTILINE),
        "struct": re.compile(r"^type\s+(\w+)\s+struct", re.MULTILINE),
        "import": re.compile(r'"([^"]+)"', re.MULTILINE),
        "comment": re.compile(r"//\s*(.+)$", re.MULTILINE),
    },
}

# Fallback patterns for languages without specific rules
GENERIC_PATTERNS = {
    "function": re.compile(r"(?:function|func|def|fn|sub|proc)\s+(\w+)", re.MULTILINE),
    "comment_line": re.compile(r"(?://|#|;)\s*(.+)$", re.MULTILINE),
}


@dataclass
class CodeUnit:
    """A logical unit of code (function, class, etc.)."""
    name: str
    unit_type: str  # function, class, struct, import, etc.
    start_line: int
    end_line: int
    content: str
    language: str


@dataclass
class CodeResult:
    """Parsed source code result."""
    filename: str
    language: str
    line_count: int
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    units: list[CodeUnit] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    structs: list[str] = field(default_factory=list)


class CodeParser:
    """Parse source code files — extract functions, classes, imports, comments."""

    def detect_language(self, filename: str) -> str:
        """Detect language from file extension."""
        ext = Path(filename).suffix.lower()
        return LANGUAGE_MAP.get(ext, "unknown")

    def parse(self, file_path: Path) -> CodeResult:
        """Parse a source code file."""
        content = file_path.read_text(errors="replace")
        return self.parse_text(content, file_path.name)

    def parse_text(self, content: str, filename: str) -> CodeResult:
        """Parse source code from text."""
        language = self.detect_language(filename)
        lines = content.split("\n")

        result = CodeResult(
            filename=filename,
            language=language,
            line_count=len(lines),
        )

        patterns = PATTERNS.get(language, PATTERNS.get("c", {}))

        # Extract named elements
        for key, pattern in patterns.items():
            matches = pattern.findall(content)
            if key == "function":
                # Handle Python where match includes indentation
                if language == "python":
                    result.functions = [m[1] if isinstance(m, tuple) else m for m in matches]
                else:
                    result.functions = list(matches)
            elif key == "class":
                result.classes = list(matches)
            elif key in ("import", "include"):
                result.imports = list(matches)
            elif key == "comment":
                result.comments = list(matches)[:20]  # Cap at 20
            elif key == "define":
                result.defines = list(matches)
            elif key == "struct":
                result.structs = list(matches)

        # If no language-specific patterns, use generic
        if language == "unknown" or not patterns:
            for match in GENERIC_PATTERNS["function"].finditer(content):
                result.functions.append(match.group(1))
            for match in GENERIC_PATTERNS["comment_line"].finditer(content):
                if len(result.comments) < 20:
                    result.comments.append(match.group(1))

        # Build logical units for chunking
        result.units = self._extract_units(content, filename, language)

        logger.info(f"Parsed {filename}: {language}, {len(lines)} lines, "
                     f"{len(result.functions)} functions, {len(result.classes)} classes")
        return result

    def _extract_units(self, content: str, filename: str, language: str) -> list[CodeUnit]:
        """Extract logical code units for chunking."""
        units = []
        lines = content.split("\n")

        if language == "python":
            units = self._extract_python_units(lines, language)
        elif language in ("c", "cpp"):
            units = self._extract_c_units(lines, language)
        else:
            # Fallback: treat entire file as one unit
            if content.strip():
                units.append(CodeUnit(
                    name=filename,
                    unit_type="file",
                    start_line=1,
                    end_line=len(lines),
                    content=content,
                    language=language,
                ))

        return units

    def _extract_python_units(self, lines: list[str], language: str) -> list[CodeUnit]:
        """Extract Python functions and classes as units."""
        units = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()

            if stripped.startswith("def ") or stripped.startswith("class "):
                unit_type = "function" if stripped.startswith("def ") else "class"
                match = re.match(r"(?:def|class)\s+(\w+)", stripped)
                name = match.group(1) if match else "unknown"
                indent = len(line) - len(stripped)
                start = i
                i += 1

                # Find end of block by indentation
                while i < len(lines):
                    if lines[i].strip() == "":
                        i += 1
                        continue
                    curr_indent = len(lines[i]) - len(lines[i].lstrip())
                    if curr_indent <= indent and lines[i].strip():
                        break
                    i += 1

                content = "\n".join(lines[start:i])
                units.append(CodeUnit(
                    name=name, unit_type=unit_type,
                    start_line=start + 1, end_line=i,
                    content=content, language=language,
                ))
            else:
                i += 1

        return units

    def _extract_c_units(self, lines: list[str], language: str) -> list[CodeUnit]:
        """Extract C/C++ functions as units using brace matching."""
        units = []
        content = "\n".join(lines)

        # Find function definitions
        func_pattern = re.compile(
            r"^([\w\s\*]+\s+(\w+)\s*\([^)]*\)\s*)\{",
            re.MULTILINE,
        )

        for match in func_pattern.finditer(content):
            name = match.group(2)
            start_pos = match.start()
            brace_pos = content.index("{", match.end() - 1)

            # Match braces
            depth = 1
            pos = brace_pos + 1
            while pos < len(content) and depth > 0:
                if content[pos] == "{":
                    depth += 1
                elif content[pos] == "}":
                    depth -= 1
                pos += 1

            func_content = content[start_pos:pos]
            start_line = content[:start_pos].count("\n") + 1
            end_line = content[:pos].count("\n") + 1

            units.append(CodeUnit(
                name=name, unit_type="function",
                start_line=start_line, end_line=end_line,
                content=func_content, language=language,
            ))

        return units
