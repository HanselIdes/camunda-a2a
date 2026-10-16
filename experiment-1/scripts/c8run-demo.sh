#!/usr/bin/env bash
# Starts a local c8run 8.10.2, deploys the agent (server) and the a2a-client process, and prints where to start
# the client in Tasklist. The connector secrets are passed as SECRET_* environment variables, so nothing is written
# to the c8run secrets store. c8run uses fixed ports: 8080 (engine, Operate, Tasklist), 8086 (connectors), 26500.
#
#   scripts/c8run-demo.sh          start, deploy, print the URLs
#   scripts/c8run-demo.sh stop     stop the cluster again (c8run data is kept; add --purge to the stop to wipe it)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${C8_VERSION:-8.10.2}"

if [ "${1:-}" = "stop" ]; then
  c8ctl cluster stop
  exit 0
fi

for port in 8080 8086 26500; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is already in use. Another cluster may be running; stop it (c8ctl cluster stop) or free the port." >&2
    exit 1
  fi
done

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3-coder-30b-64k}"
if ! curl -sf -o /dev/null http://localhost:11434/api/tags; then
  echo "Ollama does not answer on localhost:11434. The agent needs it (model $OLLAMA_MODEL)." >&2
  exit 1
fi

export SECRET_ENGINE_URL=http://localhost:8080
export SECRET_A2A_PUBLIC_URL=http://localhost:8086/inbound
export SECRET_A2A_AGENT_CARD_URL=http://localhost:8086/inbound/a2a-card
export SECRET_A2A_PUSH_ENABLED=false
export SECRET_OLLAMA_BASE_URL=http://localhost:11434/v1
export SECRET_OLLAMA_MODEL="$OLLAMA_MODEL"
export CAMUNDA_CLIENT_REQUEST_TIMEOUT=PT120S

c8ctl cluster start "$VERSION"
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8086/actuator/health)" = 200 ] && break
  sleep 3
done

# ENV_FILE points nowhere so the ports of the docker compose stack in .env are not used
ENV_FILE=/nonexistent CAMUNDA_REST_PORT=8080 CONNECTORS_PORT=8086 "$ROOT/scripts/deploy.sh"

# keep the model loaded, a cold 30B model needs more than a minute for its first answer
curl -s -o /dev/null http://localhost:11434/api/generate \
  -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":\"30m\"}" || true

cat <<EOF

Cluster is up and the processes are deployed.
  Tasklist:  http://localhost:8080/tasklist/processes   (c8run default login: demo / demo)
             Processes tab > "A2A client: ask the agent" > Start process
  Operate:   http://localhost:8080/operate
  Agent:     http://localhost:8086/inbound/a2a-card
Follow one conversation across client and server:
  python3 scripts/token-trace.py --wait-seconds 120
Stop:        scripts/c8run-demo.sh stop
EOF
