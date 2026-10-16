#!/usr/bin/env bash
# Starts a local c8run 8.10.2 with the secrets experiment 2 needs, deploys the two-agent diagram and its forms, and
# waits until the connectors runtime serves its webhooks. c8run uses fixed ports: 8080 (engine, Operate, Tasklist),
# 8086 (connectors), 26500. Connector secrets are passed as SECRET_* environment variables. The agents use
# camunda.secrets.CAMUNDA_PROVIDED_LLM_*, which the engine reads from c8run's local secret store; set them once with
#   c8run secrets set CAMUNDA_PROVIDED_LLM_API_ENDPOINT CAMUNDA_PROVIDED_LLM_API_KEY CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL
#
#   scripts/c8run-demo.sh            start (or restart) c8run, deploy, print the URLs
#   scripts/c8run-demo.sh deploy     deploy only, to a c8run that is already running with these secrets
#   scripts/c8run-demo.sh stop       stop c8run (its data is kept)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${C8_VERSION:-8.10.2}"
REST=http://localhost:8080
CONN=http://localhost:8086

if [ "${1:-}" = "stop" ]; then
  c8ctl cluster stop
  exit 0
fi

if [ "${1:-}" != "deploy" ]; then
  if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
    c8ctl cluster stop
  fi
  # c8run 8.10.2 keeps camunda.secrets.* references unresolved in connector jobs, so hand every secret of the
  # local store (c8run secrets set ...) to the connectors runtime, which resolves {{secrets.NAME}} from SECRET_NAME
  C8RUN="$HOME/Library/Caches/c8run/c8run-$VERSION/c8run-$VERSION/c8run"
  [ -x "$C8RUN" ] || c8ctl cluster install "$VERSION"
  STORE="$("$C8RUN" secrets path)"
  for f in "$STORE"/*; do
    name="$(basename "$f")"
    [[ "$name" =~ ^[A-Za-z0-9_]+$ ]] || continue
    value="$(cat "$f")"
    # a value typed with surrounding quotes at the hidden prompt is stored with them; read it like a dotenv value
    if [[ ${#value} -ge 2 && ( ( $value == \'*\' ) || ( $value == \"*\" ) ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "SECRET_$name=$value"
  done
  export SECRET_A2A_CONNECTORS_URL="$CONN"
  export SECRET_A2A_PUSH_TOKEN="${A2A_PUSH_TOKEN:-local-push-token}"
  export CAMUNDA_CLIENT_REQUEST_TIMEOUT=PT120S
  c8ctl cluster start "$VERSION"
  for _ in $(seq 1 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' $CONN/actuator/health)" = 200 ] && break
    sleep 3
  done
fi

args=(-F "resources=@$ROOT/bpmn/a2a-two-agents.bpmn")
for f in "$ROOT"/forms/*.form; do args+=(-F "resources=@$f"); done
OUT="$(mktemp)"
code=$(curl -s -o "$OUT" -w '%{http_code}' -X POST "$REST/v2/deployments" "${args[@]}")
[ "$code" = 200 ] || { echo "deploy failed: HTTP $code"; cat "$OUT"; exit 1; }
key=$(jq -r '.deployments[] | select(.processDefinition.processDefinitionId == "a2a-two-agents") | .processDefinition.processDefinitionKey' "$OUT")
echo "deployed a2a-two-agents, definition key $key"

# the connectors runtime polls for new definitions; wait until its webhooks belong to this version
for _ in $(seq 1 90); do
  if curl -s "$CONN/inbound" | jq -e --arg k "$key" '[.[] | .elements[] | select(.bpmnProcessId == "a2a-two-agents") | (.processDefinitionKey | tostring)] | index($k) != null' >/dev/null 2>&1; then
    echo "connectors serve version $key"
    break
  fi
  sleep 2
done

cat <<EOF

Tasklist:  $REST/tasklist/processes   (c8run default login: demo / demo)
           Processes tab > "A2A two agents" > Start process
Operate:   $REST/operate
EOF
