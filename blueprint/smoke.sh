#!/usr/bin/env bash
# Brings up an isolated stack (own compose project, free ports) from this checkout, warms the model up,
# runs blueprint/smoke.py against it, and tears the stack down again.
#
#   blueprint/smoke.sh            run and tear down
#   KEEP_STACK=1 blueprint/smoke.sh   leave the stack running afterwards
#
# Needs Docker, python3 and a local Ollama with the model of OLLAMA_MODEL (default qwen3-coder-30b-64k).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PROJECT="${SMOKE_PROJECT:-camunda-a2a-smoke}"
MODEL="${OLLAMA_MODEL:-qwen3-coder-30b-64k}"

free_ports() {
  python3 - "$@" <<'PY'
import socket, sys
socks, ports = [], []
for _ in range(int(sys.argv[1])):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); socks.append(s); ports.append(str(s.getsockname()[1]))
print(" ".join(ports))
PY
}

read -r REST GRPC MGMT CONN PROXY <<<"$(free_ports 5)"
ENV_FILE="$ROOT/.env.smoke"
export ENV_FILE
cat > "$ENV_FILE" <<EOF
COMPOSE_PROJECT_NAME=$PROJECT
CAMUNDA_REST_PORT=$REST
CAMUNDA_GRPC_PORT=$GRPC
CAMUNDA_MGMT_PORT=$MGMT
CONNECTORS_PORT=$CONN
PROXY_PORT=$PROXY
A2A_PUBLIC_URL=http://localhost:$PROXY
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_MODEL=$MODEL
EOF
COMPOSE=(docker compose -p "$PROJECT" -f blueprint/docker-compose.yml --env-file "$ENV_FILE")
cleanup() { [ "${KEEP_STACK:-0}" = 1 ] || "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Checking Ollama and warming up $MODEL"
curl -sf http://localhost:11434/api/tags | python3 -c "
import json, sys
names = [m['name'] for m in json.load(sys.stdin)['models']]
sys.exit(0 if any(n.split(':')[0] == '$MODEL'.split(':')[0] for n in names) else 'model $MODEL is not pulled: ' + ', '.join(names))"
curl -sf http://localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"keep_alive\":\"30m\"}" >/dev/null

echo "Starting stack $PROJECT on proxy port $PROXY"
"${COMPOSE[@]}" up -d --wait
scripts/deploy.sh
python3 blueprint/smoke.py "http://localhost:$PROXY"
