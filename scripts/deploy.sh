#!/usr/bin/env bash
# Deploys every bpmn/ and dmn/ resource to the local stack and waits until the webhooks answer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
REST="http://localhost:${CAMUNDA_REST_PORT:-18080}"
CONN="http://localhost:${CONNECTORS_PORT:-18085}"
args=()
for f in "$ROOT"/bpmn/*.bpmn "$ROOT"/dmn/*.dmn; do
  [ -f "$f" ] && args+=(-F "resources=@$f")
done
code=$(curl -s -o /tmp/a2a-deploy.json -w '%{http_code}' -X POST "$REST/v2/deployments" "${args[@]}")
[ "$code" = 200 ] || { echo "deploy failed: HTTP $code"; cat /tmp/a2a-deploy.json; exit 1; }
echo "deployed $(( ${#args[@]} / 2 )) resources"
for i in $(seq 1 60); do
  c=$(curl -s -o /dev/null -w '%{http_code}' "$CONN/inbound/a2a-card" || true)
  [ "$c" = 200 ] && { echo "a2a-card webhook ready"; exit 0; }
  sleep 2
done
echo "a2a-card webhook did not become ready"; exit 1
