#!/usr/bin/env bash
# Runs the pinned a2a-tck (MUST level, jsonrpc) three times on one stack, then once more after
# `docker compose -p camunda-a2a down -v` and `up`. Each run is judged by tck/check_results.py.
#
#   tck/run.sh           full protocol: 3 runs, reset, 1 run
#   tck/run.sh --once    one run on the current stack
#
# The TCK is untrusted downloaded code: it is cloned into its own directory outside the repo
# (TCK_DIR, default $TMPDIR/camunda-a2a-tck) and run with `python -I`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . ./tck/pin.env; [ -f .env ] && . ./.env; set +a
TCK_DIR="${TCK_DIR:-${TMPDIR:-/tmp}/camunda-a2a-tck}"
PROXY_PORT="${PROXY_PORT:-18090}"
CAMUNDA_REST_PORT="${CAMUNDA_REST_PORT:-18080}"
SUT="http://localhost:${PROXY_PORT}"
COMPOSE=(docker compose -p camunda-a2a -f blueprint/docker-compose.yml --env-file .env)
MODE="${1:-full}"

prepare_tck() {
  if [ ! -d "$TCK_DIR/.git" ]; then
    mkdir -p "$TCK_DIR"
    git clone -q "$TCK_REPO" "$TCK_DIR"
  fi
  git -C "$TCK_DIR" checkout -q --force "$TCK_SHA"
  git -C "$TCK_DIR" reset -q --hard "$TCK_SHA"
  git -C "$TCK_DIR" clean -q -fdx -e .venv
  git -C "$TCK_DIR" apply "$ROOT/$TCK_PATCH"
  [ -d "$TCK_DIR/.venv" ] || (cd "$TCK_DIR" && uv venv -q .venv)
  (cd "$TCK_DIR" && . .venv/bin/activate && uv pip install -q -e . >/dev/null)
  echo "TCK pinned at $(git -C "$TCK_DIR" rev-parse HEAD) plus PRs $TCK_PRS"
}

stack_up() {
  "${COMPOSE[@]}" up -d --wait
  scripts/deploy.sh
}

one_run() {
  local label="$1" out="$ROOT/reports/$1"
  rm -rf "$TCK_DIR/reports" "$out"
  (cd "$TCK_DIR" && . .venv/bin/activate && \
    python -I run_tck.py --sut-host "$SUT" --transport jsonrpc --level must >"$ROOT/reports/$label.log" 2>&1) || true
  mkdir -p "$out" && cp -R "$TCK_DIR/reports/." "$out/"
  python3 -I tck/check_results.py "$out" --rest "http://localhost:${CAMUNDA_REST_PORT}" | tee -a "$ROOT/reports/results.txt"
}

mkdir -p reports; : > reports/results.txt
prepare_tck
stack_up
status=0
if [ "$MODE" = "--once" ]; then
  one_run run-1 || status=1
else
  for n in 1 2 3; do one_run "run-$n" || status=1; done
  echo "Resetting the stack: down -v, up"
  "${COMPOSE[@]}" down -v
  stack_up
  one_run run-after-reset || status=1
fi
exit $status
