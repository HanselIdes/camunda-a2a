# A2A BPMN client and agent example

Ask a client AI agent to delegate through Agent2Agent (A2A) 1.0 to a server-side AI agent, then review the synthetic result.

This early-access community prototype uses stock Camunda Connectors, not native Camunda A2A support or a custom HTTP server.
It is unmaintained, intended for non-production use, and subject to the [project license](https://github.com/HanselIdes/camunda-a2a/blob/main/LICENSE.md).
Camunda does not support or certify it.

## What is in this blueprint?

| File                                           | Modeler name or role                     | Purpose                                                                                                 |
| ---------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `demo/01-client-agent.bpmn`                    | 01 Client Agent - Ask the Server         | Run a client AI agent that selects A2A tools and requests human input.                                  |
| `profiles/basic/02-a2a-server.bpmn`            | 02 A2A Server - Protocol and Discovery   | Expose discovery and task webhooks, manage task state, and handle follow-up, cancellation, and queries. |
| `demo/03-server-agent-card-dispute.bpmn`       | 03 Server Agent - Synthetic Card Dispute | Run the server-side AI agent and its deterministic reconciliation tool.                                 |
| `demo/04-client-agent-ask.form`                | Client request form                      | Collect the initial free-text request.                                                                  |
| `demo/05-client-agent-confirm.form`            | Client confirmation form                 | Collect explicit confirmation of synthetic financial inputs.                                            |
| `demo/06-client-agent-result.form`             | Client result form                       | Display the result and arithmetic evidence for review.                                                  |
| `demo/07-server-request-validation.dmn`        | 07 Server - Validate A2A Request         | Validate protocol requests.                                                                             |
| `templates/08-server-a2a-rpc-endpoint.json`    | Server - A2A RPC Endpoint                | Configure the authenticated task webhook.                                                               |
| `templates/09-server-agent-card-endpoint.json` | Server - Agent Card Endpoint             | Configure the discovery webhook.                                                                        |
| `templates/10-server-http-json-v13.json`       | HTTP JSON Connector, version 13          | Pinned stock outbound HTTP template.                                                                    |
| `templates/11-client-a2a.json`                 | Client - A2A 1.0                         | Fetch the Agent Card, send messages, and retrieve tasks using stock HTTP Connectors.                    |
| `demo/01-client-agent.integration.test.json`   | Web Modeler client integration scenario  | Exercise the live client journey; requires deployed server processes, Connectors, and a model.          |
| `profiles/basic/02-a2a-server.test.json`       | Web Modeler protocol scenarios           | Exercise selected protocol paths without a live webhook.                                                |
| `demo/03-server-agent-card-dispute.test.json`  | Web Modeler reconciliation scenarios     | Exercise the deterministic tool without a language model.                                               |
| `templates/12-client-agent-feedback.json`      | Client AI Agent - Feedback               | Stock Sub-process v2 template with an expression-capable model-call ceiling.                            |
| `demo/README.md`                               | Project instructions                     | Explain this imported project and how to run it.                                                        |

The numeric prefixes order the project by role: client agent, server protocol, server agent, forms, validation, then templates.
Runtime process IDs remain `a2a-rpc`, `a2a-card-dispute`, and `a2a-client`.

The 16 repository resources plus the pinned [AI Agent Job Worker version 5 template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json)
form the 17-resource import list. The server AI template remains an external dependency. Before import, confirm that the
target Modeler resolves this exact ID and version; do not substitute another version. An “already available”
notice alone does not prove a version match.

## How A2A works in Camunda

The protocol is executable BPMN. Agent Card discovery belongs to the protocol process, not a separate card process.
Stock inbound Connectors expose its discovery and task webhooks. Stock outbound HTTP Connectors call the authenticated engine API.
Camunda process instances and variables hold task state, messages, and artifacts.

The `a2a-rpc` process has independent webhook starts: `CardRequested` for discovery and `RpcReceived` for task requests.
Their contexts remain `a2a-card` and `a2a`. The discovery endpoint uses the custom card template.

The client uses `dev.hansel.a2a.client-agent.v1`, version 1, on ad-hoc subprocess `ClientAgent`.
It is a blueprint-specific template authored for the stock Sub-process v2 connector.
Its model-call limit accepts FEEL; the upstream static number field otherwise displays a dynamic ceiling as blank.
The runtime remains stock `io.camunda.agenticai:aiagent:subprocess:2`.
Discovery runs explicitly before this host, not as a selectable AI tool.
The host exposes three local script tools, a human-input tool, and an expanded remote-agent subprocess.
The stock connector owns tool activation and the internal model feedback loop.

| Client tool             | Role                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `ReadIntakeGuidance`    | Read the local synthetic-demo checklist; this is not bank policy.                                                                          |
| `CheckConfirmedDetails` | Check whether the human form supplied confirmation, without reconciling amounts.                                                           |
| `DraftReviewNote`       | Format an unsent draft for human review; perform no financial action.                                                                      |
| `SendA2AMessage`        | Run nested `SendRemoteMessage`, wait two seconds, then use `GetA2ATask` to retrieve task state. Repeat polling while submitted or working. |
| `AskClientForInput`     | Present a Tasklist user task for server clarification and confirmed synthetic inputs.                                                      |

The surrounding process fixes discovery and feedback routing. The language model selects tools inside the host:

1. `DiscoverAgentCard` fetches the configured discovery URL before entering `ClientAgent`.
2. The client can read intake guidance, check confirmation, and delegate through `SendA2AMessage`.
3. The nested flow sends an authenticated message, then polls the response-derived task ID at two-second intervals.
4. It returns the actual JSON-RPC response on an input-required, terminal, or error outcome; polling has no fixed iteration counter.
5. If confirmation is needed, `AskClientForInput` collects human-confirmed fields. The agent can follow up on the same active task and context.
6. The client can draft a review note, then presents its response in `ReviewClientResult`.
7. `ClientSatisfied` ends the conversation for “yes”; otherwise `PrepareClientFollowUp` routes feedback back through `ClientJoin` into the host.

Every root tool returns a meaningful `toolCallResult`. During execution the connector maintains
`agentContext`; the completed response maps from the connector's local `agent` variable to `clientAgent`,
including its conversation context for result preparation. Each feedback turn receives eight additional
model calls; the ceiling is the retained context's cumulative call count plus eight.
The 8.10 conversation stores each tool result as structured content blocks; the client reads the
`object` block's `content` for confirmation, task identity, and final task-state review.
The bundled `SendA2AMessage` tool has no model-supplied claim parameter: it adds a structured data part only from the
`AskClientForInput` form result. Follow-ups reuse the task and context IDs returned by the previous remote response instead
of accepting IDs from the model. After a terminal task, a new task retains only the server-returned context ID.
`GetA2ATask` likewise polls the ID returned by the server. Values in the initial
free-text request or model output cannot satisfy this client confirmation step.
The remote tool result contains the actual JSON-RPC `response` and the last successfully observed
`task`. A polling error remains visible in `response.error` without losing the accepted task's identity.
The next invocation continues that task rather than silently creating a duplicate.
The business agent and reconciliation tool are separate from the protocol. The model can request the tool, but cannot supply its financial arguments.
The tool uses only deterministically validated client fields from the current message.

The protocol also supports task listing and cancellation. Business-process adaptation requires the documented task contract,
including the interrupting `a2a-cancel` hook correlated by `task.id`. See the [extended setup and task-contract guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md).

## Prerequisites

The complete client/server demo requires **8.10 for both engine and Connectors**:
the client Sub-process template has engine constraint `^8.10`. Source `6a0247a` passed the revised
live JSON scenario on engine 8.10.2, stock Connectors 8.10.0 and Elasticsearch 8.19.23.
It used local Ollama, not Camunda-provided model access. The official CPT 8.10.4 runner executed the
scenario, not Web Modeler's browser UI. The six server/tool JSON segments and deterministic
client feedback/context test also passed. The live scenario rejected one result, created a new
completed task in the same server context, then accepted it. Model-call ceilings were 8 then 14;
cumulative calls increased from 6 to 8. The full default Maven suite passed 197 tests.
See `prototype-refinement.json` in the [verification records](https://github.com/HanselIdes/camunda-a2a/tree/main/experiment-3/verification)
for exact command attribution, prior failures and exclusions.
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

| Package / runtime                                                                                                                                                                              | What you can and cannot do                                                                                                                                                        | Evidence                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Current client / engine 8.10.2 and Connectors 8.10.0                                                                                                                                           | Client host, confirmation, nested send/poll, same-task follow-up and live user-feedback re-entry passed.                                                                          | Source `6a0247a`, official CPT 8.10.4 JSON runner with local Ollama; new task in the same context and fresh per-turn model allowance verified.                                                                           |
| Current package / 8.9                                                                                                                                                                          | Cannot deploy and execute the client or complete demo as supplied. Custom templates target 8.9, but their current 8.9 runtime behavior is unverified.                             | Selected AI host requires `^8.10`; a custom template's `^8.9` constraint is not execution evidence.                                                                                                                      |
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

The custom A2A templates are version 3 and target `^8.9`. Their defaults use legacy Connector-store
references such as `{{secrets.A2A_API_KEY}}`; runtime verification for that 8.9 target remains pending.
The supplied BPMN retains native 8.10 references instead. Reapplying a template can restore its legacy
default: keep or restore the native references below when running this complete 8.10 demo.

**Caller migration:** send `X-Api-Key` instead of `X-A2A-Api-Key`; the secret name remains
`A2A_API_KEY`. The current card advertises this header and accepts no old-header fallback.
Stock Connectors 8.10.2 masks `x-api-key`, but logs the old custom header before authentication.
Do not send credentials in the old header. Immutable older packages retain their own contract.

Configure these names in the **8.10 cluster's default secret store**. Never put credentials or keys
in BPMN files. Connector-only `SECRET_*` environment variables are not a substitute for this store.

| Connector secret                     | Value                                                                               |
| ------------------------------------ | ----------------------------------------------------------------------------------- |
| `ENGINE_URL`                         | Engine REST base URL without `/v2`, reachable from Connectors.                      |
| `ENGINE_USERNAME`, `ENGINE_PASSWORD` | Authorized engine API credentials.                                                  |
| `A2A_API_KEY`                        | Shared task-access key for clients in one trust boundary.                           |
| `A2A_AGENT_PROCESS`                  | `a2a-card-dispute`.                                                                 |
| `A2A_RPC_URL`                        | Complete HTTPS task webhook URL, including any cluster prefix and `/inbound/a2a`.   |
| `A2A_AGENT_CARD_URL`                 | Complete HTTPS discovery URL, including any cluster prefix and `/inbound/a2a-card`. |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT`  | OpenAI-compatible base URL, including `/v1`.                                        |
| `CAMUNDA_PROVIDED_LLM_API_KEY`       | Your model-provider credential.                                                     |
| `CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL` | Model identifier available from that provider.                                      |

The client references the Camunda-provided LLM secret names through these connector inputs:

```text
Input provider.openai.backend.custom.endpoint: =camunda.secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT
Input provider.openai.backend.custom.authentication.apiKey: =camunda.secrets.CAMUNDA_PROVIDED_LLM_API_KEY
Input provider.openai.model.model: =camunda.secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL
```

The client selects provider `openai`, API `completions`, custom backend and API-key authentication.
The server's pinned v5 template retains its `openaiCompatible` fields. These secret references do not establish compatibility with a particular
Camunda SaaS provider; verify the endpoint and model through your authorized environment.

Both A2A URLs must resolve from external clients and the Connectors runtime. Use matching certificate names and configure trusted issuers.
Do not disable certificate checks. Each whole-value input uses FEEL `=camunda.secrets.NAME`.
Inside an existing FEEL context, use an unquoted reference, for example
`={"X-Api-Key": camunda.secrets.A2A_API_KEY}`; do not quote it as text.
URL composition uses `=camunda.secrets.ENGINE_URL + "/v2/..."`.
The engine persists references rather than credentials and injects resolved values for jobs;
Connectors also resolves references when binding inbound credentials. This does **not** apply to every
expression: webhook response callbacks use local FEEL and cannot resolve cluster secret references.
Select **Agent Card requested** in `02 A2A Server`, then fill its required **Public RPC URL** field
with the complete HTTPS RPC webhook URL. It must **exactly match** the client's `A2A_RPC_URL` secret,
including any cluster prefix and path. This endpoint URL is public in the Agent Card, not a credential.
The template's field is empty by default. The supplied BPMN contains
`https://camunda-a2a-demo.example.com/inbound/a2a`, an explicitly **nonfunctional prototype placeholder**.
Replace it before deployment. An HTTPS-shaped placeholder passes format validation but does not provide a working endpoint.
Discovery returns an explicit setup error if the field is missing or not HTTPS.
The [runtime setup guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md#cluster-secret-store)
explains store setup and permissions. Missing secrets or resolution permissions prevent execution.
Use Modeler **5.52.0 or later** for native-secret linting; 5.51.1 misidentifies `camunda.secrets` as the older deprecated syntax.

The demonstrated same-runtime client/server flow requires `CAMUNDA_CLIENT_EXECUTION_THREADS=4`.
The recorded profile also sets `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`.
The Self-Managed low-latency profile requires explicit exporter settings and has resource-cost tradeoffs.
Follow the [runtime setup guide](https://github.com/HanselIdes/camunda-a2a/blob/main/experiment-3/blueprint/README.md) before deployment. Import does not configure runtime settings.

## Deploy and run

For this revised import, start with a fresh Modeler project when possible. Importing or renaming resources
does not remove the earlier standalone `a2a-card.bpmn`; do not deploy it alongside
`profiles/basic/02-a2a-server.bpmn`, which now contains discovery.

1. Import the 16 repository resources, including local `12-client-agent-feedback.json`, and the pinned upstream server AI Agent Job Worker v5 template. Confirm each exact template version.
2. Configure secrets and the runtime requirements above.
3. Deploy the selected BPMN, DMN, and form resources together.
4. Wait for healthy `CardRequested` and `RpcReceived` inbound Connectors in process `a2a-rpc`.
5. Confirm that the discovery URL returns an Agent Card and unauthenticated task requests return HTTP 401, not 404.
6. Start **01 Client Agent - Ask the Server** (`a2a-client`) using its start form.
7. Enter the synthetic request below.

> Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool.

Free text is context, not confirmation, even when it contains every value. If the server requests confirmation, open the client agent's
Tasklist user task using `05-client-agent-confirm.form` and enter the requested values:

| Confirmation field          | Value                   |
| --------------------------- | ----------------------- |
| Merchant                    | `Northwind Electronics` |
| Currency                    | `USD`                   |
| First charge amount         | `49.95`                 |
| Second charge amount        | `49.95`                 |
| Expected amount             | `49.95`                 |
| Synthetic-only confirmation | Checked.                |

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

Select “Yes, finish” in the review task to finish the client process, or “No, send a follow-up” to continue with your feedback.
This example performs no refund, financial action, real dispute decision,
fraud determination, or financial integration.

### Web Modeler test scenarios

The three `.test.json` files use the Web Modeler 8.10 test-case schema. Import them with their matching BPMN resources.
Protocol scenarios cover selected parsing, validation, and response mappings; reconciliation scenarios exercise the deterministic tool.
They do not establish complete process coverage or A2A conformance.
The client integration scenario calls real Connectors and a language model. It requires the complete deployed setup and configured secrets.
It checks client routing, not response wording or reconciliation correctness. Import and static reference checks alone do not prove these scenarios execute successfully.

## Use an external A2A client

Read `A2A_AGENT_CARD_URL`, then send A2A 1.0 JSON-RPC requests to `A2A_RPC_URL` with the `X-Api-Key` header.
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
