# ORACLE

**Offline Research Assistant for Component-Level Exploitation Analysis**

Red Specter Security Research | v1.0.0-trl6

> *"ORACLE sees what others miss."*

ORACLE is a standalone, air-gapped intelligent research assistant purpose-built for security researchers conducting hardware and software tear-downs of complex industrial machinery.

## What It Does

- **Ingest** PDFs, schematics, datasheets, images, source code, binary files, handwritten annotations
- **Build** a component-level knowledge graph — hardware architecture, interfaces, protocols, trust chains
- **Query** in natural language with source citation, confidence scoring, and persistent session memory
- **Validate** every response through a 7-subsystem hallucination detection framework before display
- **Operate** fully offline — no internet connection required at any layer

## Quick Start

```bash
git clone https://github.com/RichardBarron27/red-specter-oracle.git
cd red-specter-oracle
./setup.sh
```



## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 32 GB |
| Disk | 20 GB free | 50 GB free |
| CPU | 4 cores | 8+ cores |
| GPU | Not required | RTX 3060+ (5x faster inference) |
| OS | Ubuntu 22.04+, Debian 12+, macOS 14+ | Any Linux with Docker |
| Docker | 24.0+ | Latest |

## Architecture

```
Researcher → Chat UI → FastAPI → Query Engine
                                    ├── Query Parser (classify intent)
                                    ├── Retriever (ChromaDB + Graph)
                                    ├── Synthesiser (Mistral 24B)
                                    ├── Citation Assembler
                                    ├── Wilson Confidence Scorer
                                    └── Response Validator (7 subsystems)
                                         ├── PatternMatcher
                                         ├── ConsistencyChecker
                                         ├── ContradictionDetector
                                         ├── ConfidenceAnalyser
                                         ├── FactChecker
                                         ├── DriftMonitor
                                         └── AccuracyGrader
```

## Performance

| Setup | Inference speed | First-run download |
|---|---|---|
| CPU only (default) | ~3–8 tokens/sec | ~4 GB |
| GPU (RTX 3060+) | ~40–80 tokens/sec | ~4 GB |
| CPU + Mistral 24B (optional) | ~1–3 tokens/sec | ~16 GB |

**CPU is fully supported.** Expect 15–40 seconds per response on CPU-only hardware with the default 7B model. A GPU accelerates this to near-instant. To upgrade to Mistral 24B for deeper analysis, set `ORACLE_REASONING_MODEL=mistral-small:24b-instruct-2501-q4_K_M` in your environment.

## Model Stack

| Role | Model | RAM |
|---|---|---|
| Reasoning (default) | Mistral 7B Instruct v0.3 Q4_K_M | ~4 GB |
| Reasoning (optional) | Mistral Small 24B Q4_K_M | ~14 GB |
| Vision | MiniCPM-V 2.6 8B Q4 (on-demand) | ~5 GB |
| Embeddings | nomic-embed-text | ~274 MB |
| OCR | Tesseract 5 | Minimal |
| Vector Store | ChromaDB (SQLite-backed) | ~1 GB |

## API Reference

See `ARCHITECTURE.md` for full API documentation.

## Licence

Apache 2.0

## Contact

Red Specter Security Research
richard@red-specter.co.uk
red-specter.co.uk
