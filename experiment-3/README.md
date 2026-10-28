# Experiment 3: two diagrams, and a server that passes the TCK

This is the **nonshipping historical experiment**, not the release blueprint. Use the
[blueprint guide](blueprint/README.md) for installation, exact-source evidence and remaining gates.
Results below describe the experiment diagrams, not the packaged profiles. In particular, the original
protocol's lenient missing/empty-version behavior does not satisfy `VER-SERVER-003`.

Experiment 2 put two AI agents in one diagram that talk Agent-to-Agent (A2A) 1.0 over real HTTP. That server could not
pass the [a2a-tck](https://github.com/a2aproject/a2a-tck), and its README listed seven steps to get there. This
experiment takes those steps, and then takes the protocol out of the diagram a customer would model.

| Diagram                                                              | What it is                                                                                                                                                                                                 |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [bpmn/a2a-agent.bpmn](bpmn/a2a-agent.bpmn)                           | What a customer models: the Agent Card and the A2A task. The AI agent with its two tools, "Update A2A task" after each turn, and a follow-up loop while the agent needs input. 14 flow nodes.              |
| [bpmn/a2a-echo.bpmn](bpmn/a2a-echo.bpmn)                             | A deterministic task-contract example. Echoes the submitted text and completes the task without a model or a custom worker.                                                                                |
| [bpmn/a2a-protocol.bpmn](bpmn/a2a-protocol.bpmn)                     | The A2A 1.0 JSON-RPC protocol, deployed unchanged next to the agent. Generated, not meant to be edited.                                                                                                    |
| [bpmn/a2a-client.bpmn](bpmn/a2a-client.bpmn)                         | The client agent of experiment 2. It reads the remote agent's card, delegates work with the "A2A 1.0 Client" template and receives the answers as push notifications through the "A2A 1.0 Client Webhook". |
| [tck/fixture/a2a-tck-fixture.bpmn](tck/fixture/a2a-tck-fixture.bpmn) | A scripted stand-in for the agent, with the same contract. Deployed only for the TCK runs.                                                                                                                 |

The agent diagram and the protocol pass the TCK at MUST level, with the same results as the first version of this
experiment (see Results).

## Why the server is split

The first version of this experiment passed the TCK with one server diagram of seven pools and 157 flow nodes. About 140
of them were protocol plumbing or TCK test logic, and they sat next to the agent in the diagram a customer would model:

1. **TCK scenarios in the task process.** "Classify message", "Apply scenario" and "Scripted or agent?" existed only so
   the TCK's test messages behave as it expects.
2. **Reads went through messages.** GetTask, terminal-state errors, the context check and push config changes were
   messages to the running task instance, answered by event sub-processes and a reply message back to the endpoint.
3. **Finished tasks stayed alive** for an hour, waiting for GetTask, CancelTask or an expiry timer, only so they could
   answer.

The split moves all three out. The endpoint answers every method from engine state, the task process ends when the task
does, and the TCK scenarios live in a fixture that only the TCK runs deploy.

The friction is that engine state is read through the search API, which lags writes. A spike against this stack
measured the lag from a write to its first visible read:

| Write                                          | Median        | Max (20 runs) |
| ---------------------------------------------- | ------------- | ------------- |
| Process instance created, its variable visible | 854 ms        | 1108 ms       |
| Variable updated                               | 717 ms        | 1172 ms       |
| Cluster variable created, updated or deleted   | 783 to 856 ms | 1159 ms       |

So every request that changes state waits until its own write is visible before it answers (`a2a-await` reads every
250 ms). A blocking SendMessage also waits there until the task reaches a settled state, which replaces the reply
message of the first version. The cost is about one second more per state-changing request and a read loop instead of a
message, which is visible as extra load on the engine.

## How the pieces fit

```
client --A2A JSON-RPC--> nginx --> HTTP Webhook connector --> a2a-rpc (one run per request)
  validate (DMN) -> route
    new task   start the agent process (secret A2A_AGENT_PROCESS) with task and req, wait until visible or settled
    GetTask    find the instance by tag, read its task variable
    CancelTask write the canceled task, cancel the instance, wait until visible
    follow-up  correlate message a2a-send, wait until visible or settled
    push       one cluster variable per config, wait until visible
agent process (a2a-agent, or a2a-tck-fixture in TCK runs)
  agent turn -> Update A2A task (a2a-task-update: apply the outcome, start push delivery) -> input required? wait for a2a-send
```

The contract between the protocol and an agent process:

| When            | What                                                                                                                                          |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| started         | variables `task` (the A2A Task plus a revision `rev`) and `req` (the message and request options); tags `a2a`, `task-<id>`, `ctx-<contextId>` |
| after each turn | calls `a2a-task-update` with `task` and an outcome: `{state, text, artifacts}`, or `{agent: <AI Agent result>}`                               |
| needs input     | waits for message `a2a-send` with correlation key `=task.id`; its output mappings add the client's message to the history                     |

### Candidate validation profiles (not a release)

The original quickstart remains an experiment, not an authenticated release installation.
The files in `blueprint/profiles/` are **nonshipping validation candidates**. They are not a completed Marketplace
blueprint. No Marketplace import, publication, or SaaS runtime compatibility is established by these files.

These candidates are **non-production only**, subject to the [repository license and licensing limitations](../README.md#license-and-support).
Licensing authority confirmation and Marketplace eligibility remain publication gates.

Both profiles protect the JSON-RPC webhook with the `A2A_API_KEY` connector secret, read from the
`X-Api-Key` header. Engine REST calls use authenticated access. Select exactly one profile: they share process IDs.
They require the deterministic example and `dmn/a2a-validate.dmn` alongside the selected protocol.

| Profile | Engine connector secrets                                                                                   |
| ------- | ---------------------------------------------------------------------------------------------------------- |
| `basic` | `ENGINE_URL`, `ENGINE_USERNAME`, `ENGINE_PASSWORD`                                                         |
| `oauth` | `ENGINE_URL`, `ENGINE_OAUTH_TOKEN_ENDPOINT`, `ENGINE_CLIENT_ID`, `ENGINE_CLIENT_SECRET`, `ENGINE_AUDIENCE` |

`ENGINE_URL` is the REST base URL without `/v2`; `A2A_AGENT_PROCESS=a2a-echo` selects the deterministic process.
Push is disabled in these profiles. Inline push requests are rejected before business work starts. These profiles
do not call the cluster-variable or expression-evaluation APIs and do not include conformance-specific direct-message
behavior.

Existing-task operations allow a three-second visibility window before reporting a missing task. The protocol retries
process/tag searches every 250 ms and uses the remaining window to read the task variable. This handles a task returned
by `SendMessage` before its process is visible in search; unknown and cross-agent task IDs still expire with
`TASK_NOT_FOUND`. It does not extend task retention or turn engine API failures into missing-task responses.

The complete current client/server demo requires **8.10 for both engine and Connectors**, using the
AI Agent Sub-process connector on the client. Source-pinned 8.9.26 / 8.9.17 evidence for the
protocol and server, including the [earlier client Task variant](verification/69e77df/README.md),
does not verify the current client's or server's revised result mappings on 8.9.
See the [current setup](blueprint/README.md).
Current blueprint resources use native `camunda.secrets` FEEL references from an 8.10 cluster secret
store, not Connector-only environment secrets. Configure the public RPC URL in the Card template
to exactly match the client's existing `A2A_RPC_URL` secret; webhook response callbacks use local FEEL.
See [cluster secret store setup](blueprint/README.md#cluster-secret-store).
The selected Sub-process v2 template requires 8.10; this is not a generic A2A or AI-agent limit.
For what cannot run as supplied on 8.9 and the immutable, verified Task-based alternative, see the
[compatibility table](blueprint/README.md#why-the-current-client-requires-810).
The [earlier input-only repair failure](verification/3634072-89/README.md) remains preserved.
Engine 8.8 is unsupported. Changed-form UI and SaaS runtime are unverified.
The following results are historical, source-pinned evidence, not current candidate acceptance.

A fresh, isolated historical Self-Managed check of the exact Basic profile passed on **engine 8.8.21, stock Connectors 8.9.0,
and Elasticsearch 8.17.0**, with engine authentication and platform authorizations enabled. Missing and invalid task API
keys returned 401; valid keys returned the exact completed echo and completed-task polling. This check used loopback HTTP,
not HTTPS, and required `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`. It is mixed-version feasibility evidence,
not matched-8.8 compatibility, conformance, or a production deployment claim.

The OAuth profile has not passed a real-runtime task check. A separate SaaS attempt on engine 8.8.44 and Connectors 8.8.24
was blocked: authenticated webhook registration reported an unavailable secret, and HTTP requests returned 403, including
with a valid key and a new registration. SaaS runtime support remains **unverified**. Deployment and Modeler import are
separate from runtime support.

The [candidate setup guide](blueprint/README.md) provides separate direct discovery, authenticated BPMN client,
AI-agent, form and template resources. On the mixed-version configuration above, these passed direct certificate-verified
HTTPS, exact synthetic charge-reconciliation evidence, numeric-leading same-task follow-up, and the complete BPMN
client-to-server-agent result/review flow with the documented local Qwen model. Stock Connectors required four job
execution threads for the nested client/server calls. This is not a real financial service or production-use claim.

The [frozen-source engineering record](verification/d4e6273/summary.json) covers terminal-state races,
three scoped TCK MUST-gate repeats, native failures/recovery, independent clients and two-agent reliability.
The [timed AI-agent execution report](verification/597b152/adoption.md) records 139 seconds by a review
session with prior repository knowledge, not a fresh human adopter or usability study.
Neither establishes full A2A conformance or support for unverified version combinations.
Desktop deployment and exact external calls have [updated evidence](verification/a994f22/README.md);
the [Hub/Tasklist report](verification/a323e19/README.md) records a separately successful actual
ask/answer/result form journey while retaining earlier failures. The
[prototype evidence matrix](verification/32f8d4e/prototype-evidence.md) records relevant-runtime gaps and
partial Desktop checks. Fresh-adopter timing and human usability are not prototype criteria;
actual Marketplace-to-Modeler import and external legal/eligibility approval remain deferred release gates.
Do not use the archived experimental card or client as companions to these candidate profiles.

For contributors, `bpmn/a2a-protocol.bpmn` is the input to the profile builder. The builder preserves surviving diagram
layout; it does not regenerate the source diagram. Regenerate a selected profile with
`python3 tools/build_core.py --authentication basic --output blueprint/profiles/basic/a2a-protocol.bpmn`
(substitute `oauth` for the other profile). Run `python3 tools/build_core.py --check` to check both committed outputs
without modifying files. Adopters must not need to run this generator.

### Deterministic task-contract example

Set the connector secret `A2A_AGENT_PROCESS` to `a2a-echo` to select the echo process for new tasks.
Deploy `a2a-echo.bpmn` alongside the protocol and validation decision. The existing local deployment script includes it.
The process receives `task` and `req`, produces an outcome with `state` and `text`, calls `a2a-task-update`, and maps
the updated `task` back to its own root scope. It needs no language model.

When exposing this example, configure the Agent Card's name, description, and skills to describe echoing text,
not the AI agent's tools. Selecting a different process does not automatically update the card.

`DeterministicProcessTest` checks exact returned text, history, completed-task polling, and isolation between two
requests on engine 8.10.2 with the existing HTTP test harness and Connectors disabled. This is not evidence for authenticated
deployment or an 8.8 compatibility claim.

Push notification configs are cluster variables named `a2a-push-<taskId>~<configId>`, because the TCK changes them on
completed tasks, after the task's process instance has ended.

| Template                          | On                       | Used by                                                                                |
| --------------------------------- | ------------------------ | -------------------------------------------------------------------------------------- |
| A2A 1.0 Client                    | service task             | client: fetch the card, send a message                                                 |
| A2A 1.0 Client Webhook            | intermediate catch event | client: receives the push, correlates on the task ID, keeps an early push for a minute |
| A2A 1.0 Server: Agent Card        | start event              | `a2a-card`: serves the card; the field holds name, description and skills              |
| A2A 1.0 Server: JSON-RPC endpoint | start event              | `a2a-rpc`: synchronous endpoint; the answer is the process variable `rpcResponse`      |
| A2A 1.0 Server: push task update  | service task             | `a2a-push-notify`: delivers a task to one push destination                             |

The templates are written with the Camunda connector template generator DSL in [element-templates/generator](element-templates/generator).
Regenerate them with `mvn -q compile exec:java` in that folder. They run on out-of-the-box connectors, so nothing custom
runs in the cluster. The out-of-the-box A2A Client connector speaks A2A 0.3, so these are a separate 1.0 implementation.

The server agent keeps experiment 2's tools: "Convert temperature" and "Get list of all Tech Stuff". It answers in
plain text, and an answer that starts with `NEED_INPUT:` makes the task wait in `TASK_STATE_INPUT_REQUIRED`. The agent
keeps its conversation across the follow-up turns of a task. The card skills are generated from the tools, so the card
cannot drift from them (`python3 tools/gen_card.py --check`).

## Results

[tck/RESULTS.md](tck/RESULTS.md) and [tck/RESULTS-push.md](tck/RESULTS-push.md) hold the latest runs. The raw TCK reports of the last run of each gate are in [tck/latest](tck/latest) (`push-off` is the run after a stack reset).

| Gate                      | Command                  | Result                                                                                                                                                                                                                                                                                       |
| ------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TCK, MUST level, push off | `tck/run.sh`             | 3 runs and 1 run after a stack reset: 68 tests executed, 56 MUST requirements pass and 58 are N/A, zero failures, zero incidents                                                                                                                                                             |
| TCK, MUST level, push on  | `tck/run-push.sh`        | 76 tests executed, 65 MUST requirements pass and 49 are N/A, every PUSH-* requirement passes; CORE-CAP-001 is skipped by the TCK                                                                                                                                                             |
| Tests                     | `cd tests && mvn verify` | 160 tests, zero failures; 100% of sequence flows and 100% of rules of both decisions; every element of every process except two in `a2a-rpc` (`BuildDirectMessage`, `DirectMessageReady`), whose entering flow is recorded and whose result the tests assert (`python3 scripts/coverage.py`) |

Push is off in the gated run because the TCK requires CORE-CAP-001 (the error for an unsupported capability) to pass.
The experimental client agent needs push, so its default `.env` turns it on. These historical runs do not
establish every applicable MUST: excluded and untested requirements need separate dispositions.

## Quickstart

Prerequisites: Docker, Java 21, Maven, Python 3, uv, `c8ctl`, and a model behind an OpenAI-compatible endpoint (a local
Ollama by default).

```bash
cp .env.example .env
docker compose -p camunda-a2a-3 -f blueprint/docker-compose.yml --env-file .env up -d --wait
scripts/deploy.sh
curl -s localhost:28090/.well-known/agent-card.json
```

For the client and the server together on c8run, `scripts/c8run-demo.sh` starts c8run 8.10.2, hands it the secrets,
deploys the diagrams and prints the Tasklist URL of "A2A client agent". c8run has no proxy, so the card is at
`http://localhost:8086/inbound/a2a-card`.

## Secrets

| Secret                                                            | Used for                                                                                                                |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `ENGINE_URL`                                                      | the engine REST API, as the connectors runtime sees it; the protocol reads and writes engine state through it           |
| `A2A_AGENT_PROCESS`                                               | the process the endpoint starts for a new task: `a2a-agent`, or `a2a-tck-fixture` in the TCK runs                       |
| `A2A_PUBLIC_URL`                                                  | the public base URL of the server; the card advertises `<url>/a2a`                                                      |
| `A2A_PUSH_ENABLED`                                                | `true` makes the card declare push and enables the push config methods                                                  |
| `A2A_SERVER_URL`, `A2A_AGENT_CARD_PATH`                           | the client: base URL of the server and the path of its card, for example `http://localhost:8086/inbound` and `a2a-card` |
| `A2A_CONNECTORS_URL`                                              | the client: its own connectors runtime, where the server pushes                                                         |
| `A2A_PUSH_TOKEN`                                                  | the push token the client sends and its webhook checks                                                                  |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT`, `_API_KEY`, `_DEFAULT_MODEL` | the model both agents use                                                                                               |

These archived experimental diagrams use legacy secret interpolation resolved from Connector `SECRET_X`
environment variables. This is **not** setup for the current numbered blueprint; use its
[cluster secret store instructions](blueprint/README.md#cluster-secret-store) instead.

## Tests

```bash
cd tests && mvn verify
```

| Tier                 | Tests                                                                                                                                                                            | What it proves                                                                                                                |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Process tests        | `TaskTest`, `ValidationTest`, `ListTasksTest`, `PushTest`, `EdgeCaseTest`, `AgentTest`, `DmnTest`, `CardTest`, `ConnectorProcessesTest`, `ClientProcessTest`, `CoverageGapsTest` | every path of the protocol, the agent, the fixture and the client with connectors off; the agent job is completed by the test |
| Template integration | `TemplatesIntegrationTest`, `WebhookIntegrationTest`, `PushIntegrationTest`                                                                                                      | each template and the whole server on the real connectors runtime                                                             |
| End to end           | `ClientServerE2ETest`                                                                                                                                                            | the client diagram and the agent with the protocol over real HTTP, with a stub model that plays both agents                   |

In the process tests the HTTP JSON connector is replaced by a harness that sends each request to the test engine's real
REST API and evaluates the element's own result expression there, so the protocol runs against the real search API and
its lag. `scripts/trace.py` checks that every MUST requirement of the pinned TCK maps to a test or an N/A reason.
`TemplateShapeTest` checks the generated template JSON. The stub model follows a script, so the end-to-end test does not
show how a real model follows the prompts.

## Layout

```
bpmn/        a2a-agent.bpmn and a2a-protocol.bpmn (generated), a2a-client.bpmn (drawn in Modeler)
dmn/         a2a-validate
tck/fixture/ a2a-tck-fixture.bpmn and a2a-classify.dmn (generated), deployed only by the TCK runs
element-templates/   the five A2A 1.0 templates and their generator
tools/       bpmn_gen/ (generator of the agent, protocol and fixture), gen_card.py, split/ (how the client was cut from experiment 2)
tests/       Maven module
tck/         run.sh, run-push.sh, check_results.py, allowed-not-passing.txt, pin.env, patches/, RESULTS*.md
blueprint/   docker-compose.yml, nginx proxy
scripts/     deploy.sh, c8run-demo.sh, trace.py, token-trace.py, coverage.py
```

Edit the generator or the generated diagrams, not both; rerun `python3 tools/bpmn_gen/build.py` to see the difference.
The client diagram has no generator: edit it in Modeler.

## Requirement matrix

This coverage inventory is not a conformance verdict. Most entries refer to the legacy experiment;
rows naming `CoreProtocolTest` refer to the packaged Basic profile. A named test or a historical N/A
label does not establish that a requirement passes. Client/server patch negotiation still needs client evidence
in addition to the server checks. See the blueprint guide's individual requirement dispositions and
`native-checks.json` in exact-source runtime reports.
`python3 scripts/trace.py` checks that IDs and named tests exist; `--update` regenerates the table.

<!-- trace:begin -->
| Requirement             | Element                                                                                       | Test                                                                                                                                                                                                                                                          | N/A reason              |
| ----------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| CORE-SEND-001           | a2a-rpc: PrepareNewTask, CreateTask, AwaitNewTask                                             | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| CORE-SEND-002           | a2a-rpc: CheckFollowUp (terminal state)                                                       | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend`                                                                                                                                                                                                      |                         |
| CORE-SEND-003           | a2a-validate rule 9                                                                           | `DmnTest#validatesRequests`; `ValidationTest#invalidParams`                                                                                                                                                                                                   |                         |
| CORE-STREAM-001         |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CORE-STREAM-002         |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CORE-STREAM-003         |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CORE-GET-001            | a2a-rpc: FindTask, ReadTask (a2a-await), BuildTaskView                                        | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend`; `AgentTest#taskAnswersGetTaskAndCancelWhileTheAgentIsWorking`                                                                                                                                       |                         |
| CORE-GET-002            | a2a-rpc: BuildNotFound                                                                        | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp`; `WebhookIntegrationTest#unknownTaskIsNotFoundBecauseNoInstanceCarriesItsTag`                                                                                                                         |                         |
| CORE-LIST-001           | Packaged a2a-list-collect; a2a-rpc: BuildTaskList                                             | `CoreListingTest#listsAll125ExactTasksAcrossEngineAndA2APagesWithStableTimestampTies`; `CoreListingTest#emptyListsAndCollidingContextTagsRetainExactContextFiltering`; `CoreListingTest#incompleteRootStateExpiresWithAnErrorInsteadOfAPartialSuccessfulList` |                         |
| CORE-LIST-002           | Packaged BuildTaskList (offset pageToken over complete engine collection)                     | `CoreListingTest#listsAll125ExactTasksAcrossEngineAndA2APagesWithStableTimestampTies`; `CoreListingTest#missingRepeatedAndOverlappingEngineCursorsCannotReturnTruncatedSuccess`                                                                               |                         |
| CORE-LIST-003           | Packaged BuildTaskList (status timestamp descending, task ID descending for ties)             | `CoreListingTest#listsAll125ExactTasksAcrossEngineAndA2APagesWithStableTimestampTies`                                                                                                                                                                         |                         |
| CORE-LIST-004           | Packaged BuildTaskList (empty nextPageToken on the last page)                                 | `CoreListingTest#listsAll125ExactTasksAcrossEngineAndA2APagesWithStableTimestampTies`                                                                                                                                                                         |                         |
| CORE-LIST-005           | Packaged BuildTaskList (artifacts dropped unless includeArtifacts)                            | `CoreProtocolTest#messageResponseModeCannotDiscardBusinessArtifacts`                                                                                                                                                                                          |                         |
| CORE-CANCEL-001         | Packaged RequestCancellation, AwaitCanceled; business A2ACancellation                         | `CoreProtocolTest#cancellationInterruptsBusinessWorkAndCommitsOnlyOneTerminalOutcome`                                                                                                                                                                         |                         |
| CORE-CANCEL-002         | a2a-rpc: Cancelable, BuildNotCancelable                                                       | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend`; `TaskTest#cancelInputRequiredTaskAndCancelAgainFails`                                                                                                                                               |                         |
| CORE-CANCEL-003         | a2a-rpc: BuildNotFound                                                                        | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp`                                                                                                                                                                                                       |                         |
| CORE-EXECUTION-MODE-001 | a2a-rpc: AwaitNewTask, AwaitFollowUp (until a settled state)                                  | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`; `AgentTest#sendMessageReturnsWorkingStateWhenTheAgentIsSlow`                                                                                                                                    |                         |
| CORE-EXECUTION-MODE-002 | a2a-rpc: AwaitNewTask (until the task is visible)                                             | `TaskTest#returnImmediatelyAnswersBeforeTheWorkAndTheTaskCompletesAnyway`                                                                                                                                                                                     |                         |
| CORE-ERR-001            | a2a-validate; a2a-rpc: BuildValidationError                                                   | `ValidationTest#unknownMethodAndInvalidRequest`; `ValidationTest#capabilityErrors`                                                                                                                                                                            |                         |
| CORE-ERR-002            | a2a-validate rules 8 and 10                                                                   | `ValidationTest#invalidParams`; `TaskTest#noIncidentsAfterMalformedInput`                                                                                                                                                                                     |                         |
| CORE-CAP-001            | a2a-validate rule 6                                                                           | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests`                                                                                                                                                                                                |                         |
| CORE-CAP-002            | a2a-validate rule 4                                                                           | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests`                                                                                                                                                                                                |                         |
| CORE-CAP-003            | a2a-validate rule 5                                                                           | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests`                                                                                                                                                                                                |                         |
| CORE-CAP-004            |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CORE-MULTI-001a         | a2a-rpc: PrepareNewTask                                                                       | `TaskTest#contextIdIsGeneratedEchoedAndChecked`                                                                                                                                                                                                               |                         |
| CORE-MULTI-002a         | a2a-rpc: PrepareNewTask (echoes the client contextId)                                         | `TaskTest#contextIdIsGeneratedEchoedAndChecked`                                                                                                                                                                                                               |                         |
| CORE-MULTI-003          | a2a-rpc: PrepareNewTask (uuid)                                                                | `TaskTest#taskIdsAreUnique`                                                                                                                                                                                                                                   |                         |
| CORE-MULTI-004          | a2a-rpc: FindTask, BuildNotFound                                                              | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp`                                                                                                                                                                                                       |                         |
| CORE-MULTI-005          | a2a-rpc: CorrelateFollowUp; agent: FollowUp (message a2a-send)                                | `TaskTest#inputRequiredThenFollowUpCompletes`                                                                                                                                                                                                                 |                         |
| CORE-MULTI-006          | a2a-rpc: CheckFollowUp, BuildFollowUpError                                                    | `TaskTest#contextIdIsGeneratedEchoedAndChecked`                                                                                                                                                                                                               |                         |
| CORE-HIST-002           | a2a-rpc: BuildTaskView, BuildNewTaskResponse (historyLength projection)                       | `TaskTest#historyLengthLimitsHistoryOnGetTask`                                                                                                                                                                                                                |                         |
| DM-TASK-001             | a2a-rpc: PrepareNewTask; a2a-task-update: ApplyOutcome                                        | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| DM-TASK-002             | a2a-task-update: ApplyOutcome; a2a-rpc: MarkCanceled; agent: FollowUp output mapping          | `TaskTest#cancelInputRequiredTaskAndCancelAgainFails`; `AgentTest#agentFailureFailsTheTask`                                                                                                                                                                   |                         |
| DM-MSG-001              | a2a-task-update: ApplyOutcome (agent messages)                                                | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`; `ValidationTest#directMessageResponse`                                                                                                                                                          |                         |
| DM-MSG-002              | a2a-rpc: PrepareNewTask (ROLE_USER); a2a-task-update: ApplyOutcome (ROLE_AGENT)               | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| DM-PART-001             | TCK fixture: ApplyScenario artifact parts                                                     | `TaskTest#artifactsAreAttachedByMessageIdPrefix`                                                                                                                                                                                                              |                         |
| DM-ART-001              | TCK fixture: ApplyScenario; a2a-task-update: ApplyOutcome                                     | `TaskTest#artifactsAreAttachedByMessageIdPrefix`                                                                                                                                                                                                              |                         |
| DM-STATUS-001           | a2a-task-update: ApplyOutcome (status object)                                                 | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| DM-SERIAL-001           | every FEEL response builder uses camelCase keys                                               | `TaskTest#artifactsAreAttachedByMessageIdPrefix`                                                                                                                                                                                                              |                         |
| DM-SERIAL-002           | TASK_STATE_* and ROLE_* strings                                                               | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| DM-SERIAL-003           | timestamps built as UTC strings ending in Z                                                   | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| DM-SERIAL-004           | null keys are dropped from every object                                                       | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`                                                                                                                                                                                                  |                         |
| STREAM-ORDER-001        |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-ORDER-002        |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-ORDER-003        |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-ORDER-004        |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-SUB-001          |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-SUB-002          |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-SUB-003          |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| STREAM-SUB-004          |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| PUSH-CREATE-001         | a2a-rpc: PreparePushOp, CreateConfig or ReplaceConfig (one cluster variable per config)       | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-CREATE-002         | a2a-rpc: AwaitConfig, ReadConfigs (cluster variables outlive the task process)                | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`; `PushIntegrationTest#configurationOperationsWorkThroughTheRealConnectors`                                                                                                                   |                         |
| PUSH-GET-001            | a2a-rpc: ReadConfigs, PreparePushOp                                                           | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-GET-002            | a2a-rpc: PreparePushOp (unknown config id)                                                    | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-LIST-001           | a2a-rpc: ReadConfigs, PreparePushOp                                                           | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-DEL-001            | a2a-rpc: DeleteConfig, AwaitConfig                                                            | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-DEL-002            | a2a-rpc: PreparePushOp (no write when the config is gone), ConfigGone                         | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`                                                                                                                                                                                              |                         |
| PUSH-DELIVER-001        | a2a-push-notify: DeliverNotification (Authorization header)                                   | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange`; `PushIntegrationTest#cardDeclaresPushAndDeliveryReachesTheHostWithTheConfiguredAuthentication`                                                                                        |                         |
| PUSH-DELIVER-002        | a2a-task-update: FindPushConfigs, StartPushDelivery; a2a-rpc: FindCancelPush; a2a-push-notify | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange`; `PushTest#cancelIsDeliveredToo`                                                                                                                                                       |                         |
| PUSH-DELIVER-003        | a2a-task-update: StartPushDelivery (payload {task})                                           | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange`                                                                                                                                                                                        |                         |
| CARD-DISC-001           | a2a-card: A2A 1.0 Server: Agent Card template                                                 | `CardTest#cardProcessEndsRightAway`; `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills`                                                                                                                                               |                         |
| CARD-PROTO-001          | a2a-card: supportedInterfaces from A2A_PUBLIC_URL                                             | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills`                                                                                                                                                                                    |                         |
| CARD-PROTO-002          | a2a-card: supportedInterfaces from A2A_PUBLIC_URL                                             | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills`                                                                                                                                                                                    |                         |
| CARD-STRUCT-001         | a2a-card: response expression of the card start event                                         | `TemplatesIntegrationTest#agentCardIsServedOnGetWithTheConfiguredEndpointAndCapabilities`; `CardTest#committedCardMatchesTheCardGeneratedFromTheAgentTools`                                                                                                   |                         |
| CARD-EXT-001            |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CARD-EXT-002            |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| CARD-SIGN-001           |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| CARD-SIGN-002           |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| CARD-SIGN-003           |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| CARD-SIGN-004           |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-TLS-001            |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-SERVER-002         |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-INTASK-001         |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-INTASK-002         |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-INTASK-003         |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-INTASK-004         |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-SCOPE-001          |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-SCOPE-002          |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| AUTH-SCOPE-003          |                                                                                               |                                                                                                                                                                                                                                                               | not-exercised           |
| VER-CLIENT-001          |                                                                                               |                                                                                                                                                                                                                                                               | client-side             |
| VER-SERVER-001          | Packaged ParseRequest: advertised Major.Minor matching                                        | `CoreProtocolTest#onlyAdvertisedMajorMinorIsAcceptedAndPatchDoesNotChangeTaskSemantics`                                                                                                                                                                       |                         |
| VER-SERVER-002          | a2a-validate rule 1                                                                           | `ValidationTest#unsupportedVersionIsRejected`; `DmnTest#validatesRequests`                                                                                                                                                                                    |                         |
| VER-SERVER-003          | Packaged ParseRequest: missing/empty defaults to unsupported 0.3                              | `CoreProtocolTest#onlyAdvertisedMajorMinorIsAcceptedAndPatchDoesNotChangeTaskSemantics`                                                                                                                                                                       |                         |
| VER-CLIENT-002          | Packaged ParseRequest: numeric patch ignored (server evidence only)                           | `CoreProtocolTest#onlyAdvertisedMajorMinorIsAcceptedAndPatchDoesNotChangeTaskSemantics`                                                                                                                                                                       |                         |
| BIND-EQUIV-001          |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| BIND-EQUIV-002          |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| BIND-EQUIV-003          |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| BIND-EQUIV-004          |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| BIND-FIELD-001          | a2a-card: supportedInterfaces                                                                 | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills`                                                                                                                                                                                    |                         |
| JSONRPC-FMT-001         | a2a-rpc: Parse request, response builders                                                     | `ValidationTest#unknownMethodAndInvalidRequest`; `ValidationTest#idIsEchoedAndListTasksReturnsEmptyPage`                                                                                                                                                      |                         |
| JSONRPC-FMT-002         | a2a-rpc webhook response expression                                                           | `WebhookIntegrationTest#sendMessageGetTaskAndCancelRoundTripThroughTheRealConnectors`                                                                                                                                                                         |                         |
| JSONRPC-SVC-001         | a2a-validate: PascalCase method names                                                         | `DmnTest#validatesRequests`                                                                                                                                                                                                                                   |                         |
| JSONRPC-SVC-002         | a2a-rpc: Parse request reads A2A-Version and Content-Type headers                             | `ValidationTest#unsupportedVersionIsRejected`; `ValidationTest#wrongContentTypeIsRejected`                                                                                                                                                                    |                         |
| JSONRPC-ERR-001         | a2a-rpc: error object has code, message and data only                                         | `ValidationTest#capabilityErrors`                                                                                                                                                                                                                             |                         |
| JSONRPC-ERR-002         | a2a-validate error codes                                                                      | `DmnTest#validatesRequests`                                                                                                                                                                                                                                   |                         |
| JSONRPC-ERR-003         | ErrorInfo in the data array                                                                   | `ValidationTest#capabilityErrors`; `ValidationTest#unsupportedVersionIsRejected`                                                                                                                                                                              |                         |
| JSONRPC-SSE-001         |                                                                                               |                                                                                                                                                                                                                                                               | capability-not-declared |
| JSONRPC-SSE-002         | a2a-validate and a2a-rpc error codes                                                          | `DmnTest#validatesRequests`; `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp`                                                                                                                                                                          |                         |
| GRPC-SVC-001            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-SVC-002            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-SVC-003            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-META-001           |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-ERR-001            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-ERR-002            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| GRPC-ERR-003            |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-URL-001       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-URL-002       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-SVC-001       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-SVC-002       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-QP-001        |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-ERR-001       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-ERR-002       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-STATUS-001    |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
| HTTP_JSON-SSE-001       |                                                                                               |                                                                                                                                                                                                                                                               | other-binding           |
<!-- trace:end -->

## What the connectors runtime would replace

The protocol diagram stands in for the connectors runtime. Where it needs a workaround, 8.11 would do it natively:

| Limit today                      | Stand-in here                                                                                              | In 8.11                                                        |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| No A2A inbound connector         | HTTP Webhook plus the nginx path mapping                                                                   | An A2A inbound start event serving the card and `/a2a`         |
| No hook on process state changes | The agent calls `a2a-task-update` after each turn (the one piece of plumbing left in the customer diagram) | The runtime reacts to the agent's output and state, and pushes |
| No native task state             | The `task` variable with a revision, read through the search API with a wait loop (`a2a-await`)            | The runtime reads task state directly                          |
| No input-required primitive      | A message catch event `a2a-send` and an output mapping in the agent diagram                                | A runtime feature for "the agent asks, the client answers"     |
| No store for push configs        | One cluster variable per config                                                                            | The runtime's own store                                        |

## Known limits

- The model runs against the stub only in the tests. The diagrams have not been run with a real model in this experiment.
- A blocking request waits about 20 seconds for a settled state. A slower task returns in `TASK_STATE_WORKING`, and the
  client reads the result by push or by `GetTask`.
- The protocol layer is still 112 flow nodes in five processes; it moved out of the customer's diagram but did not
  shrink much, because the endpoint now answers GetTask, CancelTask and the push config methods itself.
- Push configs are cluster variables, one per config, and nothing deletes them when a task ends.
- The handler's direct-message branch (`tck-message-response` message ids) is a TCK scenario that still sits in the
  protocol, because it answers without starting a task.
- Streaming, the extended card and authentication are not offered.
