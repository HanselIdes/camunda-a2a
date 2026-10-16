#!/usr/bin/env bash
# Lints every BPMN file with the committed .bpmnlintrc. Run from the repo root (c8ctl uses the .bpmnlintrc in the
# working directory). c8ctl takes one file per call.
set -uo pipefail
cd "$(dirname "$0")/.."
status=0
for f in bpmn/*.bpmn; do
  out="$(c8ctl bpmn lint "$f" 2>&1)" || status=1
  if ! grep -q "No issues found" <<<"$out"; then status=1; fi
  echo "$f: $(tail -1 <<<"$out")"
done
exit $status
