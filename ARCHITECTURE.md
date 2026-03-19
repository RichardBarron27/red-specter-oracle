# ORACLE Architecture

## System Overview

```
┌─────────────────────────────────────────────────────┐
│                   RESEARCHER                         │
│         (Browser: localhost:8200)                    │
└────────────┬────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────┐
│              FastAPI Backend (:8200)                 │
│  ┌──────────┬──────────┬──────────┬──────────┐      │
│  │ Intake   │ Query    │ Graph   │ Validation│      │
│  │ Engine   │ Engine   │ Engine  │ Framework │      │
│  └────┬─────┴────┬─────┴────┬────┴────┬──────┘      │
│       │          │          │         │              │
│  ┌────▼──┐  ┌───▼───┐ ┌───▼───┐ ┌───▼──────┐      │
│  │ChromaDB│  │Ollama │ │networkx│ │M40 (7    │      │
│  │Vector  │  │LLM    │ │Graph  │ │subsystems)│      │
│  │Store   │  │Server │ │Engine │ │          │      │
│  └────────┘  └───────┘ └───────┘ └──────────┘      │
│       │          │                                   │
│  ┌────▼──────────▼──────────────────────────┐       │
│  │         SQLite Database                   │       │
│  │  sessions | documents | queries           │       │
│  │  components | relationships | audit_log   │       │
│  │  graph_snapshots | researcher_profile     │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

## Data Flow

```
Document Upload → Intake Handler → Parser (PDF/Image/Code/Binary/OCR)
    → Chunking Engine (~512 tokens, 50 overlap)
    → Embedding Pipeline (nomic-embed-text via Ollama)
    → ChromaDB Vector Store

Query → Query Parser (DOCUMENT/COMPONENT/HYBRID)
    → Retriever (ChromaDB + networkx graph)
    → Synthesiser (Mistral 24B with structured prompt)
    → Citation Assembler (match claims to sources)
    → Wilson Confidence Scorer (accuracy/completeness/confidence)
    → Response Validator (7 M40 subsystems)
    → Audit Trail (Ed25519 signed, hash-chained)
    → Researcher Display
```

## API Reference

### Core

| Method | Path | Description |
|---|---|---|
| GET | /api/v1/health | System health check |
| GET | /api/v1/stats | System statistics |
| GET | /api/v1/ollama/status | LLM model status |

### Sessions

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/sessions | Create session |
| GET | /api/v1/sessions | List sessions |
| GET | /api/v1/sessions/{id} | Session detail |

### Documents

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/sessions/{id}/documents | Upload document |
| GET | /api/v1/sessions/{id}/documents | List documents |
| GET | /api/v1/documents/{id} | Document detail |
| POST | /api/v1/documents/{id}/ingest | Trigger ingestion |
| POST | /api/v1/sessions/{id}/ingest-all | Ingest all documents |

### Queries

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/sessions/{id}/ask | Submit NL query |
| GET | /api/v1/sessions/{id}/queries | List queries |
| POST | /api/v1/search | Raw similarity search |

### Graph

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/graph/sessions/{id}/extract | Extract components |
| POST | /api/v1/graph/sessions/{id}/map-relationships | Map relationships |
| POST | /api/v1/graph/sessions/{id}/build | Build graph |
| GET | /api/v1/graph/sessions/{id}/components | List components |
| GET | /api/v1/graph/sessions/{id}/relationships | List relationships |
| GET | /api/v1/graph/sessions/{id}/trust-chain | Trust chain view |
| GET | /api/v1/graph/sessions/{id}/critical-nodes | Critical components |
| GET | /api/v1/graph/sessions/{id}/data | Full graph data |
| GET | /api/v1/graph/components/{id} | Component detail |
| GET | /api/v1/graph/components/{id}/blast-radius | Blast radius |

### Validation

| Method | Path | Description |
|---|---|---|
| GET | /api/v1/validation/audit | Audit log |
| GET | /api/v1/validation/audit/verify | Verify hash chain |
| GET | /api/v1/validation/audit/export/json | Export JSON |
| GET | /api/v1/validation/audit/export/csv | Export CSV |
| GET | /api/v1/validation/profile/{session_id} | Researcher profile |

## Database Schema

8 tables, 13 indexes. See `oracle/db/database.py` for full schema.

## Security

- **Ed25519 signing** on all audit entries and validated responses
- **Hash-chained audit log** — tamper-evident, append-only
- **Air-gapped operation** — zero outbound network calls
- **No telemetry** — ChromaDB telemetry disabled
- **Local-only data** — all documents, embeddings, and models stored on-device
