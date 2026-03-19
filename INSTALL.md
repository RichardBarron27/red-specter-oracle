# ORACLE Installation Guide

## Prerequisites

- Docker 24.0+ with Docker Compose
- 16 GB RAM minimum (32 GB recommended)
- 20 GB free disk space

## Automated Installation

```bash
./setup.sh
```

The setup script will:
1. Check system requirements (RAM, disk)
2. Verify Docker installation
3. Build the ORACLE Docker image
4. Start the ORACLE stack (API + Ollama)
5. Pull required LLM models (~15 GB total)
6. Run a self-test to confirm everything is working

## Manual Installation

### 1. Start the stack

```bash
docker compose up -d
```

### 2. Pull models

```bash
docker exec oracle-ollama ollama pull nomic-embed-text
docker exec oracle-ollama ollama pull mistral-small:24b-instruct-2501-q4_K_M
```

### 3. Verify

```bash
curl http://localhost:8200/api/v1/health
```

## Development Installation (without Docker)

```bash
pip install -e ".[dev]"
ollama serve &
ollama pull nomic-embed-text
ollama pull mistral-small:24b-instruct-2501-q4_K_M
oracle init
oracle serve
```

## Stopping ORACLE

```bash
docker compose down
```

## Uninstalling

```bash
docker compose down -v  # removes data volumes
docker rmi oracle-api
```

## Offline / Air-Gapped Deployment

1. On a machine with internet access, run `setup.sh` to download all models
2. Export the Docker images:
   ```bash
   docker save oracle-api ollama/ollama > oracle-bundle.tar
   docker run --rm -v ollama-models:/data -v $(pwd):/backup busybox tar czf /backup/ollama-models.tar.gz /data
   ```
3. Transfer `oracle-bundle.tar` and `ollama-models.tar.gz` to the air-gapped machine
4. On the air-gapped machine:
   ```bash
   docker load < oracle-bundle.tar
   docker volume create ollama-models
   docker run --rm -v ollama-models:/data -v $(pwd):/backup busybox tar xzf /backup/ollama-models.tar.gz -C /
   docker compose up -d
   ```
