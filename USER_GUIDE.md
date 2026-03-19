# ORACLE User Guide

## Getting Started

Open your browser to http://localhost:8200/

## 1. Creating a Research Session

Every investigation starts with a session. A session holds your documents, component graph, queries, and conversation history.

1. Go to the **Document Intake** page (http://localhost:8200/)
2. Enter a session name (e.g. "PLC Teardown - March 2026")
3. Click **NEW SESSION**

## 2. Ingesting Documents

Drag and drop files onto the intake area, or click to browse. Supported formats:

| Format | Types |
|---|---|
| Documents | PDF |
| Images | PNG, JPG, JPEG, TIFF, BMP |
| Code | .py, .c, .h, .cpp, .rs, .go, .java, .js, .ts, .asm, .v, .vhd |
| Structured | JSON, YAML, XML, CSV, TXT, Markdown |
| Binary | .bin, .hex, .elf, .fw |

ORACLE will:
- Parse text, tables, and metadata from PDFs
- OCR handwritten annotations from images
- Extract functions, classes, and imports from source code
- Extract strings and headers from binary files
- Chunk everything and embed it in the vector store

## 3. Querying

Go to the **Chat Interface** (http://localhost:8200/chat).

Ask questions in natural language:
- "What interfaces does this device expose?"
- "Show me the pin configuration for UART"
- "What is the blast radius if the main MCU is compromised?"
- "Which components communicate via SPI?"

### Query Types

ORACLE automatically classifies your query:
- **DOCUMENT** — searches indexed text content
- **COMPONENT** — queries the component graph
- **HYBRID** — combines both

### Follow-up Questions

ORACLE maintains context across your conversation. You can ask:
1. "What interfaces does the MCU support?"
2. "Which of those are wireless?"
3. "Show me the pin assignments for the wired ones"

Each follow-up uses the previous exchanges for context.

## 4. Understanding Confidence Scores

Every response displays three scores:

| Score | Meaning |
|---|---|
| **Accuracy** | How well claims match source material |
| **Completeness** | How much relevant source material was used |
| **Confidence** | Statistical certainty (Wilson lower bound) |

### Validation Status

- **GREEN** — Passed all 7 validation subsystems. Reliable.
- **AMBER** — Below accuracy threshold. Review the cited sources.
- **RED** — Blocked. Raw sources displayed instead. Do not trust the generated response.

### Unverified Claims

Claims that cannot be matched to any indexed source are flagged inline. These may be:
- Model hallucinations (fabricated part numbers, standards, or specifications)
- Correct information not yet in your document library
- Ambiguous phrasing that the citation matcher couldn't resolve

## 5. Component Graph

Go to http://localhost:8200/graph

After ingesting documents, click **EXTRACT COMPONENTS** then **MAP RELATIONSHIPS** then **BUILD GRAPH**.

The graph shows:
- **Nodes** — components colour-coded by type (MCU, memory, protocol, etc.)
- **Edges** — relationships (CONNECTS_TO, DEPENDS_ON, CONTROLS, etc.)
- **Click any node** to see full details including source document and page

### Graph Queries via API

- **Blast radius:** What is affected if component X is compromised?
- **Critical nodes:** Which components have the most connections?
- **Trust chain:** Hardware → firmware → OS → application layer view
- **Version conflicts:** Where do datasheets disagree?

## 6. Exporting the Audit Log

Every query, response, validation score, and action is logged with Ed25519 signatures.

- **View:** GET /api/v1/validation/audit
- **Verify chain:** GET /api/v1/validation/audit/verify
- **Export JSON:** GET /api/v1/validation/audit/export/json
- **Export CSV:** GET /api/v1/validation/audit/export/csv

## 7. Session Persistence

Sessions persist across browser restarts, system reboots, and days/weeks of inactivity. Your conversation history, documents, and component graph are all retained in the SQLite database.

To resume: open the Chat Interface, select your session from the sidebar.
