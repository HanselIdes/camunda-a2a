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

| Component            | Version or setting                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Self-Managed engine  | Camunda 8.8.21, Basic authentication and platform authorizations enabled                                             |
| Stock Connectors     | 8.9.0; no custom worker or custom HTTP server                                                                        |
| Secondary storage    | Elasticsearch 8.17.0                                                                                                 |
| Model                | Local Ollama `qwen3-coder-30b-64k:latest`, digest `13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253` |
| AI Agent template    | `io.camunda.connectors.agenticai.aiagent.jobworker.v1`, version 5                                                    |
| Client HTTP template | `io.camunda.connectors.HttpJson.v2`, version 12                                                                      |
| Transport            | Direct Connectors HTTPS, with certificate verification on both external and BPMN clients                             |
| Runtime settings     | `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`, `CAMUNDA_CLIENT_EXECUTION_THREADS=4`                        |
| Engine exporter      | Self-Managed 8.8.21 only: explicit CamundaExporter class and `bulk.delay=1`; see below                               |

This is an **8.8 engine with 8.9 Connectors** configuration, not matched-8.8 proof. Other combinations and model
providers are not established by this result. The local check uses an isolated, disposable cluster and synthetic data.
Modeler import and Tasklist form rendering still require their own observed checks.

The execution-thread setting matters when client and server use the same Connectors runtime: a synchronous
client HTTP job must not occupy the only job-execution thread while the server needs another HTTP job.
The four-thread configuration passed the supplied client flow. It is not a capacity guarantee.

The [96357f5 verification record](../verification/96357f5/summary.json) contains three clean-source runs of
the pinned TCK **MUST gate**: each passed 56 MUST requirements and excluded 58 with documented reasons
(25 undeclared capabilities, 17 other bindings, 14 not exercised by the TCK and two client-side requirements).
Each run executed 68 tests, skipped 167, and reported no failures, errors or engine incidents.
The [detailed gate audit](../verification/96357f5/gate.json) maps every MUST and skipped test to its reason.
This is **not full A2A conformance**. The official SDK 1.2.3 flow and the supplied BPMN client passed the
exact real-model outcome checks; the complete Maven suite finished with 172 tests and no failures/errors/skips.

The TCK does not test 16 MUST requirements here: card signing (`CARD-SIGN-001` through `004`), TLS
(`AUTH-TLS-001`), server authentication (`AUTH-SERVER-002`), in-task authorization (`AUTH-INTASK-001` through
`004`), authorization scopes (`AUTH-SCOPE-001` through `003`), version semantics (`VER-SERVER-001`), client
headers (`VER-CLIENT-001`) and client/server patch negotiation (`VER-CLIENT-002`). Native verification separately checks
certificate validation and missing/invalid API-key rejection; those are not TCK passes.
The card is unsigned. One shared key supplies no per-caller task scoping.
The [individual dispositions](../verification/96357f5/requirement-dispositions.json) distinguish inactive signing
and in-task credential-acquisition features from applicable server and shipped-client obligations.
The 96357f5 dispositions describe that historical source. Major.Minor matching is implemented at 0bc60d4;
its native evidence is separate from the older reports. Applicable open gates still prevent final acceptance:
the scoped TCK result alone cannot close them. The historical gate's client-side
label for `VER-CLIENT-002` does not remove its server-side obligation.

Across the three runs, raw Extensions-call latency was **1.630 / 1.764 / 2.221 seconds**
(min/median/max), against its unchanged five-second read timeout. Normal RPC latency across 195 requests
was **0.097 / 1.657 / 4.532 seconds**, against the pinned transport's unchanged 30-second read timeout.
These measurements describe this local configuration, not a latency guarantee.

## Prepare the cluster

Start timing an adoption attempt only after the cluster, Modeler, runtime, model and credentials are ready.
Keep the engine API authenticated. Configure the stock Connectors runtime's engine connection as usual; the
engine credentials below also authenticate the protocol's REST calls.

Set these stock Connectors environment variables explicitly:

