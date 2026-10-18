#!/usr/bin/env bash
# Runs the SHOULD and MAY levels (not part of the goal) and lists every requirement that is not PASS.
# Best effort: needs the stack from tck/run.sh to be up and the TCK prepared by it.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . ./tck/pin.env; [ -f .env ] && . ./.env; set +a
TCK_DIR="${TCK_DIR:-${TMPDIR:-/tmp}/camunda-a2a-3-tck}"
SUT="http://localhost:${PROXY_PORT:-28090}"
mkdir -p reports
for level in should may; do
  rm -rf "$TCK_DIR/reports" "reports/$level"
  (cd "$TCK_DIR" && . .venv/bin/activate && python -I run_tck.py --sut-host "$SUT" --transport jsonrpc --level "$level" \
      >"$ROOT/reports/$level.log" 2>&1)
  mkdir -p "reports/$level" && cp -R "$TCK_DIR/reports/." "reports/$level/"
  python3 -I - "reports/$level" "$level" <<'PY'
import json, sys
per = json.load(open(sys.argv[1] + "/compatibility.json"))["per_requirement"]
bad = [(k, v) for k, v in per.items() if v["level"] == sys.argv[2].upper() and
       any(s == "FAIL" for t, s in v["transports"].items() if t in ("jsonrpc", "agent_card"))]
ok = [k for k, v in per.items() if v["level"] == sys.argv[2].upper() and
      v["transports"].get("jsonrpc", v["transports"].get("agent_card")) == "PASS"]
print("%s: %d PASS, %d FAIL" % (sys.argv[2].upper(), len(ok), len(bad)))
for k, v in bad:
    print("  FAIL %s: %s" % (k, (v["errors"] or [""])[0][:150]))
PY
done
