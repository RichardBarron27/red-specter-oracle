#!/usr/bin/env bash
# ORACLE Setup Script — Offline Research Assistant for Component-Level Exploitation Analysis
# Red Specter Security Research
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           RED SPECTER ORACLE — Setup                        ║${NC}"
echo -e "${GREEN}║  Offline Research Assistant for Component-Level Analysis    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# --- System Requirements ---
echo -e "${YELLOW}[1/7] Checking system requirements...${NC}"

# RAM check
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
TOTAL_RAM_GB=$((TOTAL_RAM_KB / 1024 / 1024))
if [ "$TOTAL_RAM_GB" -lt 14 ]; then
    echo -e "${RED}WARNING: ${TOTAL_RAM_GB}GB RAM detected. 16GB minimum, 32GB recommended.${NC}"
    echo -e "${RED}Mistral Small 24B requires ~14GB RAM. Consider using a smaller model.${NC}"
else
    echo -e "${GREEN}  RAM: ${TOTAL_RAM_GB}GB — OK${NC}"
fi

# Disk check
DISK_FREE_GB=$(df -BG . | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$DISK_FREE_GB" -lt 20 ]; then
    echo -e "${RED}WARNING: ${DISK_FREE_GB}GB free disk. 20GB minimum (models + data).${NC}"
else
    echo -e "${GREEN}  Disk: ${DISK_FREE_GB}GB free — OK${NC}"
fi

# --- Docker ---
echo -e "${YELLOW}[2/7] Checking Docker...${NC}"
if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version | head -1)
    echo -e "${GREEN}  ${DOCKER_VERSION}${NC}"
else
    echo -e "${RED}Docker not found. Installing...${NC}"
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin
    elif command -v brew &>/dev/null; then
        brew install --cask docker
    else
        echo -e "${RED}Cannot install Docker automatically. Please install manually.${NC}"
        exit 1
    fi
fi

if command -v docker compose &>/dev/null; then
    echo -e "${GREEN}  Docker Compose available${NC}"
elif command -v docker-compose &>/dev/null; then
    echo -e "${GREEN}  docker-compose (legacy) available${NC}"
else
    echo -e "${RED}Docker Compose not found. Please install docker-compose-plugin.${NC}"
    exit 1
fi

# --- Build ORACLE ---
echo -e "${YELLOW}[3/7] Building ORACLE Docker image...${NC}"
docker compose build oracle

# --- Start Stack ---
echo -e "${YELLOW}[4/7] Starting ORACLE stack...${NC}"
docker compose up -d

echo -e "${YELLOW}[5/7] Waiting for services to start...${NC}"
sleep 10

# Check Ollama
for i in {1..30}; do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo -e "${GREEN}  Ollama: running${NC}"
        break
    fi
    sleep 2
done

# Check ORACLE API
for i in {1..15}; do
    if curl -sf http://localhost:8200/api/v1/health >/dev/null 2>&1; then
        echo -e "${GREEN}  ORACLE API: running${NC}"
        break
    fi
    sleep 2
done

# --- Pull Models ---
echo -e "${YELLOW}[6/7] Pulling LLM models (this may take 15-30 minutes on first run)...${NC}"

echo "  Pulling nomic-embed-text (embeddings)..."
docker exec oracle-ollama ollama pull nomic-embed-text 2>&1 | tail -1

echo "  Pulling mistral-small (reasoning)..."
docker exec oracle-ollama ollama pull mistral-small:24b-instruct-2501-q4_K_M 2>&1 | tail -1

echo "  Models downloaded."

# --- Self Test ---
echo -e "${YELLOW}[7/7] Running self-test...${NC}"

# Health check
HEALTH=$(curl -sf http://localhost:8200/api/v1/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q "operational"; then
    echo -e "${GREEN}  Health check: PASSED${NC}"
else
    echo -e "${RED}  Health check: FAILED${NC}"
    echo "$HEALTH"
    exit 1
fi

# Create test session
SESSION=$(curl -sf -X POST http://localhost:8200/api/v1/sessions \
    -H "Content-Type: application/json" \
    -d '{"name":"_setup_test"}' 2>/dev/null || echo "FAILED")
if echo "$SESSION" | grep -q "session_id"; then
    echo -e "${GREEN}  Session creation: PASSED${NC}"
else
    echo -e "${RED}  Session creation: FAILED${NC}"
fi

# Ollama models
MODELS=$(curl -sf http://localhost:8200/api/v1/ollama/status 2>/dev/null || echo "{}")
if echo "$MODELS" | grep -q "loaded"; then
    echo -e "${GREEN}  LLM models: LOADED${NC}"
else
    echo -e "${YELLOW}  LLM models: check ollama status${NC}"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    ORACLE is ready.                         ║${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}║  Document Intake:  http://localhost:8200/                   ║${NC}"
echo -e "${GREEN}║  Chat Interface:   http://localhost:8200/chat               ║${NC}"
echo -e "${GREEN}║  Component Graph:  http://localhost:8200/graph              ║${NC}"
echo -e "${GREEN}║  API Docs:         http://localhost:8200/docs               ║${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}║  \"ORACLE sees what others miss.\"                            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
