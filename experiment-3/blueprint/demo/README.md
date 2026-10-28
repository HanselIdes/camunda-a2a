# A2A BPMN client and agent example

Ask a client AI agent to delegate through Agent2Agent (A2A) 1.0 to a server-side AI agent, then review the synthetic result.

This early-access community prototype uses stock Camunda Connectors, not native Camunda A2A support or a custom HTTP server.
It is unmaintained, intended for non-production use, and subject to the [project license](https://github.com/HanselIdes/camunda-a2a/blob/main/LICENSE.md).
Camunda does not support or certify it.

## What is in this blueprint?

| File | Modeler name or role | Purpose |
| --- | --- | --- |
| `demo/01-client-agent.bpmn` | 01 Client Agent - Ask the Server | Run a client AI agent that selects A2A tools and requests human input. |
| `profiles/basic/02-a2a-server.bpmn` | 02 A2A Server - Protocol and Discovery | Expose discovery and task webhooks, manage task state, and handle follow-up, cancellation, and queries. |
| `demo/03-server-agent-card-dispute.bpmn` | 03 Server Agent - Synthetic Card Dispute | Run the server-side AI agent and its deterministic reconciliation tool. |
| `demo/04-client-agent-ask.form` | Client request form | Collect the initial free-text request. |
| `demo/05-client-agent-confirm.form` | Client confirmation form | Collect explicit confirmation of synthetic financial inputs. |
| `demo/06-client-agent-result.form` | Client result form | Display the result and arithmetic evidence for review. |
| `demo/07-server-request-validation.dmn` | 07 Server - Validate A2A Request | Validate protocol requests. |
| `templates/08-server-a2a-rpc-endpoint.json` | Server - A2A RPC Endpoint | Configure the authenticated task webhook. |
| `templates/09-server-agent-card-endpoint.json` | Server - Agent Card Endpoint | Configure the discovery webhook. |
| `templates/10-server-http-json-v13.json` | HTTP JSON Connector, version 13 | Pinned stock outbound HTTP template. |
| Pinned upstream template | Client AI Agent Sub-process v2, version 1 | Required external template for the client agent; not redistributed here. |
| `demo/README.md` | Project instructions | Explain this imported project and how to run it. |

The numeric prefixes order the project by role: client agent, server protocol, server agent, forms, validation, then templates.
Runtime process IDs remain `a2a-rpc`, `a2a-card-dispute`, and `a2a-client`.

The 11 repository resources plus the pinned [AI Agent Job Worker version 5 template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json)
and [client AI Agent Sub-process v2 version 1 template](https://raw.githubusercontent.com/camunda/connectors/b490d065b59ffe4788319609dbe41deb25e68e3f/connectors/agentic-ai/connector-agentic-ai/element-templates/agenticai-ai-agent-subprocess.v2.json)
form the 13-resource import list. Both AI templates remain external dependencies. Before import, confirm that the
target Modeler resolves this exact ID and version; do not substitute another version. An “already available”
notice alone does not prove a version match.

## How A2A works in Camunda

The protocol is executable BPMN. Agent Card discovery belongs to the protocol process, not a separate card process.
Stock inbound Connectors expose its discovery and task webhooks. Stock outbound HTTP Connectors call the authenticated engine API.
Camunda process instances and variables hold task state, messages, and artifacts.

The `a2a-rpc` process has independent webhook starts: `CardRequested` for discovery and `RpcReceived` for task requests.
Their contexts remain `a2a-card` and `a2a`. The discovery endpoint uses the custom card template.

The client uses AI Agent Sub-process template `io.camunda.connectors.agenticai.ai-agent-subprocess.v2`,
version 1, on ad-hoc subprocess `ClientAgent`. Its four selectable root tools are arranged in a two-by-two grid.
The stock connector owns tool activation and the model feedback loop; no external agent task or loop gateways are needed.

| Client tool | Role |
| --- | --- |
| `DiscoverAgentCard` | Read the Agent Card from the configured discovery URL. |
| `SendA2AMessage` | Send an authenticated A2A message, optionally on an existing task and context. |
| `GetA2ATask` | Read task state and artifacts while work continues. |
| `AskClientForInput` | Present a Tasklist user task for server clarification and confirmed synthetic inputs. |

The client language model selects tools; the following is an intended journey, not a fixed sequence of model decisions:

1. Read the Agent Card through `DiscoverAgentCard`.
2. Send the user's request to the configured task URL using the shared API key.
3. Let the server protocol validate the request and start its configured business process.
4. If the server requests explicit confirmation, collect it through `AskClientForInput` and send it on the same task and context.
5. Use `GetA2ATask` to inspect work and report the observed result.

Every root tool returns a meaningful `toolCallResult`. During execution the connector maintains
`agentContext`; the completed response maps from the connector's local `agent` variable to `clientAgent`,
including its conversation context for result preparation. The model-call limit remains eight.
The 8.10 conversation stores each tool result as structured content blocks; the client reads the
`object` block's `content` for confirmation, task identity, and final task-state review.
The bundled `SendA2AMessage` tool has no model-supplied claim parameter: it adds a structured data part only from the
`AskClientForInput` form result. Follow-ups also reuse the task and context IDs returned by the first send instead
of accepting IDs from the model. `GetA2ATask` likewise polls the ID returned by that send. Values in the initial
free-text request or model output cannot satisfy this client confirmation step.
The business agent and reconciliation tool are separate from the protocol. The model can request the tool, but cannot supply its financial arguments.
The tool uses only deterministically validated client fields from the current message.

The protocol also supports task listing and cancellation. Business-process adaptation requires the documented task contract,
including the interrupting `a2a-cancel` hook correlated by `task.id`. See the [extended setup and task-contract guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md).

## Prerequisites

The complete client/server demo now requires **8.10 for both engine and Connectors**:
the client Sub-process template has engine constraint `^8.10`. The focused verification profile is
engine 8.10.2, stock Connectors 8.10.2, and Elasticsearch 8.19.23.
Earlier 8.9.26 / Connectors 8.9.17 evidence applies only to its pinned earlier source, not this client
or the server's revised result mapping. The server still uses the v5 connector and accepts both legacy
object results and 8.10 structured content blocks. Camunda-provided model execution and other version pairs remain unverified.

### Why 8.10, and what can I use on 8.9?

This is a requirement of the **selected client connector**, not of A2A or BPMN in general.
The [pinned Sub-process v2 template, version 1](https://raw.githubusercontent.com/camunda/connectors/b490d065b59ffe4788319609dbe41deb25e68e3f/connectors/agentic-ai/connector-agentic-ai/element-templates/agenticai-ai-agent-subprocess.v2.json)
declares engine constraint `^8.10` and worker type `io.camunda.agenticai:aiagent:subprocess:2`.
That worker handles tool activation and feedback inside the ad-hoc subprocess. The verified
Connectors 8.9.17 runtime instead contains the older `io.camunda.agenticai:aiagent-job-worker:1`
implementation; it is not the selected v2 worker. This does **not** mean that 8.9 lacks AI agents
or ad-hoc subprocesses generally.

| Package / runtime | What you can and cannot do | Evidence |
| --- | --- | --- |
| Current compact client / engine and Connectors 8.10.2 | Run the supplied client, confirmation, server, polling, and result-review journey. | [Focused authenticated run](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/verification/9c43104/README.md), with local Ollama rather than a SaaS model. |
| Current package / 8.9 | Cannot deploy and execute the compact client or complete demo as supplied. The revised server result mapping has no fresh 8.9 runtime validation. | Selected template requires `^8.10`; current runtime evidence is 8.10.2 only. |
| [Pinned Task-based package at `565adf7`](https://github.com/HanselIdes/camunda-a2a/tree/565adf7e740aa472cb0cc3f813ca43ff861e73b5/experiment-3/blueprint) / engine 8.9.26 and Connectors 8.9.17 | Use discovery, send/poll, explicit confirmation, and result review with the older client AI Agent Task and external feedback loop, not the current compact Sub-process v2 client. | [Source-pinned `69e77df` run](https://github.com/HanselIdes/camunda-a2a/blob/565adf7e740aa472cb0cc3f813ca43ff861e73b5/experiment-3/verification/69e77df/README.md); local Ollama, not a blanket 8.9 compatibility claim. |

If staying on 8.9, use that **whole immutable package and its own README/dependencies**, rather than
combining it with current files. No fallback variant is maintained here. A template being visible or
importable in Modeler does not establish runtime compatibility. Lowering BPMN version metadata or
mixing engine and Connectors minor versions is not a supported workaround.

Version compatibility is separate from the [profile limitations](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/demo/README.md#limits-and-troubleshooting):
8.10 does not add push, streaming, OAuth, or per-user authorization to this Basic demo.

You need an authenticated engine, stock Connectors, trusted HTTPS endpoints, and a reachable OpenAI-compatible language model.
Keep local validation overrides separate from the public secret defaults below.

## Configure secrets and endpoints

Configure these names in the **8.10 cluster's default secret store**. Never put credentials or keys
in BPMN files. Connector-only `SECRET_*` environment variables are not a substitute for this store.

| Connector secret | Value |
| --- | --- |
| `ENGINE_URL` | Engine REST base URL without `/v2`, reachable from Connectors. |
| `ENGINE_USERNAME`, `ENGINE_PASSWORD` | Authorized engine API credentials. |
| `A2A_API_KEY` | Shared task-access key for clients in one trust boundary. |
| `A2A_AGENT_PROCESS` | `a2a-card-dispute`. |
| `A2A_RPC_URL` | Complete HTTPS task webhook URL, including any cluster prefix and `/inbound/a2a`. |
| `A2A_AGENT_CARD_URL` | Complete HTTPS discovery URL, including any cluster prefix and `/inbound/a2a-card`. |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT` | OpenAI-compatible base URL, including `/v1`. |
| `CAMUNDA_PROVIDED_LLM_API_KEY` | Your model-provider credential. |
| `CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL` | Model identifier available from that provider. |

The client references the Camunda-provided LLM secret names through these connector inputs:

```text
provider.openai.backend.custom.endpoint==camunda.secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT
provider.openai.backend.custom.authentication.apiKey==camunda.secrets.CAMUNDA_PROVIDED_LLM_API_KEY
provider.openai.model.model==camunda.secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL
```

The client selects provider `openai`, API `completions`, custom backend and API-key authentication.
The server's pinned v5 template retains its `openaiCompatible` fields. These secret references do not establish compatibility with a particular
Camunda SaaS provider; verify the endpoint and model through your authorized environment.

Both A2A URLs must resolve from external clients and the Connectors runtime. Use matching certificate names and configure trusted issuers.
Do not disable certificate checks. Each whole-value input uses FEEL `=camunda.secrets.NAME`.
Inside an existing FEEL context, use an unquoted reference, for example
`={"X-A2A-Api-Key": camunda.secrets.A2A_API_KEY}`; do not quote it as text.
URL composition uses `=camunda.secrets.ENGINE_URL + "/v2/..."`.
The engine persists references rather than credentials and injects resolved values for jobs;
Connectors also resolves references when evaluating inbound properties.
The [runtime setup guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md#cluster-secret-store)
explains store setup and permissions. Missing secrets or resolution permissions prevent execution.

The demonstrated same-runtime client/server flow requires `CAMUNDA_CLIENT_EXECUTION_THREADS=4`.
The recorded profile also sets `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`.
The Self-Managed low-latency profile requires explicit exporter settings and has resource-cost tradeoffs.
Follow the [runtime setup guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md) before deployment. Import does not configure runtime settings.

## Deploy and run

For this revised import, start with a fresh Modeler project when possible. Importing or renaming resources
does not remove the earlier standalone `a2a-card.bpmn`; do not deploy it alongside
`profiles/basic/02-a2a-server.bpmn`, which now contains discovery.

1. Import the 11 repository resources and both pinned upstream AI Agent templates. Confirm that each BPMN template assignment resolves to its exact stated version.
2. Configure secrets and the runtime requirements above.
3. Deploy the selected BPMN, DMN, and form resources together.
4. Wait for healthy `CardRequested` and `RpcReceived` inbound Connectors in process `a2a-rpc`.
5. Confirm that the discovery URL returns an Agent Card and unauthenticated task requests return HTTP 401, not 404.
6. Start **01 Client Agent - Ask the Server** (`a2a-client`) using its start form.
7. Enter the synthetic request below.

> Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool.

Free text is context, not confirmation, even when it contains every value. If the server requests confirmation, open the client agent's
Tasklist user task using `05-client-agent-confirm.form` and enter the requested values:

| Confirmation field | Value |
| --- | --- |
| Merchant | `Northwind Electronics` |
| Currency | `USD` |
| First charge amount | `49.95` |
| Second charge amount | `49.95` |
| Expected amount | `49.95` |
| Synthetic-only confirmation | Checked. |

The client agent can send structured data on the original task and context. Review its tool outcomes and final result.
For the sample values, the expected `reconciliation` artifact is:

```json
{
  "merchant": "Northwind Electronics",
  "currency": "USD",
  "chargeAmounts": [49.95, 49.95],
  "expectedAmount": 49.95,
  "paidAmount": 99.9,
  "overchargeAmount": 49.95,
  "matchingAmounts": true,
  "recommendation": "REQUEST_HUMAN_REVIEW",
  "syntheticOnly": true
}
```

Complete the review task to finish the client process. This example performs no refund, financial action, real dispute decision,
fraud determination, or financial integration.

## Use an external A2A client

Read `A2A_AGENT_CARD_URL`, then send A2A 1.0 JSON-RPC requests to `A2A_RPC_URL` with the `X-A2A-Api-Key` header.
The supplied BPMN client uses these explicit URLs, not the stock A2A 0.3 client connector.

An external client can include one structured data part in the initial message for one-shot execution:

```json
{
  "data": {
    "syntheticClaim": {
      "merchant": "Northwind Electronics",
      "currency": "USD",
      "chargeAmounts": [49.95, 49.95],
      "expectedAmount": 49.95,
      "syntheticOnly": true
    }
  }
}
```

This is a message part, not a complete JSON-RPC request. For clarification, include it in a follow-up with the original
`taskId` and `contextId`. Missing, partial, malformed, or duplicate confirmation returns `INPUT_REQUIRED` without a reconciliation
artifact. The tool does not merge financial fields from earlier messages or model output. See the [complete request examples](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md#run-the-demonstration).

## Limits and troubleshooting

Use the Basic API-key profile only. Push notifications are off. Streaming, A2A 0.3 interoperability, and per-user authorization are unsupported.
Do not infer full A2A conformance from these example operations.

An HTTP failure can occur after business work starts. Never blindly retry an ambiguous submission. Inspect task and engine state first.
Duplicate submissions can create independent tasks; there is no side-effect deduplication or exactly-once guarantee.

HTTP 404 at a webhook can mean its inbound Connector registration is pending. Inspect inbound status and engine incidents before repeating requests.
Use the [extended guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md) for deployment and recovery details.

Source and community issue reports: [HanselIdes/camunda-a2a](https://github.com/HanselIdes/camunda-a2a).
Issue reports carry no response or maintenance commitment.
