#!/usr/bin/env bash
# Runs the TCK MUST level with push notifications switched on (A2A_PUSH_ENABLED=true) and reports the PUSH-*
# requirements. Not part of the gated run: with the capability declared the TCK skips CORE-CAP-001 (error when push
# is unsupported), which tck/check_results.py requires to PASS. The TCK receiver listens on the host, so the
# connectors container reaches it as host.docker.internal.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . ./tck/pin.env; [ -f .env ] && . ./.env; set +a
TCK_DIR="${TCK_DIR:-${TMPDIR:-/tmp}/camunda-a2a-tck}"
export A2A_PUSH_ENABLED=true
COMPOSE=(docker compose -p camunda-a2a -f blueprint/docker-compose.yml --env-file .env)
"${COMPOSE[@]}" up -d --wait connectors >/dev/null
scripts/deploy.sh
mkdir -p reports; rm -rf "$TCK_DIR/reports" reports/push
(cd "$TCK_DIR" && . .venv/bin/activate && python -I run_tck.py --sut-host "http://localhost:${PROXY_PORT:-18090}" \
    --transport jsonrpc --level must -- --webhook-host=host.docker.internal >"$ROOT/reports/push.log" 2>&1)
mkdir -p reports/push && cp -R "$TCK_DIR/reports/." reports/push/
python3 -I - reports/push <<'PY'
import json, sys
per = json.load(open(sys.argv[1] + "/compatibility.json"))["per_requirement"]
for rid, v in sorted(per.items()):
    if rid.startswith("PUSH-") or rid.startswith("CORE-CAP-001"):
        print("%-18s %s" % (rid, v["transports"].get("jsonrpc", v["status"])), (v["errors"] or [""])[0][:100])
PY
export A2A_PUSH_ENABLED=false
"${COMPOSE[@]}" up -d --wait connectors >/dev/null
scripts/deploy.sh >/dev/null
echo "push switched off again"
