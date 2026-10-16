#!/usr/bin/env bash
# Runs the Playwright demo against the a2a-inspector web UI and the camunda-a2a stack.
#
#   demo/run-demo.sh              headless run, screenshots in demo/artifacts/
#   HEADED=1 demo/run-demo.sh     watch it in a browser window, slowed down
#   RECORD=1 demo/run-demo.sh     also record a video of every scenario
#
# Needs the stack from MANUAL-VERIFICATION.md step 1 to be up (AGENT_URL, default http://localhost:18090),
# Node.js, uv, git, and Ollama running with the model. The inspector is untrusted downloaded code: it is cloned
# into INSPECTOR_DIR (default $TMPDIR/a2a-inspector) outside this repo at a pinned commit and started on a free
# local port; it is stopped again when the script ends.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
INSPECTOR_SHA="8aa064639af106ff771d60428ef6d460f5454743"
INSPECTOR_DIR="${INSPECTOR_DIR:-${TMPDIR:-/tmp}/a2a-inspector}"
AGENT_URL="${AGENT_URL:-http://localhost:18090}"
export AGENT_URL

curl -sf "$AGENT_URL/.well-known/agent-card.json" >/dev/null || { echo "agent not reachable at $AGENT_URL: start the stack first"; exit 1; }

# Keep the model loaded for the whole run: a reload of a large model while the demo waits looks like a hang.
MODEL="${OLLAMA_MODEL:-qwen3-coder-30b-64k}"
curl -sf http://localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"keep_alive\":\"30m\"}" >/dev/null \
  || echo "warning: could not warm up $MODEL on the local Ollama"

if [ ! -d "$INSPECTOR_DIR/.git" ]; then
  git clone -q https://github.com/a2aproject/a2a-inspector.git "$INSPECTOR_DIR"
fi
git -C "$INSPECTOR_DIR" fetch -q origin "$INSPECTOR_SHA" 2>/dev/null || true
git -C "$INSPECTOR_DIR" checkout -q "$INSPECTOR_SHA"
(cd "$INSPECTOR_DIR" && uv sync -q)
(cd "$INSPECTOR_DIR/frontend" && npm install --silent && npm run build --silent)

PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
(cd "$INSPECTOR_DIR/backend" && exec uv run -- uvicorn app:app --host 127.0.0.1 --port "$PORT" >"$INSPECTOR_DIR/inspector.log" 2>&1) &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/" >/dev/null && break; sleep 1; done
export INSPECTOR_URL="http://127.0.0.1:$PORT"

cd "$HERE"
npm install --silent
npx playwright install chromium >/dev/null
npx playwright test --reporter=list
