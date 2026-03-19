# ORACLE Security

## Air-Gap Operation

ORACLE is designed to operate with zero network connectivity.

- All LLM inference runs locally via Ollama (no API calls to cloud providers)
- All embeddings generated locally (nomic-embed-text)
- ChromaDB runs fully offline with telemetry disabled
- Tesseract OCR runs locally (no cloud OCR services)
- No telemetry, analytics, or usage reporting at any layer
- SQLite database stored locally on the file system

## Ed25519 Signing

- Signing keys auto-generated on first run (stored at `~/.oracle/keys/oracle.key`)
- Private key permissions set to 0600 (owner read/write only)
- Public key exported alongside (`.pub` extension)
- All audit log entries are signed
- All validated responses include a signature hash
- Key rotation: delete the key file and restart — new keypair generated automatically

## Hash-Chained Audit Trail

- Every event (query, response, validation, action) is logged to the `audit_log` table
- Each entry contains a SHA-256 hash and a reference to the previous entry's hash
- Chain integrity verifiable via `/api/v1/validation/audit/verify`
- Append-only: no UPDATE or DELETE operations on the audit log table
- Exportable as JSON or CSV for external review

## Response Validation

Every LLM response passes through 7 validation subsystems before display:

1. **PatternMatcher** — detects fabricated citations, fake URLs, invented statistics
2. **ConsistencyChecker** — verifies response is grounded in source material (TF-IDF)
3. **ContradictionDetector** — flags internal contradictions and source conflicts
4. **ConfidenceAnalyser** — scores hedging vs overconfidence language
5. **FactChecker** — cross-checks claims against the registered fact corpus
6. **DriftMonitor** — detects quality degradation across a session
7. **AccuracyGrader** — assigns A-F grade based on composite score

Responses scoring below 0.7 are flagged AMBER (requires review).
Responses scoring below 0.4 are flagged RED (blocked).

## Data Handling

- Documents are stored in `~/.oracle/documents/` with SHA-256 hashed filenames
- No data ever leaves the local machine
- Session data persists in SQLite until the researcher explicitly deletes it
- Model weights are stored in the Ollama model directory (`~/.ollama/models/`)

## Model Provenance

| Model | Licence | Source |
|---|---|---|
| Mistral Small 24B | Apache 2.0 | mistral.ai |
| nomic-embed-text | Apache 2.0 | nomic.ai |
| MiniCPM-V 2.6 | Apache 2.0 | openbmb |
| Tesseract 5 | Apache 2.0 | github.com/tesseract-ocr |
| ChromaDB | Apache 2.0 | trychroma.com |
