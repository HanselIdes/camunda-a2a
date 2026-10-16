# camunda-a2a

Can BPMN plus out-of-the-box connectors implement a real A2A 1.0 server? This repository is a proof of concept
that says yes for the JSON-RPC binding at the TCK's MUST level. The server is a handful of BPMN and DMN files
running on an unchanged Camunda 8.10.2 runtime. There is no custom connector and no Java in the runtime path.
The official [a2a-tck](https://github.com/a2aproject/a2a-tck) is the acceptance test.

| Piece | How it is built |
|-------|-----------------|
| JSON-RPC endpoint | HTTP Webhook inbound connector on a start event (`a2a-rpc`), synchronous response |
| Request validation and routing | DMN decision tables (`a2a-validate`, `a2a-classify`) plus null-safe FEEL script tasks |
| One long-lived process per task | `a2a-task`, with event sub-processes for GetTask and CancelTask |
| Talking between processes | HTTP JSON connector against the engine REST API (`/v2/process-instances`, `/v2/messages/correlation`, `/v2/messages/publication`) |
| The agent | AI Agent sub-process on a local Ollama model, with three basic tools |
| Agent Card | Webhook start event (`a2a-card`), generated from the tools so it cannot drift |
| ListTasks | Tasks carry tags (`a2a`, `ctx-<contextId>`, `task-<taskId>`); the handler searches by tag, asks every task for its state in parallel (`a2a-fetch-task`), then filters, sorts and pages |
| Runtime card | `a2a-card-runtime` (`/inbound/a2a-card-runtime`) parses the skills out of the deployed `a2a-task` XML on each request and returns the same skills as the generated card (checked by an integration test) |
| Push notifications | Optional (`A2A_PUSH_ENABLED=true`): configs live in the task, delivery is a fire-and-forget process (`a2a-push-notify`) |

## How a request flows

```
client --A2A JSON-RPC--> nginx (maps /a2a and /.well-known/agent-card.json)
  --> HTTP Webhook connector --> a2a-rpc (one instance per request)
        1. Parse request      FEEL builds one `ctx` context from body and headers, null-safe
        2. Validate request   DMN `a2a-validate`: version, content type, method, params, media types
        3. Route              error | ListTasks | direct message | new task | follow-up, GetTask, CancelTask
        4. New task           HTTP JSON POST /v2/process-instances starts `a2a-task`
           Follow-up/get/cancel   call activity `a2a-correlate`: POST /v2/messages/correlation, retried on 404
        5. Await reply        event-based gateway: message `a2a-reply` (key = request id) or a 25 s timer
        6. Build response     wraps the task's `replyResult` or `replyError` in a JSON-RPC envelope
  <-- the webhook returns the `rpcResponse` process variable as the HTTP body

a2a-task (one instance per A2A task, the task is always able to answer)
   Init -> Active sub-process -> Terminal loop (1 hour)
   Active:   Classify message (DMN) -> scripted TCK scenario | AI Agent sub-process with tools
             -> publish reply (HTTP JSON, message a2a-reply) -> wait for follow-up while INPUT_REQUIRED
             event sub-processes: a2a-get (non-interrupting), a2a-cancel (interrupting)
   Terminal: answers GetTask, rejects CancelTask (-32002) and SendMessage (-32004), expires after 1 hour
```

The originating side is a process too: `a2a-client` (started from a Tasklist form) reads the Agent Card, sends
`SendMessage` with the HTTP JSON connector, polls `GetTask`, relays an `INPUT_REQUIRED` question to a person and shows
the answer. `ClientServerE2ETest` runs both processes on one cluster; see `MANUAL-VERIFICATION.md` section 7 to try it
in Tasklist on c8run and follow the token across both with `scripts/token-trace.py`.

All state lives in process variables. The task is the `task` variable of its `a2a-task` instance, so no request
reads state back from secondary storage and there is no eventual-consistency window to wait out.

## Quickstart

Prerequisites: Docker, Java 21, Maven, Python 3, `c8ctl`, and a local [Ollama](https://ollama.com) with
`qwen3-coder-30b-64k` (the model with a 64k context baked in, which the OpenAI-compatible endpoint cannot set per request).

```bash
cp .env.example .env                       # ports, public URL, model
docker compose -p camunda-a2a -f blueprint/docker-compose.yml --env-file .env up -d --wait
scripts/deploy.sh                          # deploys bpmn/ and dmn/, waits until the webhooks answer
curl -s localhost:18090/.well-known/agent-card.json
curl -s localhost:18090/a2a -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc":"2.0","id":1,"method":"SendMessage",
  "params":{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"What time is it?"}]}}}'
```

The stack is Camunda 8.10.2 with H2 as secondary storage on a named volume, the connectors bundle 8.10.0 and nginx.
nginx exists only because the TCK fetches the card from `/.well-known/agent-card.json` while the connectors
runtime mounts webhooks at `/inbound/<context>`. The card advertises `A2A_PUBLIC_URL/a2a` as its JSON-RPC interface.

Ollama notes: the agent needs 2 or more model calls per turn plus a cold load, so the first answer can take 15 to
30 seconds. `blueprint/smoke.sh` warms the model up and pins it with `keep_alive`. When the model is slow the
SendMessage call returns the task in state `TASK_STATE_WORKING` after 25 seconds and the client polls GetTask.

Step-by-step checks you can run by hand are in [MANUAL-VERIFICATION.md](MANUAL-VERIFICATION.md).

## Layout

```
demo/        Playwright script and runner for the a2a-inspector demo
bpmn/        a2a-card, a2a-rpc, a2a-task, a2a-correlate, a2a-publish-reply, a2a-fetch-task, a2a-push-notify,
             a2a-card-runtime, a2a-client (the originating process, not part of the server)
forms/       Tasklist forms of a2a-client
dmn/         a2a-validate, a2a-classify, capitals
tools/       bpmn_gen/ (generator for the files above), gen_card.py (Agent Card from the agent's tools)
tests/       Maven module: CPT process tests, DMN tests, connector integration tests, Ollama tests
scripts/     deploy.sh, trace.py, c8run-demo.sh (c8run + deploy), token-trace.py (client and server timeline)
blueprint/   docker-compose.yml, nginx proxy, smoke.sh
tck/         run.sh, check_results.py, allowed-not-passing.txt, pin.env, patches/, RESULTS.md,
             run-extra.sh (SHOULD and MAY), run-push.sh (push enabled)
```

The BPMN and DMN files are generated by `python3 tools/bpmn_gen/build.py` (connector templates are applied with
`c8ctl element-template apply`). Edit the generator or the files, not both, and rerun it to see the difference.

## Validation

| Check | Command |
|-------|---------|
| Process, DMN, agent (mocked model), card drift, real connectors | `mvn verify` |
| The agent against Ollama | `mvn -Pollama verify` |
| The pinned TCK, MUST level, JSON-RPC | `tck/run.sh` |
| BPMN lint with the committed `.bpmnlintrc` | `c8ctl bpmn lint bpmn/*.bpmn` |
| Requirement traceability | `python3 scripts/trace.py` |
| End to end with the real model from a fresh clone | `blueprint/smoke.sh` |
| Browser demo: Playwright drives the a2a-inspector UI | `demo/run-demo.sh` |
| SHOULD and MAY levels (not gated) | `tck/run-extra.sh` |
| The PUSH-* requirements with push switched on (not gated) | `tck/run-push.sh` |

How the tests are built: process tests run on Camunda Process Test (CPT) with the HTTP JSON connector replaced by a
small bridge (`Harness`) that performs the engine call the connector would make, so the handler, the task, the DMN
and the message correlation are all the real engine. Webhook integration tests run the real connectors runtime. The
agent tests complete the AI Agent job themselves and activate the tools, so tool behavior is proven without a model.

`tck/run.sh` runs the pinned TCK three times on one stack, resets the stack with `docker compose down -v`, and runs it
once more. `tck/check_results.py` judges every run and never trusts the TCK exit code, because the TCK turns setup
failures into skips. It requires zero junit failures and errors, a plausible number of executed tests, every junit skip
matched by an allowlist entry, every MUST requirement PASS on JSON-RPC unless allowlisted with one of four reasons, a
fixed list of requirements that may never be allowlisted, and zero engine incidents. Pin and results: `tck/pin.env`,
`tck/RESULTS.md`.

## Requirement matrix

Every MUST requirement of the pinned TCK, with the elements that implement it and the tests that prove it, or an N/A
reason (`capability-not-declared`, `other-binding`, `client-side`, `not-exercised`). `python3 scripts/trace.py` fails
when a requirement is missing, a named test does not exist, or a row has neither a test nor a reason.
`python3 scripts/trace.py --update` regenerates the table from `scripts/trace.py`.

<!-- trace:begin -->
| Requirement | Element | Test | N/A reason |
|-------------|---------|------|------------|
| CORE-SEND-001 | a2a-rpc: PrepareNewTask, CreateTask; a2a-task: Active | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| CORE-SEND-002 | a2a-task: TerminalSend | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend` | |
| CORE-SEND-003 | a2a-validate rule 9 | `DmnTest#validatesRequests`; `ValidationTest#invalidParams` | |
| CORE-STREAM-001 | | | capability-not-declared |
| CORE-STREAM-002 | | | capability-not-declared |
| CORE-STREAM-003 | | | capability-not-declared |
| CORE-GET-001 | a2a-task: ActiveGet, TerminalGet | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend`; `AgentTest#taskAnswersGetTaskAndCancelWhileTheAgentIsWorking` | |
| CORE-GET-002 | a2a-rpc: BuildNotFound | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp`; `WebhookIntegrationTest#unknownTaskIsNotFoundBecauseTheEngineAnswers404ToTheCorrelation` | |
| CORE-LIST-001 | a2a-rpc: SearchTasks, FetchTasks (a2a-fetch-task), BuildTaskList | `ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts`; `ListTasksTest#unknownContextAndOddContextIdsAreHandled` | |
| CORE-LIST-002 | a2a-rpc: BuildTaskList (offset cursor in pageToken) | `ListTasksTest#pagesWithCursorTokens` | |
| CORE-LIST-003 | a2a-rpc: BuildTaskList (sort by status timestamp, descending) | `ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts` | |
| CORE-LIST-004 | a2a-rpc: BuildTaskList (empty nextPageToken on the last page) | `ListTasksTest#pagesWithCursorTokens` | |
| CORE-LIST-005 | a2a-rpc: BuildTaskList (artifacts dropped unless includeArtifacts) | `ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts` | |
| CORE-CANCEL-001 | a2a-task: ActiveCancel | `TaskTest#cancelInputRequiredTaskAndCancelAgainFails` | |
| CORE-CANCEL-002 | a2a-task: TerminalCancel | `TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend`; `TaskTest#cancelInputRequiredTaskAndCancelAgainFails` | |
| CORE-CANCEL-003 | a2a-rpc: BuildNotFound | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp` | |
| CORE-EXECUTION-MODE-001 | a2a-rpc: AwaitReply; a2a-task: IsPending | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`; `AgentTest#sendMessageReturnsWorkingStateWhenTheAgentIsSlow` | |
| CORE-EXECUTION-MODE-002 | a2a-task: ReturnImmediately, PublishInitialReply | `TaskTest#returnImmediatelyAnswersBeforeTheWorkAndTheTaskCompletesAnyway` | |
| CORE-ERR-001 | a2a-validate; a2a-rpc: BuildValidationError | `ValidationTest#unknownMethodAndInvalidRequest`; `ValidationTest#capabilityErrors` | |
| CORE-ERR-002 | a2a-validate rules 8 and 10 | `ValidationTest#invalidParams`; `TaskTest#noIncidentsAfterMalformedInput` | |
| CORE-CAP-001 | a2a-validate rule 6 | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests` | |
| CORE-CAP-002 | a2a-validate rule 4 | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests` | |
| CORE-CAP-003 | a2a-validate rule 5 | `ValidationTest#capabilityErrors`; `DmnTest#validatesRequests` | |
| CORE-CAP-004 | | | capability-not-declared |
| CORE-MULTI-001a | a2a-rpc: PrepareNewTask | `TaskTest#contextIdIsGeneratedEchoedAndChecked` | |
| CORE-MULTI-002a | a2a-rpc: PrepareNewTask (echoes the client contextId) | `TaskTest#contextIdIsGeneratedEchoedAndChecked` | |
| CORE-MULTI-003 | a2a-rpc: PrepareNewTask (uuid) | `TaskTest#taskIdsAreUnique` | |
| CORE-MULTI-004 | a2a-rpc: ProbeFollowUp, BuildNotFound | `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp` | |
| CORE-MULTI-005 | a2a-task: FollowUpArrives, ContextMatches | `TaskTest#inputRequiredThenFollowUpCompletes` | |
| CORE-MULTI-006 | a2a-task: ContextMatches, BuildContextMismatch; TerminalSend | `TaskTest#contextIdIsGeneratedEchoedAndChecked` | |
| CORE-HIST-002 | a2a-task: BuildActiveView, BuildTerminalView (historyLength projection) | `TaskTest#historyLengthLimitsHistoryOnGetTask` | |
| DM-TASK-001 | a2a-task: CreateTaskState, ApplyScenario | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| DM-TASK-002 | a2a-task: states set by ApplyScenario, MarkWorking, MarkCanceled | `TaskTest#cancelInputRequiredTaskAndCancelAgainFails`; `AgentTest#agentFailureFailsTheTask` | |
| DM-MSG-001 | a2a-task: ApplyScenario (agent messages) | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage`; `ValidationTest#directMessageResponse` | |
| DM-MSG-002 | a2a-task: ROLE_USER and ROLE_AGENT | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| DM-PART-001 | a2a-task: ApplyScenario artifact parts | `TaskTest#artifactsAreAttachedByMessageIdPrefix` | |
| DM-ART-001 | a2a-task: ApplyScenario artifacts | `TaskTest#artifactsAreAttachedByMessageIdPrefix` | |
| DM-STATUS-001 | a2a-task: status object | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| DM-SERIAL-001 | every FEEL response builder uses camelCase keys | `TaskTest#artifactsAreAttachedByMessageIdPrefix` | |
| DM-SERIAL-002 | TASK_STATE_* and ROLE_* strings | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| DM-SERIAL-003 | timestamps built as UTC strings ending in Z | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| DM-SERIAL-004 | null keys are dropped from every object | `TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage` | |
| STREAM-ORDER-001 | | | capability-not-declared |
| STREAM-ORDER-002 | | | capability-not-declared |
| STREAM-ORDER-003 | | | capability-not-declared |
| STREAM-ORDER-004 | | | capability-not-declared |
| STREAM-SUB-001 | | | capability-not-declared |
| STREAM-SUB-002 | | | capability-not-declared |
| STREAM-SUB-003 | | | capability-not-declared |
| STREAM-SUB-004 | | | capability-not-declared |
| PUSH-CREATE-001 | a2a-task: ActivePush, TerminalPush (CreateTaskPushNotificationConfig) | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-CREATE-002 | a2a-task: ActivePush, TerminalPush (configs kept in `pushConfigs`) | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks`; `PushIntegrationTest#configurationOperationsWorkThroughTheRealConnectors` | |
| PUSH-GET-001 | a2a-task: ComputePushOutcome | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-GET-002 | a2a-task: ComputePushOutcome (unknown config id) | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-LIST-001 | a2a-task: ComputePushOutcome | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-DEL-001 | a2a-task: UpdatePushConfigs | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-DEL-002 | a2a-task: UpdatePushConfigs (idempotent) | `PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks` | |
| PUSH-DELIVER-001 | a2a-push-notify: DeliverNotification (Authorization header) | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange`; `PushIntegrationTest#cardDeclaresPushAndDeliveryReachesTheHostWithTheConfiguredAuthentication` | |
| PUSH-DELIVER-002 | a2a-task: NotifyPush; a2a-push-notify | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange`; `PushTest#cancelIsDeliveredToo` | |
| PUSH-DELIVER-003 | a2a-task: NotifyPush (payload {task}) | `PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange` | |
| CARD-DISC-001 | a2a-card webhook | `CardTest#cardProcessBuildsACardWithTheThreeToolsAsSkills`; `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills` | |
| CARD-PROTO-001 | a2a-card: supportedInterfaces from A2A_PUBLIC_URL | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills` | |
| CARD-PROTO-002 | a2a-card: supportedInterfaces from A2A_PUBLIC_URL | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills` | |
| CARD-STRUCT-001 | a2a-card: BuildCard | `CardTest#cardProcessBuildsACardWithTheThreeToolsAsSkills`; `CardTest#committedCardMatchesTheCardGeneratedFromTheAgentTools` | |
| CARD-EXT-001 | | | capability-not-declared |
| CARD-EXT-002 | | | capability-not-declared |
| CARD-SIGN-001 | | | not-exercised |
| CARD-SIGN-002 | | | not-exercised |
| CARD-SIGN-003 | | | not-exercised |
| CARD-SIGN-004 | | | not-exercised |
| AUTH-TLS-001 | | | not-exercised |
| AUTH-SERVER-002 | | | not-exercised |
| AUTH-INTASK-001 | | | not-exercised |
| AUTH-INTASK-002 | | | not-exercised |
| AUTH-INTASK-003 | | | not-exercised |
| AUTH-INTASK-004 | | | not-exercised |
| AUTH-SCOPE-001 | | | not-exercised |
| AUTH-SCOPE-002 | | | not-exercised |
| AUTH-SCOPE-003 | | | not-exercised |
| VER-CLIENT-001 | | | client-side |
| VER-SERVER-001 | | | not-exercised |
| VER-SERVER-002 | a2a-validate rule 1 | `ValidationTest#unsupportedVersionIsRejected`; `DmnTest#validatesRequests` | |
| VER-SERVER-003 | a2a-validate: empty or missing A2A-Version is accepted | `ValidationTest#patchVersionAndMissingVersionAreAccepted` | |
| VER-CLIENT-002 | | | client-side |
| BIND-EQUIV-001 | | | other-binding |
| BIND-EQUIV-002 | | | other-binding |
| BIND-EQUIV-003 | | | other-binding |
| BIND-EQUIV-004 | | | other-binding |
| BIND-FIELD-001 | a2a-card: supportedInterfaces | `WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills` | |
| JSONRPC-FMT-001 | a2a-rpc: Parse request, BuildResponse | `ValidationTest#unknownMethodAndInvalidRequest`; `ValidationTest#idIsEchoedAndListTasksReturnsEmptyPage` | |
| JSONRPC-FMT-002 | a2a-rpc webhook response expression | `WebhookIntegrationTest#sendMessageGetTaskAndCancelRoundTripThroughTheRealConnectors` | |
| JSONRPC-SVC-001 | a2a-validate: PascalCase method names | `DmnTest#validatesRequests` | |
| JSONRPC-SVC-002 | a2a-rpc: Parse request reads A2A-Version and Content-Type headers | `ValidationTest#unsupportedVersionIsRejected`; `ValidationTest#wrongContentTypeIsRejected` | |
| JSONRPC-ERR-001 | a2a-rpc: error object has code, message and data only | `ValidationTest#capabilityErrors` | |
| JSONRPC-ERR-002 | a2a-validate error codes | `DmnTest#validatesRequests` | |
| JSONRPC-ERR-003 | ErrorInfo in the data array | `ValidationTest#capabilityErrors`; `ValidationTest#unsupportedVersionIsRejected` | |
| JSONRPC-SSE-001 | | | capability-not-declared |
| JSONRPC-SSE-002 | a2a-validate and a2a-task error codes | `DmnTest#validatesRequests`; `TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp` | |
| GRPC-SVC-001 | | | other-binding |
| GRPC-SVC-002 | | | other-binding |
| GRPC-SVC-003 | | | other-binding |
| GRPC-META-001 | | | other-binding |
| GRPC-ERR-001 | | | other-binding |
| GRPC-ERR-002 | | | other-binding |
| GRPC-ERR-003 | | | other-binding |
| HTTP_JSON-URL-001 | | | other-binding |
| HTTP_JSON-URL-002 | | | other-binding |
| HTTP_JSON-SVC-001 | | | other-binding |
| HTTP_JSON-SVC-002 | | | other-binding |
| HTTP_JSON-QP-001 | | | other-binding |
| HTTP_JSON-ERR-001 | | | other-binding |
| HTTP_JSON-ERR-002 | | | other-binding |
| HTTP_JSON-STATUS-001 | | | other-binding |
| HTTP_JSON-SSE-001 | | | other-binding |
<!-- trace:end -->

## Spike results

Recorded while building, each one decided something.

| Question | Result |
|----------|--------|
| Does a webhook start event answer with the process result? | Yes. In synchronous mode `correlation.variables` holds the end state of the instance, and `responseExpression` returns `{statusCode, headers, body}` with a FEEL context as `body`. |
| Are secrets usable in `responseExpression`? | Yes, `{{secrets.A2A_PUBLIC_URL}}` is replaced textually. Secrets are environment variables prefixed `SECRET_` since 8.9. |
| How does the webhook parse bodies? | JSON is parsed whatever the Content-Type says, headers arrive lower-cased, an invalid JSON body gives an empty HTTP 500 (see known limits). |
| Time format | `now()` serializes as `...Z[UTC]` inside a context, so timestamps are built as `substring(string(now()), 1, 19) + "Z"`. |
| FEEL gaps | No JSON parse function. Reading a missing variable or key returns null without an incident, which hides typos, so every path is covered by a test. |
| `POST /v2/messages/correlation` without a subscription | HTTP 404, mapped to a BPMN error by the HTTP JSON `errorExpression` and retried 3 times at 300 ms. |
| `POST /v2/messages/publication` | Buffers for `timeToLive`, so a reply published before the handler subscribes is still delivered. |
| Exclusive gateway with two true conditions | In a direct test on 8.10.2 the second of two true conditions was taken, three times out of three, not the first. Every router condition is therefore made mutually exclusive. |
| REST authentication | `CAMUNDA_SECURITY_AUTHENTICATION_UNPROTECTEDAPI=true`, no credentials needed. |
| Secondary storage | The default tries Elasticsearch. H2 in memory failed with an exporter position mismatch, H2 on a named volume works and is reset together with the broker data by `down -v`. |
| Sync webhook timeout | The connectors runtime needs `CAMUNDA_CLIENT_REQUEST_TIMEOUT` above the 25 s reply timer (40 s here, 60 s in the tests). |
| Ollama tool calling | `qwen3-coder-30b-64k` calls tools through the completions endpoint. Structured JSON answers were unreliable (the model prefixes prose), so the agent protocol is plain text with a `NEED_INPUT:` marker for questions. |
| AI Agent job with `retries=0` | CPT could not find the job to complete, so the agent uses `retries=1`. |
| Process instance search by tag | `tags` in `POST /v2/process-instances/search` are ANDed, which the ListTasks search relies on. |
| `null` inside a request array | `ignoreNullValues` does not drop a `null` element of an array, so a `null` tag made the engine reject the instance creation and the request hang. The mocked process tests missed it, the real-connector integration test caught it. |
| Secrets in webhook `resultExpression` | Not resolved there (they are in `responseExpression` and in outbound connector inputs), so the push switch is read by an outbound HTTP JSON call that asks the engine to evaluate a FEEL string containing the secret. |
| `Testcontainers.exposeHostPorts` | Breaks later CPT runtimes in the same JVM. The push integration test reaches its receiver through `host.docker.internal` instead. |
| Testcontainers | The Ryuk reaper maps a random host port that once collided with an unrelated local listener, so the reaper is disabled in the test run. |

## Stretch items

Beyond the seven goal conditions. Each one is evidence-backed or stopped at a recorded blocker.

| Item | Status | Evidence |
|------|--------|----------|
| S1 SHOULD and MAY tests | Done | `tck/run-extra.sh`: SHOULD 7 of 7 and MAY 4 of 4 PASS on JSON-RPC, after adding `Cache-Control`, `ETag` and `Last-Modified` to the card response. The AUTH-* SHOULD requirements are not exercised by the TCK. |
| S2 Real ListTasks | Done | `ListTasksTest` (CPT) and `WebhookIntegrationTest#listTasksFindsTasksThroughTheEngineSearchAndFetchesEachOne` (real connectors): filter, sort, cursor paging, `includeArtifacts`, `historyLength`. |
| S3 Push notifications | Done, off by default | `tck/run-push.sh`: PUSH-CREATE, GET, LIST, DEL and DELIVER requirements all PASS with `A2A_PUSH_ENABLED=true`. `PushTest` and `PushIntegrationTest` cover operations, delivery with `Authorization`, cancel, and failed deliveries that never fail the task. |
| S4 Custom JSON-RPC inbound connector | Not built | It would turn invalid JSON into -32700 instead of an empty HTTP 500 (`WebhookIntegrationTest#invalidJsonBodyIsAnEmptyServerErrorFromTheWebhookConnector` records today's behavior). No MUST test sends invalid JSON and the out-of-the-box webhook passes every MUST test, so the plan's condition for promoting it is not met. It also needs a custom connector runtime image next to the bundle. |
| S5 Extra edge cases | Done | `EdgeCaseTest` (ids of every type, batches, unicode, 200 KB messages, 12 concurrent requests, concurrent follow-ups) and concurrency, headers and 405 checks in `WebhookIntegrationTest`. |
| S6 Runtime card builder | Done | `a2a-card-runtime`, compared with the generated card by an integration test. |

## Known limits

- Streaming (`SendStreamingMessage`, `SubscribeToTask`) and the extended Agent Card are not supported and answer -32004.
  Push notifications are not supported and answer -32003.
- ListTasks finds tasks through the engine search, which is eventually consistent: a task created a moment ago can be
  missing for about a second. It reads at most 100 tasks per call and asks each for its state, so it is meant for
  modest volumes.
- Push notifications are off by default, because with the capability declared the TCK skips CORE-CAP-001 (error when
  push is unsupported), which the gate requires to PASS. `tck/run-push.sh` switches them on and runs the PUSH-*
  requirements (all ten pass). Delivery has no SSRF protection, because the TCK receiver is on localhost.
- No authentication. The TCK has no way to inject credentials, and the card declares no scheme.
- The blocking wait is a 25 second timer. After it, SendMessage returns the task in its current state (`WORKING`),
  a documented deviation from "wait for a terminal or interrupted state".
- Tasks live for one hour after reaching a terminal state, then GetTask answers TaskNotFound.
- A body that is not JSON produces an empty HTTP 500 instead of -32700, because the Webhook connector fails before
  the process starts. No MUST test sends invalid JSON.
- Results depend on the pinned TCK commit plus three unmerged fix PRs (#203, #232, #243).
- LLM output varies, so agent tests assert task state and tool use, never wording.
