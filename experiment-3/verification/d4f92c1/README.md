# Focused client-agent end-to-end verification

**PASS** for source commit `d4f92c1f97e2e22fdf08b781cab881b0be65725f`, with a clean worktree before
and after the run. The [sanitized runtime report](client-agent-e2e.json) records the exact runtime
image tags and result.

The run deployed the seven BPMN, DMN, and form resources to an authenticated, disposable Camunda
Self-Managed environment using Camunda 8.9.26, stock Connectors 8.9.17, and Elasticsearch 8.19.23.
It verified direct HTTPS Agent Card discovery, rejection of missing and invalid API keys, and the
client-agent flow through the actual AI Agent Task v8 and server AI Agent Job Worker v5:

- The initial A2A message contained no structured claim data.
- The client requested explicit user confirmation, then sent exactly one structured claim part
  matching the confirmation form.
- Follow-up sends reused the task and context returned by the first send. Polling observed that
  same task reach `TASK_STATE_COMPLETED`.
- The observed reconciliation artifact matched the expected synthetic result, and the client process
  completed after result review.

The run used a local Ollama validation override. The shipped
`CAMUNDA_PROVIDED_LLM_*` secret references were unchanged, but this does **not** verify Camunda SaaS
model access or execution. This evidence covers only the exact runtime profile above; it does not
establish 8.8 support, all 8.9+ combinations, full A2A conformance, or Marketplace eligibility.

The executable assertions are in
[`verify_client_agent.py`](../../tests/runtime/verify_client_agent.py) at the pinned source commit.
Earlier failure and historical evidence records remain separate and unchanged.