```text
CAMUNDA_CLIENT_EXECUTION_THREADS=4
CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false
```

Four execution threads are required for the demonstrated same-runtime client/server flow; one thread can cause starvation
while the synchronous client waits for server HTTP jobs. On an 8.8 engine, disable active-version polling because
the newer importer statistics API is unavailable. These settings do not disable engine authentication.

On the Self-Managed engine, the low-latency/conformance profile requires these explicit deployment settings:

```text
ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_CLASSNAME=io.camunda.exporter.CamundaExporter
ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_ARGS_BULK_DELAY=1
```

These settings were exercised on **Self-Managed 8.8.21 only**; other engine versions are unverified.
The class name is necessary when explicitly configuring the exporter through these environment variables:
omitting it caused engine startup to fail with "Expected to find a 'className' configured for the exporter."
The [8.8.21 exporter source](https://github.com/camunda/camunda/blob/8.8.21/zeebe/exporters/camunda-exporter/src/main/java/io/camunda/exporter/config/ExporterConfiguration.java)
sets the default forced-flush delay to five seconds. The protocol reads indexed task state, so this delay can
consume a short client's entire read budget. A fresh default-delay TCK run failed the Extensions-header call
at its unchanged five-second read timeout; another run passed that call in 4.553 seconds. Neither result
establishes reliable headroom.

One-second flushing trades smaller batches and more frequent storage requests for lower indexing latency;
it can increase CPU, I/O and storage request overhead and reduce throughput efficiency. Size and measure
the secondary storage accordingly. This is a deployment prerequisite, not behavior installed by importing
the BPMN, nor a production sizing recommendation. Managed/SaaS clusters may not expose this setting; their
latency and conformance remain unverified.

The observed 8.8.21 exporter startup configurations retain the same logged index, archiver, cache and
post-export defaults; only `bulk.delay` differs. Its connection object is not expanded in that log.
The [8.8.21 configuration merge](https://github.com/camunda/camunda/blob/8.8.21/configuration/src/main/java/io/camunda/configuration/beanoverrides/BrokerBasedPropertiesOverride.java)
retains the unified secondary-storage connection, index prefix and security configuration.
Authenticated indexed process/variable/user-task searches and user-task completion were exercised with this
profile. **Retention remains disabled**, its stock default. Operate/Tasklist visual UI behavior and enabled
history cleanup have **not** been verified with the tuned exporter.

Provide HTTPS on the **Connectors runtime itself**, or through an optional TLS terminator. With stock Spring Boot
Connectors, direct TLS uses `SERVER_SSL_ENABLED=true`, `SERVER_SSL_KEY_STORE`, `SERVER_SSL_KEY_STORE_TYPE=PKCS12`
and `SERVER_SSL_KEY_STORE_PASSWORD`. Use a certificate valid for the advertised hostname. Clients must trust its
issuer; do not disable certificate verification. The local verifier creates a disposable certificate and truststore,
not a production certificate.

The stock Connectors 8.10.0 image healthcheck defaults to an HTTP readiness URL even when direct TLS is enabled.
For that image, set `HEALTHCHECK_URL` to the runtime's HTTPS readiness endpoint with a certificate-valid hostname
and configure the healthcheck JVM's truststore. The isolated verifier uses
`https://127.0.0.1:8080/actuator/health/readiness`, whose IP is in its generated certificate.
This setting alone does not establish 8.10 runtime compatibility.

If a private issuer is used, configure the JVM truststore for outbound client calls as well. Keep private keys,
keystore passwords and API keys out of BPMN, repository files, screenshots and reports.

Use `CAMUNDA_CONNECTOR_SECRETPROVIDER_ENVIRONMENT_PREFIX=SECRET_` if supplying local connector secrets through
environment variables. For example, connector secret `ENGINE_URL` is then supplied as `SECRET_ENGINE_URL`.
Use your deployment's normal secret provider instead where appropriate.

| Connector secret                     | Required value                                                                     |
| ------------------------------------ | ---------------------------------------------------------------------------------- |
| `ENGINE_URL`                         | Engine REST base URL without `/v2`, reachable from Connectors                      |
| `ENGINE_USERNAME`, `ENGINE_PASSWORD` | Authorized engine credentials; do not disable platform authentication              |
| `A2A_API_KEY`                        | Shared key for task operations; supply it only over HTTPS                          |
| `A2A_AGENT_PROCESS`                  | `a2a-card-dispute`                                                                 |
| `A2A_RPC_URL`                        | Complete HTTPS webhook URL, including any cluster prefix and `/inbound/a2a`        |
| `A2A_AGENT_CARD_URL`                 | Complete HTTPS discovery URL, including any cluster prefix and `/inbound/a2a-card` |
| `CAMUNDA_PROVIDED_LLM_API_ENDPOINT`  | OpenAI-compatible base URL reachable from Connectors, including `/v1`              |
| `CAMUNDA_PROVIDED_LLM_API_KEY`       | Provider credential; the tested local Ollama setup uses its documented dummy key   |
| `CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL` | `qwen3-coder-30b-64k:latest` for the verified local configuration                  |

The `CAMUNDA_PROVIDED_LLM_*` names are configuration names, not a claim that this check used Camunda's SaaS model.
For Docker Desktop, a host-local Ollama service can be reached through `host.docker.internal`; do not assume
that hostname works on a remote cluster. Model inference needs sufficient local resources.
The supplied AI Agent activity `AgentTools` already references these three model/provider secrets through its
`provider.openaiCompatible.*` inputs. Changing their secret values does not require editing that activity.
Changing to a different provider type, business tool or system instructions does require configuring the agent BPMN.

## Import and deploy

Use only the Basic profile for this candidate. Do not import or deploy the OAuth profile alongside it: the profiles
share executable process IDs.

Import these resources into one Modeler project:

| Resource                                                             | Purpose                                                                   |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [profiles/basic/a2a-protocol.bpmn](profiles/basic/a2a-protocol.bpmn) | Authenticated, push-disabled protocol; deploy unchanged                   |
| [../dmn/a2a-validate.dmn](../dmn/a2a-validate.dmn)                   | Protocol request validation                                               |
| [demo/a2a-card.bpmn](demo/a2a-card.bpmn)                             | Direct discovery card with actual skill, complete URL and API-key scheme  |
| [demo/a2a-card-dispute.bpmn](demo/a2a-card-dispute.bpmn)             | AI agent, reconciliation tool and follow-up loop                          |
| [demo/a2a-client.bpmn](demo/a2a-client.bpmn)                         | BPMN client with explicit card discovery, authenticated calls and polling |
| [demo/a2a-client-ask.form](demo/a2a-client-ask.form)                 | Synthetic starting request                                                |
| [demo/a2a-client-answer.form](demo/a2a-client-answer.form)           | Clarification reply                                                       |
| [demo/a2a-client-result.form](demo/a2a-client-result.form)           | Returned result and arithmetic evidence                                   |

Import the three JSON files in [templates/](templates/) and the
[upstream AI Agent version 5 template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json)
as element templates, using the Modeler's template-import workflow. The stock templates are pinned; the two blueprint templates configure the authenticated RPC endpoint
and public discovery card. Do not use the archived experiment's unauthenticated RPC template.

The AI template remains an upstream dependency with its own proprietary module terms; its JSON is imported from
upstream rather than copied into this repository. See [third-party notices](../../THIRD_PARTY_NOTICES.md).

Deploy all eight BPMN/DMN/form resources together, so the forms and decision are available to the processes.
No generator execution, protocol editing, custom worker, nginx route or standard-path ingress is required.
Wait for both webhook registrations to become healthy before testing.
In Operate, inspect the inbound connector status on `CardRequested` in `a2a-card` and `RpcReceived` in `a2a-rpc`.
Externally, `curl --fail "$A2A_AGENT_CARD_URL"` must return the card, and an unauthenticated POST with a JSON body
to `A2A_RPC_URL` must return 401, not 404. A 404 means the task webhook is not yet registered.
Use your deployment's trusted CA configuration for every curl command; do not use `--insecure`.

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

For a minimal external check, set `A2A_RPC_URL`, `A2A_AGENT_CARD_URL` and `A2A_API_KEY` in your local shell
without committing their values or including them in screenshots. These shell variables do not configure connector
secrets automatically. The examples below require curl and send synthetic data only:

```sh
curl --fail "$A2A_AGENT_CARD_URL"
curl --fail "$A2A_RPC_URL" \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -H "X-A2A-Api-Key: $A2A_API_KEY" \
  --data '{"jsonrpc":"2.0","id":"demo-send","method":"SendMessage","params":{"message":{"messageId":"demo-request-1","role":"ROLE_USER","parts":[{"text":"Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool."}]}}}'
```

Read `result.task.id` from the response, set `TASK_ID` to that value and poll:

```sh
curl --fail "$A2A_RPC_URL" \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -H "X-A2A-Api-Key: $A2A_API_KEY" \
  --data "{\"jsonrpc\":\"2.0\",\"id\":\"demo-poll\",\"method\":\"GetTask\",\"params\":{\"id\":\"$TASK_ID\"}}"
```

HTTP 200 is not sufficient: inspect JSON-RPC `error`, the task status and the exact reconciliation artifact above.
A working task needs further polling; an input-required task needs a follow-up message on the same task/context.

## Adapt the business process

The process contract is independent of the card-dispute tool: a selected process receives `task` and `req`, calls
`a2a-task-update` with `{state, text, artifacts}`, and explicitly maps the updated `task` back to its root scope.
For input-required turns it waits for `a2a-send`, correlated by `task.id`, and applies the follow-up mappings shown
in the supplied agent. Do not start another task or discard its conversation when handling a follow-up.

[../bpmn/a2a-echo.bpmn](../bpmn/a2a-echo.bpmn) is the separately tested deterministic contract reference, not the
public demonstration. When selecting a different process, update the discovery card's name, description and skills
to describe that process. Selecting `A2A_AGENT_PROCESS` does not automatically rewrite the card.
To try echo, download/import that linked BPMN separately, deploy it alongside the unchanged Basic protocol and
validation DMN, and set connector secret `A2A_AGENT_PROCESS=a2a-echo`. Echo uses only the shared `a2a-task-update`
process from the protocol: it needs no model, form or classification DMN. It is not in the default import manifest.
In `a2a-card.bpmn`, select start event `CardRequested` and edit the `inbound.responseExpression` property:
update `body.name`, `body.description` and `body.skills` (IDs, names, descriptions, tags and examples).
Keep the complete endpoint URL, API-key scheme and disabled-capability declarations.

The default outcome returns a Task. A business process can explicitly set `outcome.responseMode="message"` for a
completed text-only reply. The protocol returns `result.message` only when the task is completed, has an agent status
message and has no artifacts; all other outcomes still return `result.task`. The stored completed task remains
available through the returned message's `taskId`. The internal response-mode field is omitted from Task views.
The protocol never chooses this mode from a client message ID or request content. The supplied real-agent demo
keeps the default Task response so its reconciliation artifact is not discarded.

Leave the literal-input encoder and `data.userPrompt.prompt =jsonPrompt` mapping intact. They preserve numeric-leading,
JSON-like, quoted, backslash, control-character and leading-equals text through the stock connector's string binding.
System instructions and business tools are modelled in the agent, not the protocol.

### Required cancellation hook

Each adapted business process must include the root-level interrupting event subprocess shown as
**Cancel this A2A task** in echo and the card-dispute example. The nonshipping conformance fixture uses the same
hook. Copy that subprocess together with its message definition when adapting a different process:

1. Use a message start event with **Interrupting** enabled, message name **`a2a-cancel`** and correlation key
   **`=task.id`**. Do not use a message start event that creates another process instance, a non-interrupting event
   or a correlation key based on context ID. Keep the subprocess at the business process's root level.
2. Connect it to a FEEL script task with result variable **`task`**, then an end event. Retain the supplied script:
   it preserves an already-terminal outcome; otherwise it writes the canceled status, empty artifacts and the
   next revision together. Do not create a local `task` variable/input mapping in this subprocess; its script
   updates the existing root variable.
3. Keep business task updates serialized through `a2a-task-update`, with the explicit output mapping to root
   `task`. End business work after a terminal outcome. Do not introduce parallel or external writers to that
   variable, or catch cancellation and resume the interrupted business path.
4. Deploy the adapted process and select it through `A2A_AGENT_PROCESS`. No protocol edit, generator,
   additional connector, custom worker or HTTP server is needed.

Cancellation uses synchronous `POST /v2/messages/correlation` with this fixed message name and the exact task ID.
It does **not** publish or buffer a message, specify a TTL, or fall back to another task. The engine interrupts
active business tokens and child calls before the hook commits cancellation; a late completion command for
interrupted work is rejected. This stops further process work, not an external side effect already performed.
The business process owns any compensation and side-effect protection.

If cancellation wins, `CancelTask` returns the **persisted** canceled task, without artifacts or a status message.
Subsequent `GetTask` and `ListTasks` retain that outcome. A repeated cancel returns `TaskNotCancelableError`
(`-32002`); follow-up input is rejected with `UnsupportedOperationError` (`-32004`) and cannot revive the task.
If the business terminal update wins first, its status/text/artifacts remain intact and cancellation returns
`-32002`, never a canceled result. An unknown task returns `TaskNotFoundError` (`-32001`).

A missing hook or no remaining matching subscription returns `-32002` after at most three correlation attempts
with 0.3-second retry waits. It does not write canceled state. After successful correlation, the protocol waits
up to five seconds for the indexed terminal revision; expiry returns internal error `-32603` with
`DEADLINE_EXCEEDED`, not a fabricated canceled response. Engine API failures remain connector failures/retries
or incidents, not successful cancellation. After an uncertain transport failure, inspect the failed execution
and poll `GetTask` rather than assuming whether cancellation occurred.

## Operational boundary and remaining gates

The API key establishes one shared trust boundary, not per-user task authorization. Possession of the key permits
operations on this agent's tasks. Engine permissions and secret distribution must match that boundary.
Task search uses the selected agent process; existing-task lookups have a three-second indexing/variable window.
Push, streaming and A2A 0.3 interoperability are not advertised.
Task requests must select the advertised `A2A-Version: 1.0`. Numeric patches such as `1.0.2` use the same
semantics; other Major.Minor versions are rejected with `VERSION_NOT_SUPPORTED`.
Missing or empty version headers default to unsupported 0.3 and receive that error rather than silently selecting 1.0.
The supplied client uses 1.0. Shipped examples do not request additional client credentials during a task;
business-input clarification is not an in-task authorization flow.
Repeating a new-task submission with the same `messageId` creates independent tasks. There is no message-ID
side-effect deduplication or idempotency guarantee; the business process owns any required side-effect protection.

Terminal-state races, bulk concurrency across two agents, duplicate-request behavior, pagination/retention,
restart recovery, expired/insufficient credentials, the full version matrix,
Modeler/form usability and a timed fresh adoption remain unverified. The recorded MUST-gate and SDK results
apply only to their exact source and deployment settings, not subsequent changes. Do not infer exactly-once
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

The runtime verifier reserves available loopback ports and creates a unique per-run Compose project and random temporary
credentials. It refuses to reuse existing project resources and cleans up only its own startup, including a partial
startup failure. Docker rejects competing port claims rather than reusing another service.
It creates a certificate and truststore with `openssl`/`keytool`, starts the pinned stack, deploys the
committed resources, checks authentication/discovery, expected real-model results, verbatim numeric-leading continuation
and final BPMN client completion, verifies persisted variables exclude runtime credentials, then removes its containers.
It does not stop or reuse unrelated clusters.
Docker, Python 3, OpenSSL, a JDK/keytool and the already-running local Ollama model are required.
`PROOF_AGENT_PROCESS=a2a-echo` selects the deterministic contract check without model inference.
Model-input diagnostics contain synthetic prompts only and are stored under ignored `experiment-3/reports/runtime`.
`PROOF_REPORT_DIR` can select another report directory.
Each native acceptance run requires a clean committed checkout and a new report directory; existing evidence
directories are never overwritten. `runtime-provenance.json` records the source snapshot, declared runtime
settings and verdict, plus actual image IDs/digests on success. A changed checkout invalidates the run.
`native-checks.json` records the missing/invalid-key matrix across all operations, known/unknown resource
non-disclosure and version/patch checks; SDK reports also record request versions.
The verifier applies `tests/runtime/exporter-low-latency.yml` to the base Compose file explicitly.
`PROOF_EXPORTER_PROFILE=default` omits that override and captures the stock five-second configuration instead.
Both modes save the actual logged exporter configuration; object identity fields are not connection evidence.
Index observation has a bounded deadline and fails on absence, ambiguous root values or failed searches.

For official Python SDK interoperability, create a separate Python 3.10+ environment, install
`experiment-3/tests/runtime/requirements-sdk.txt`, then set `PROOF_SDK_PYTHON` to that environment's Python
executable when running the verifier. This uses `a2a-sdk==1.2.3`, not the conformance suite's transport client,
and checks discovery, polling, same-task clarification, exact real-tool evidence and context-filtered listing.

For the unchanged pinned conformance suite, prepare a separate checkout at
`263b9cfaf16a554bdfb166a7ba5b67716e946349`, apply `experiment-3/tck/patches/tck-pr-stack.patch` from this
repository and run `uv sync` there.
Set `PROOF_TCK_DIRECTORY` to its absolute path and run the same verifier. The runner checks the complete
patched source fingerprint before execution and deploys a clearly nonshipping deterministic fixture.
It preserves the raw five-second read timeout and the existing assertions/exclusions. The explicit test
connection adaptations (CA trust, scoped API key, card path, runner-appended slash and local hostname) are
recorded separately in `tck/provenance.json`. `tck/gate.json` lists every MUST requirement and every skipped
test with requirement IDs and exclusion reasons; totals do not mean every A2A requirement passed.
This contributor adapter is not proof of standard well-known-path ingress or SaaS conformance.

`PROOF_REPORT_DIR=/path/to/new-load-report python3 experiment-3/tests/runtime/reliability.py` checks two separate
authenticated engine/Connectors deployments, not two runtimes with different global secrets sharing one engine.
It requires no model inference. The driver compares 100 globally sequential and 20 concurrent exact echo results,
then checks foreign-task lookups, paginated listing, duplicate submissions and restart preservation.
During concurrency it deploys a nonshipping 15-second timed echo variant and requires all 20 tasks to be accepted
as working before the earliest possible completion; overlapping HTTP requests alone do not satisfy the check.
The driver removes only its owned runtimes. This is a contributor check, not an already-passed acceptance claim.

`PROOF_AGENT_PROCESS=a2a-echo PROOF_OPERATIONAL_CHECKS=1 python3 experiment-3/tests/runtime/verify.py`
also deploys a clearly nonshipping controlled business process against the stock runtime. It checks both terminal
orderings, rejected late business completion, 24 seeded randomized completion/cancel races, 12 follow-up/cancel
races, four concurrent-follow-up pairs, cancellation while input-required, repeated operations, stored root state,
task listing and missing-hook failure. `terminal-checks.json` records exact outcomes;
`runtime-provenance.json` identifies the tested source.
This is not evidence of a pass until that exact-source run completes.

`python3 experiment-3/tools/build_blueprint.py --check` checks the committed candidate assets against their builder,
using immutable upstream template URLs. `python3 experiment-3/tools/build_core.py --check` checks both protocol profiles.
`python3 experiment-3/tools/check_resources.py` checks the selected import set for template-version, form, decision
and process reference closure. Add `--ref <full-public-commit-SHA>` to print the 12 immutable resource URLs.
None of these commands changes an adopter's deployment. A successful runtime check is not a conformance or Modeler-import pass.
