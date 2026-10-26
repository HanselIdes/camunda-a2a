# A2A community blueprint candidate

**Non-production only; not release-ready.** This unmaintained community blueprint is subject to the
[license and licensing limitations](../../README.md#license-and-support). Marketplace import, conformance,
the compatibility matrix, reliability checks and fresh-adopter timing remain separate release gates.
SaaS runtime support is unverified.

The demonstration is a BPMN client calling an A2A 1.0 JSON-RPC endpoint, which starts a server-side AI agent.
The agent asks for missing input or calls a native BPMN tool to reconcile two synthetic charges.
The client receives the arithmetic evidence and displays it in a review form. No refund, real dispute decision,
fraud determination, financial integration, document processing or unreleased prototype feature is included.

## Verified configuration

| Component | Version or setting |
|-----------|--------------------|
| Self-Managed engine | Camunda 8.8.21, Basic authentication and platform authorizations enabled |
| Stock Connectors | 8.9.0; no custom worker or custom HTTP server |
| Secondary storage | Elasticsearch 8.17.0 |
| Model | Local Ollama `qwen3-coder-30b-64k:latest`, digest `13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253` |
| AI Agent template | `io.camunda.connectors.agenticai.aiagent.jobworker.v1`, version 5 |
| Client HTTP template | `io.camunda.connectors.HttpJson.v2`, version 12 |
| Transport | Direct Connectors HTTPS, with certificate verification on both external and BPMN clients |
| Runtime settings | `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`, `CAMUNDA_CLIENT_EXECUTION_THREADS=4` |

This is an **8.8 engine with 8.9 Connectors** configuration, not matched-8.8 proof. Other combinations and model
providers are not established by this result. The local check uses an isolated, disposable cluster and synthetic data.
Modeler import and Tasklist form rendering still require their own observed checks.

The execution-thread setting matters when client and server use the same Connectors runtime: a synchronous
client HTTP job must not occupy the only job-execution thread while the server needs another HTTP job.
The four-thread configuration passed the supplied client flow. It is not a capacity guarantee.

## Prepare the cluster

Start timing an adoption attempt only after the cluster, Modeler, runtime, model and credentials are ready.
Keep the engine API authenticated. Configure the stock Connectors runtime's engine connection as usual; the
engine credentials below also authenticate the protocol's REST calls.

Provide HTTPS on the **Connectors runtime itself**, or through an optional TLS terminator. With stock Spring Boot
Connectors, direct TLS uses `SERVER_SSL_ENABLED=true`, `SERVER_SSL_KEY_STORE`, `SERVER_SSL_KEY_STORE_TYPE=PKCS12`
and `SERVER_SSL_KEY_STORE_PASSWORD`. Use a certificate valid for the advertised hostname. Clients must trust its
issuer; do not disable certificate verification. The local verifier creates a disposable certificate and truststore,
not a production certificate.

If a private issuer is used, configure the JVM truststore for outbound client calls as well. Keep private keys,
keystore passwords and API keys out of BPMN, repository files, screenshots and reports.

Use `CAMUNDA_CONNECTOR_SECRETPROVIDER_ENVIRONMENT_PREFIX=SECRET_` if supplying local connector secrets through
environment variables. For example, connector secret `ENGINE_URL` is then supplied as `SECRET_ENGINE_URL`.
Use your deployment's normal secret provider instead where appropriate.

| Connector secret | Required value |
|------------------|----------------|
| `ENGINE_URL` | Engine REST base URL without `/v2`, reachable from Connectors |
| `ENGINE_USERNAME`, `ENGINE_PASSWORD` | Authorized engine credentials; do not disable platform authentication |
| `A2A_API_KEY` | Shared key for task operations; supply it only over HTTPS |
| `A2A_AGENT_PROCESS` | `a2a-card-dispute` |
| `A2A_RPC_URL` | Complete HTTPS webhook URL, including any cluster prefix and `/inbound/a2a` |
| `A2A_AGENT_CARD_URL` | Complete HTTPS discovery URL, including any cluster prefix and `/inbound/a2a-card` |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT` | OpenAI-compatible base URL reachable from Connectors, including `/v1` |
| `CAMUNDA_PROVIDED_LLM_API_KEY` | Provider credential; the tested local Ollama setup uses its documented dummy key |
| `CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL` | `qwen3-coder-30b-64k:latest` for the verified local configuration |

The `CAMUNDA_PROVIDED_LLM_*` names are configuration names, not a claim that this check used Camunda's SaaS model.
For Docker Desktop, a host-local Ollama service can be reached through `host.docker.internal`; do not assume
that hostname works on a remote cluster. Model inference needs sufficient local resources.

## Import and deploy

Use only the Basic profile for this candidate. Do not import or deploy the OAuth profile alongside it: the profiles
share executable process IDs.

Import these resources into one Modeler project:

| Resource | Purpose |
|----------|---------|
| [profiles/basic/a2a-protocol.bpmn](profiles/basic/a2a-protocol.bpmn) | Authenticated, push-disabled protocol; deploy unchanged |
| [../dmn/a2a-validate.dmn](../dmn/a2a-validate.dmn) | Protocol request validation |
| [demo/a2a-card.bpmn](demo/a2a-card.bpmn) | Direct discovery card with actual skill, complete URL and API-key scheme |
| [demo/a2a-card-dispute.bpmn](demo/a2a-card-dispute.bpmn) | AI agent, reconciliation tool and follow-up loop |
| [demo/a2a-client.bpmn](demo/a2a-client.bpmn) | BPMN client with explicit card discovery, authenticated calls and polling |
| [demo/a2a-client-ask.form](demo/a2a-client-ask.form) | Synthetic starting request |
| [demo/a2a-client-answer.form](demo/a2a-client-answer.form) | Clarification reply |
| [demo/a2a-client-result.form](demo/a2a-client-result.form) | Returned result and arithmetic evidence |

Import the three JSON files in [templates/](templates/) and the
[upstream AI Agent version 5 template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json)
as element templates, using the Modeler's template-import workflow. The stock templates are pinned; the two blueprint templates configure the authenticated RPC endpoint
and public discovery card. Do not use the archived experiment's unauthenticated RPC template.

The AI template remains an upstream dependency with its own proprietary module terms; it is not redistributed
in the blueprint ZIP. See [third-party notices](../../THIRD_PARTY_NOTICES.md).

Deploy all eight BPMN/DMN/form resources together, so the forms and decision are available to the processes.
No generator execution, protocol editing, custom worker, nginx route or standard-path ingress is required.
Wait for both webhook registrations to become healthy before testing.

## Run the demonstration

Start process `a2a-client` through its start form, or with a `question` variable:

```json
{
  "question": "Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool."
}
```

The client explicitly fetches the card to obtain the agent name and skills. It sends credentials only to the
configured `A2A_RPC_URL`, not an arbitrary URL returned by a card. This is explicit BPMN discovery, not hidden
discovery by the stock A2A 0.3 client connector.

The expected reconciliation artifact contains merchant `Northwind Electronics`, currency `USD`, paid amount `99.9`,
expected amount `49.95`, overcharge `49.95`, and recommendation `REQUEST_HUMAN_REVIEW`.
The result form shows these values. Its status text is derived from actual tool evidence, rather than forwarding
unvalidated model prose. Review and complete the final user task.

For clarification, start with `Please review a synthetic card dispute.`. Answer the agent's question with
`49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD.`.
The same A2A task should complete with four history messages, not ask for already-supplied amounts again.

An external client can fetch the complete `A2A_AGENT_CARD_URL` and send A2A 1.0 `SendMessage` requests to the card's
JSON-RPC interface using `X-A2A-Api-Key`. `GetTask` polls the returned task ID. Missing and invalid keys must be
rejected without business work. Standard `/.well-known/agent-card.json` discovery requires an optional route to the
direct discovery webhook; it has not been independently verified for this candidate.

## Adapt the business process

The process contract is independent of the card-dispute tool: a selected process receives `task` and `req`, calls
`a2a-task-update` with `{state, text, artifacts}`, and explicitly maps the updated `task` back to its root scope.
For input-required turns it waits for `a2a-send`, correlated by `task.id`, and applies the follow-up mappings shown
in the supplied agent. Do not start another task or discard its conversation when handling a follow-up.

[../bpmn/a2a-echo.bpmn](../bpmn/a2a-echo.bpmn) is the separately tested deterministic contract reference, not the
public demonstration. When selecting a different process, update the discovery card's name, description and skills
to describe that process. Selecting `A2A_AGENT_PROCESS` does not automatically rewrite the card.

Leave the literal-input encoder and `data.userPrompt.prompt =jsonPrompt` mapping intact. They preserve numeric-leading,
JSON-like, quoted, backslash, control-character and leading-equals text through the stock connector's string binding.
System instructions and business tools are modelled in the agent, not the protocol.

## Operational boundary and remaining gates

The API key establishes one shared trust boundary, not per-user task authorization. Possession of the key permits
operations on this agent's tasks. Engine permissions and secret distribution must match that boundary.
Task search uses the selected agent process; existing-task lookups have a three-second indexing/variable window.
Push, streaming and A2A 0.3 interoperability are not advertised.

Terminal-state races, bulk concurrency across two agents, duplicate-request behavior, pagination/retention,
restart recovery, expired/insufficient credentials, the full version matrix, independent clients, exact-candidate
conformance, Modeler/form usability and a timed fresh adoption remain unverified. Do not infer exactly-once
side effects or a retention guarantee. Engine/connector incidents are operator-visible failures, not successful
business outcomes.

The original experiments, fixture diagrams, conformance patches and old generated templates/icons are nonshipping
verification or historical material. They are not part of the Modeler import set above.
Actual Marketplace import, licensing authority, unmaintained eligibility and publication remain separate gates.
Contact the [repository issue tracker](https://github.com/HanselIdes/camunda-a2a/issues); no support response is promised.

## Reproduce the candidate checks

These are contributor commands, not installation prerequisites. With the documented Docker/model prerequisites ready:

```sh
python3 experiment-3/tests/runtime/verify.py
cd experiment-3/tests && mvn -q test
```

The runtime verifier uses only loopback-published ports 38880/38885, an isolated Compose project and random temporary
credentials. It creates a certificate and truststore with `openssl`/`keytool`, starts the pinned stack, deploys the
committed resources, checks authentication/discovery, expected real-model results, verbatim numeric-leading continuation
and final BPMN client completion, then removes its containers. It does not stop or reuse unrelated clusters.
Docker, Python 3, OpenSSL, a JDK/keytool and the already-running local Ollama model are required.
`PROOF_AGENT_PROCESS=a2a-echo` selects the deterministic contract check without model inference.
Model-input diagnostics contain synthetic prompts only and are stored under ignored `experiment-3/reports/runtime`.
`PROOF_REPORT_DIR` can select another report directory.

`python3 experiment-3/tools/build_blueprint.py --check` checks the committed candidate assets against their builder,
using immutable upstream template URLs. `python3 experiment-3/tools/build_core.py --check` checks both protocol profiles.
Neither command changes an adopter's deployment. A successful runtime check is not a conformance or Modeler-import pass.
