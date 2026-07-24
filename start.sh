#!/bin/bash
# TranslateGemma Docker Startup Script
# Automatically selects the GPU with most free memory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     TranslateGemma Docker Launcher         ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════╝${NC}"
echo

# Check nvidia-docker
check_nvidia_docker() {
    if ! command -v nvidia-smi &> /dev/null; then
        echo -e "${RED}Error: nvidia-smi not found. NVIDIA drivers required.${NC}"
        exit 1
    fi
    
    if ! docker info 2>/dev/null | grep -q "Runtimes.*nvidia"; then
        echo -e "${YELLOW}Warning: nvidia-docker runtime not detected.${NC}"
        echo -e "${YELLOW}Install with: sudo apt install nvidia-container-toolkit${NC}"
    fi
    
    echo -e "${GREEN}✓ NVIDIA Docker environment OK${NC}"
}

# Select GPU with most free memory
select_gpu() {
    echo -e "\n${CYAN}Checking GPU status...${NC}"
    nvidia-smi --query-gpu=index,name,memory.used,memory.free,memory.total --format=csv,noheader
    echo
    
    # Get GPU with most free memory
    GPU_ID=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | \
             sort -t',' -k2 -rn | head -1 | cut -d',' -f1 | tr -d ' ')
    
    if [ -z "$GPU_ID" ]; then
        echo -e "${RED}Error: No GPU found${NC}"
        exit 1
    fi
    
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i "$GPU_ID")
    GPU_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader -i "$GPU_ID")
    
    echo -e "${GREEN}✓ Selected GPU $GPU_ID: $GPU_NAME (Free: $GPU_FREE)${NC}"
    export NVIDIA_VISIBLE_DEVICES=$GPU_ID
}

# Check port availability
check_port() {
    PORT=${PORT:-8022}
    if ss -tlnp | grep -q ":$PORT "; then
        echo -e "${YELLOW}Warning: Port $PORT is in use${NC}"
        # Find next available port
        for p in $(seq 8022 8100); do
            if ! ss -tlnp | grep -q ":$p "; then
                PORT=$p
                echo -e "${GREEN}Using port $PORT instead${NC}"
                break
            fi
        done
    fi
    export PORT
}

# Load environment
load_env() {
    if [ -f .env ]; then
        echo -e "${CYAN}Loading .env configuration...${NC}"
        export $(grep -v '^#' .env | xargs)
    elif [ -f .env.example ]; then
        echo -e "${YELLOW}No .env found, using defaults from .env.example${NC}"
        cp .env.example .env
        export $(grep -v '^#' .env | xargs)
    fi
}

# Detect docker compose (plugin or standalone)
detect_compose() {
    if docker compose version &>/dev/null; then
        COMPOSE_CMD=(docker compose)
        return 0
    fi
    if command -v docker-compose &>/dev/null; then
        COMPOSE_CMD=(docker-compose)
        return 0
    fi
    return 1
}

# Fallback: plain docker run when compose is unavailable
start_with_docker_run() {
    local image="neosun/translategemma:latest"
    local gpu_devices="${NVIDIA_VISIBLE_DEVICES:-0}"

    if [[ "$1" == "--build" ]] || [[ "$1" == "-b" ]]; then
        echo -e "${CYAN}Building Docker image...${NC}"
        docker build -t "$image" .
    fi

    docker rm -f translategemma &>/dev/null || true

    docker run -d \
        --name translategemma \
        --gpus "device=${gpu_devices}" \
        -p "0.0.0.0:${PORT:-8022}:8022" \
        -e "NVIDIA_VISIBLE_DEVICES=${gpu_devices}" \
        -e "MODEL_NAME=${MODEL_NAME:-12b}" \
        -e "QUANTIZATION=${QUANTIZATION:-4}" \
        -e "BACKEND=${BACKEND:-gguf}" \
        -e "GPU_IDLE_TIMEOUT=${GPU_IDLE_TIMEOUT:-300}" \
        -e "MAX_CHUNK_LENGTH=${MAX_CHUNK_LENGTH:-80}" \
        -e "HF_ENDPOINT=${HF_ENDPOINT:-https://huggingface.co}" \
        -e "HF_HUB_ENABLE_HF_TRANSFER=1" \
        -e "HF_HOME=/app/models" \
        -v "${HOME}/.cache/translate/models:/app/models" \
        -v "${HOME}/.cache/translate/models:/root/.cache/translate/models" \
        -v "/tmp/translategemma:/tmp/translategemma" \
        --restart unless-stopped \
        "$image"
}

# Build and start
start_service() {
    echo -e "\n${CYAN}Starting TranslateGemma service...${NC}"

    if detect_compose; then
        if [[ "$1" == "--build" ]] || [[ "$1" == "-b" ]]; then
            echo -e "${CYAN}Building Docker image...${NC}"
            "${COMPOSE_CMD[@]}" build
        fi
        "${COMPOSE_CMD[@]}" up -d
    else
        echo -e "${YELLOW}Docker Compose not found, using docker run fallback.${NC}"
        echo -e "${YELLOW}Install compose for easier management:${NC}"
        echo -e "${YELLOW}  sudo apt install docker-compose${NC}"
        echo -e "${YELLOW}  # or: mkdir -p ~/.docker/cli-plugins && curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose && chmod +x ~/.docker/cli-plugins/docker-compose${NC}"
        start_with_docker_run "$@"
    fi
    
    echo -e "\n${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     TranslateGemma Started Successfully    ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo
    echo -e "  ${CYAN}Web UI:${NC}     http://0.0.0.0:$PORT"
    echo -e "  ${CYAN}API Docs:${NC}   http://0.0.0.0:$PORT/docs"
    echo -e "  ${CYAN}Health:${NC}     http://0.0.0.0:$PORT/health"
    echo -e "  ${CYAN}GPU:${NC}        $GPU_ID ($GPU_NAME)"
    echo -e "  ${CYAN}Model:${NC}      ${MODEL_NAME:-12b}-Q${QUANTIZATION:-4}"
    echo
    echo -e "  ${YELLOW}Logs:${NC}       docker logs -f translategemma"
    echo -e "  ${YELLOW}Stop:${NC}       docker compose down"
    echo
}

# Main
main() {
    check_nvidia_docker
    load_env
    select_gpu
    check_port
    start_service "$@"
}

main "$@"
