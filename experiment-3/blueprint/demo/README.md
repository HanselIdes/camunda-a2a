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
| Camunda template catalog | Client AI Agent Task, version 8 | Required catalog template for the client agent; not redistributed here. |
| `demo/README.md` | Project instructions | Explain this imported project and how to run it. |

The numeric prefixes order the project by role: client agent, server protocol, server agent, forms, validation, then templates.
Runtime process IDs remain `a2a-rpc`, `a2a-card-dispute`, and `a2a-client`.

The 11 repository resources plus the pinned [AI Agent Job Worker version 5 template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json)
form the 12-resource import list. The client also requires Camunda AI Agent Task template
`io.camunda.connectors.agenticai.aiagent.v1@8`, which `c8ctl element-template info` confirmed available
in the configured template catalog. Its JSON is not redistributed here. Before import, confirm that the
target Modeler resolves this exact ID and version; do not substitute another version. An “already available”
notice alone does not prove a version match.

## How A2A works in Camunda

The protocol is executable BPMN. Agent Card discovery belongs to the protocol process, not a separate card process.
Stock inbound Connectors expose its discovery and task webhooks. Stock outbound HTTP Connectors call the authenticated engine API.
Camunda process instances and variables hold task state, messages, and artifacts.

The `a2a-rpc` process has independent webhook starts: `CardRequested` for discovery and `RpcReceived` for task requests.
Their contexts remain `a2a-card` and `a2a`. The discovery endpoint uses the custom card template.

The client uses AI Agent Task template `io.camunda.connectors.agenticai.aiagent.v1`, version 8, on service task `ClientAgent`.
It drives `ClientTools`, a parallel multi-instance ad-hoc subprocess, through an explicit tool-feedback loop.
This is the 8.9-compatible Task variant, not the newer AI Agent Sub-process connector.

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

The ad-hoc subprocess executes `clientAgent.toolCalls` in parallel and returns each result's `id`, `name`, and `content` to the next agent invocation.
The bundled `SendA2AMessage` tool has no model-supplied claim parameter: it adds a structured data part only from the
`AskClientForInput` form result. Follow-ups also reuse the task and context IDs returned by the first send instead
of accepting IDs from the model. `GetA2ATask` likewise polls the ID returned by that send. Values in the initial
free-text request or model output cannot satisfy this client confirmation step.
The business agent and reconciliation tool are separate from the protocol. The model can request the tool, but cannot supply its financial arguments.
The tool uses only deterministically validated client fields from the current message.

The protocol also supports task listing and cancellation. Business-process adaptation requires the documented task contract,
including the interrupting `a2a-cancel` hook correlated by `task.id`. See the [extended setup and task-contract guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md).

## Prerequisites

The minimum release line is **8.9 for both engine and Connectors**. Earlier confirmed-input checks used engine 8.9.26,
stock Connectors 8.9.17, and Elasticsearch 8.19.23. Those checks do not establish this revised client-agent flow,
Camunda-provided model execution, or support for every 8.9 patch and later version.

You need an authenticated engine, stock Connectors, trusted HTTPS endpoints, and a reachable OpenAI-compatible language model.
Keep local validation overrides separate from the public secret defaults below.

## Configure secrets and endpoints

Use your deployment's secret provider. Never put credentials or keys in BPMN files.

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
provider.openaiCompatible.endpoint={{secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT}}
provider.openaiCompatible.authentication.apiKey={{secrets.CAMUNDA_PROVIDED_LLM_API_KEY}}
provider.openaiCompatible.model.model={{secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL}}
```

AI Agent Task version 8 uses the `openaiCompatible` provider and endpoint setting. It does not use the tutorial's newer
`openai` Responses API and custom-backend fields. These secret references do not establish compatibility with a particular
Camunda SaaS provider; verify the endpoint and model through your authorized environment.

Both A2A URLs must resolve from external clients and the Connectors runtime. Use matching certificate names and configure trusted issuers.
Do not disable certificate checks. Restart or recreate Connectors after changing environment-supplied secrets.

The demonstrated same-runtime client/server flow requires `CAMUNDA_CLIENT_EXECUTION_THREADS=4`.
The recorded profile also sets `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`.
The Self-Managed low-latency profile requires explicit exporter settings and has resource-cost tradeoffs.
Follow the [runtime setup guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md) before deployment. Import does not configure runtime settings.

## Deploy and run

For this revised import, start with a fresh Modeler project when possible. Importing or renaming resources
does not remove the earlier standalone `a2a-card.bpmn`; do not deploy it alongside
`profiles/basic/02-a2a-server.bpmn`, which now contains discovery.

1. Import the 11 repository resources and the pinned server AI Agent template. Confirm that each BPMN template assignment resolves to the stated version, including catalog AI Agent Task v8.
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
