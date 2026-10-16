# Experiment 2: two agents, one diagram

One process instance holds two AI agents that talk Agent-to-Agent (A2A) 1.0 over real HTTP:

- **Client agent** (main flow): a chat agent with a few tools. One tool, "Ask remote agent", delegates work over A2A.
- **Server agent** (event sub-processes): "GET Agent Card" serves the agent's card, "A2A task" runs one A2A task.
  Both start non-interrupting, and only the client's A2A calls trigger them.

The diagram is [bpmn/a2a-two-agents.bpmn](bpmn/a2a-two-agents.bpmn).

## How the agents find each other

1. "Request received" creates `a2aAgentId`, the ID the server agent in this instance is reached by.
2. "Fetch remote agent card" reads `<connectors>/inbound/a2a-server-card?agent=<id>`. The A2A 1.0 Server card
   connector takes the `agent` query parameter as correlation key, so the request fires "GET Agent Card" in this
   instance. The card's JSON-RPC URL carries the same `?agent=`.
3. "Ask remote agent" sends `SendMessage` to that URL. Without a `taskId` it is a new task and fires "A2A task".
   The response is the Task in `TASK_STATE_SUBMITTED`; the answer comes later as a push notification.
4. When the server agent needs more input, it pushes `TASK_STATE_INPUT_REQUIRED` and waits in "A2A update received".
   The client answers with `SendMessage` carrying the `taskId`; it reaches that waiting event and nothing else.
5. Once a task is final its event sub-process has ended, so nothing waits for its `taskId`. The client must start a
   new task. The conversation ends when the person is satisfied, and the server agent ends with it.

Each A2A task's variables (`taskId`, `contextId`, `messageText`, `pushNotification`, `taskState`) are local to its
event sub-process run, so overlapping tasks do not overwrite each other.

## Element templates

Six A2A 1.0 templates in [element-templates/](element-templates), written with the Camunda connector template
generator DSL ([generator/](element-templates/generator)). They run on out-of-the-box task types, the HTTP JSON
connector and the HTTP webhook, so nothing custom runs in the cluster. Regenerate with
`mvn -q compile exec:java` in `element-templates/generator`.

| Template | On | Does |
|----------|----|------|
| A2A 1.0 Client | service task | fetchAgentCard (GET) or sendMessage (JSON-RPC `SendMessage`, `A2A-Version: 1.0`, push config) |
| A2A 1.0 Client Webhook | intermediate catch event | receives the push (`StreamResponse`), correlates on the task ID, checks `X-A2A-Notification-Token` |
| A2A 1.0 Server: Agent Card | message start event | serves the card on GET, correlates on `?agent=` |
| A2A 1.0 Server: SendMessage (new task) | message start event | answers `TASK_STATE_SUBMITTED`, correlates on `?agent=` |
| A2A 1.0 Server: SendMessage (follow-up) | intermediate catch event | same endpoint, correlates on `taskId`, the answer becomes `toolCallResult` |
| A2A 1.0 Server: push task update | message throw event | POSTs the task as `StreamResponse` with the notification token |

The out-of-the-box A2A Client connector (connectors 8.10.0) bundles a2a-java SDK 0.3.3 and speaks A2A 0.3, so these
templates are a separate 1.0 implementation that keeps its field layout.

Two deliberate deviations from the A2A 1.0 spec, both forced by the HTTP webhook connector:

- The push is sent as `application/json`, not `application/a2a+json`: the webhook only parses `application/json`
  into `request.body`, and the client webhook needs the parsed task to correlate.
- A `SendMessage` with a `taskId` whose task is already final finds nothing waiting and is not rejected with an
  error; the client must start a new task (the client agent's prompt says so).

The server agent's tools are the push event, "Get list of all Tech Stuff" and "Convert temperature", a FEEL script
task that converts between celsius, fahrenheit and kelvin.

## Secrets

| Secret | Used for |
|--------|----------|
| `A2A_CONNECTORS_URL` | base URL of the connectors runtime as the runtime itself sees it, for example `http://localhost:8086` on c8run |
| `A2A_PUSH_TOKEN` | the push notification token the client sends and its webhook checks |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT`, `_API_KEY`, `_DEFAULT_MODEL` | the OpenAI-compatible model both agents use |

The diagram uses the `{{secrets.X}}` format, which the connectors runtime resolves from its `SECRET_X` environment
variables. On c8run 8.10.2, `camunda.secrets.X` stays unresolved text inside connector jobs (checked with a one-task
HTTP probe as well as the AI agent), and the 8.10 linter's preference for it is switched off in
[.bpmnlintrc](.bpmnlintrc).

Keep the values in c8run's local secret store, which persists across c8run versions:

```bash
~/Library/Caches/c8run/c8run-8.10.2/c8run-8.10.2/c8run secrets set CAMUNDA_PROVIDED_LLM_API_ENDPOINT CAMUNDA_PROVIDED_LLM_API_KEY CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL
```

[scripts/c8run-demo.sh](scripts/c8run-demo.sh) exports every secret of that store as `SECRET_<name>` (without
surrounding quotes) before it starts c8run, then deploys the diagram and its forms and waits for the webhooks:

```bash
scripts/c8run-demo.sh            # start or restart c8run, deploy
scripts/c8run-demo.sh deploy     # deploy only
```

Then start "A2A two agents" from Tasklist (`http://localhost:8080/tasklist/processes`, login demo / demo) and follow
the instance in Operate.

## Tests

```bash
cd tests && mvn verify
```

1. **Process tests** (`TwoAgentsProcessTest`): every path, connectors off. The test completes the HTTP jobs and AI
   agent jobs and correlates the messages the inbound templates would. 100% element and flow coverage.
2. **Template integration tests** (`TemplatesIntegrationTest`): each template on its own, on the real connectors
   runtime, against harness processes in `tests/src/test/resources/harness` and a recording HTTP server.
3. **End-to-end** (`TwoAgentsE2ETest`): an ambiguous request, a clarification, then completion, with real A2A over
   HTTP and a stub model that plays both agents.

Status: all three tiers pass with `mvn verify` (30 tests: 3 process, 26 template integration, 1 end-to-end), with 100% element and flow coverage of the process. The same route also ran end to end on c8run with the provided LLM: an ambiguous request, the server's clarifying question answered in "User feedback", the conversion tool, and a completed instance.
