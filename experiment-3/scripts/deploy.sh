#!/usr/bin/env bash
# Deploys every bpmn/, dmn/ and forms/ resource to the local stack and waits until the webhooks answer.
# A2A_EXTRA_RESOURCES names one more directory to deploy, for example tck/fixture for the TCK runs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a
REST="http://localhost:${CAMUNDA_REST_PORT:-28080}"
CONN="http://localhost:${CONNECTORS_PORT:-28085}"
args=()
EXTRA="${A2A_EXTRA_RESOURCES:+$ROOT/$A2A_EXTRA_RESOURCES}"
for f in "$ROOT"/bpmn/*.bpmn "$ROOT"/dmn/*.dmn "$ROOT"/forms/*.form ${EXTRA:+"$EXTRA"/*.bpmn "$EXTRA"/*.dmn}; do
  [ -f "$f" ] && args+=(-F "resources=@$f")
done
OUT="$(mktemp)"
code=$(curl -s -o "$OUT" -w '%{http_code}' -X POST "$REST/v2/deployments" "${args[@]}")
[ "$code" = 200 ] || { echo "deploy failed: HTTP $code"; cat "$OUT"; exit 1; }
echo "deployed $(( ${#args[@]} / 2 )) resources"
# Wait until the connectors runtime serves the versions that were just deployed (it polls for new definitions),
# not merely until the webhooks answer, because the previous version keeps answering until then.
python3 - "$OUT" "$CONN" <<'PY'
import json, sys, time, urllib.request
deployed = {d["processDefinition"]["processDefinitionId"]: d["processDefinition"]["processDefinitionKey"]
            for d in json.load(open(sys.argv[1]))["deployments"] if d.get("processDefinition")}
want = {pid: key for pid, key in deployed.items() if pid in ("a2a-card", "a2a-rpc")}
deadline = time.time() + 180
while time.time() < deadline:
    try:
        active = {}
        for e in json.load(urllib.request.urlopen(sys.argv[2] + "/inbound", timeout=10)):
            for el in e["elements"]:
                active[el["bpmnProcessId"]] = str(el["processDefinitionKey"])
        # a definition that is unchanged keeps its old key, which the deployment response repeats
        if all(active.get(pid) == str(key) for pid, key in want.items()):
            print("connectors serve the deployed versions: " + ", ".join(sorted(want)))
            sys.exit(0)
    except Exception:
        pass
    time.sleep(2)
sys.exit("connectors did not pick up the deployed versions in 180 s")
PY
