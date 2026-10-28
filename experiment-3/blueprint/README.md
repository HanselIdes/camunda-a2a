# A2A community blueprint candidate

**Early-access, non-production prototype.** This unmaintained community blueprint is subject to the
[license and licensing limitations](../../README.md#license-and-support). This is a functional prototype:
informed-agent checks are allowed; no adoption-time threshold or human-usability claim applies.
The [numbered demo README](demo/README.md) is the current import manifest and quickstart.
Every verification record below is source-pinned historical evidence unless it explicitly names the
current numbered candidate. Do not use prior Desktop/Hub, TCK, or model runs as verification of changed
assets. Marketplace import and external licensing/eligibility approval are separate deferred release
gates, not prototype acceptance. SaaS runtime and Camunda-provided model execution are unverified.

**Earlier 8.9 input-only repair: overall FAIL.** Exact model-input preservation passes, but incomplete
leading-equals JSON input caused the real model to invent reconciliation fields and the demo to
complete instead of asking for missing input. The existing synthetic-result guard does not validate
that fields came from the request. This is a material missing-input/grounding limitation, not a
formatting issue or a passed release gate. See the [versioned results and preserved failures](../verification/3634072-89/README.md).
The [earlier confirmed-input prototype](../verification/fb158a5-89/README.md) passed its bounded
checks on engine 8.9.26 / Connectors 8.9.17 / Elasticsearch 8.19.23. Those results do not verify
the current numbered candidate.

The demonstration has a client-side AI Agent Task (template version 8) that chooses among A2A discovery,
send, poll, and user-input tools inside a parallel multi-instance ad-hoc subprocess. The protocol and
discovery webhooks share process `a2a-rpc`; a new A2A task starts the separate server-side AI agent
`a2a-card-dispute`. Its deterministic BPMN tool validates explicit synthetic inputs and returns arithmetic
evidence for the client to review. The shipped agent tasks reference the `CAMUNDA_PROVIDED_LLM_*` secrets;
the local validation override does not verify SaaS model access. No refund, real dispute decision, fraud
determination, financial integration, or custom HTTP server is included.

## 8.9+ candidate configuration

The candidate targets **Camunda 8.9.26 with stock Connectors 8.9.17** and Elasticsearch 8.19.23.
The focused client-agent E2E passed on clean source commit
[`d4f92c1`](../verification/d4f92c1/README.md). This is a specific validation profile, not a blanket
claim for every 8.9+ combination.
Earlier engine 8.8.44 / Connectors 8.8.24 evidence showed the synchronous webhook result needed by the
protocol was unavailable; it does not establish support for 8.8.

| Component            | Version or setting                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Self-Managed engine  | Camunda 8.9.26, Basic authentication and platform authorizations enabled                                             |
| Stock Connectors     | 8.9.17; no custom worker or custom HTTP server                                                                       |
| Secondary storage    | Elasticsearch 8.19.23                                                                                                |
| Client AI Agent Task | `io.camunda.connectors.agenticai.aiagent.v1`, version 8; engine constraint `^8.9`                                    |
| Server AI Agent      | `io.camunda.connectors.agenticai.aiagent.jobworker.v1`, version 5                                                    |
| HTTP template        | `io.camunda.connectors.HttpJson.v2`, version 13                                                                      |
| Transport            | Direct Connectors HTTPS, with certificate verification on both external and BPMN clients                             |
| Runtime settings     | `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`, `CAMUNDA_CLIENT_EXECUTION_THREADS=4`                        |
| Engine exporter      | Explicit CamundaExporter class and `bulk.delay=1`; see below                                                      |

Use `CAMUNDA_PROVIDED_LLM_API_ENDPOINT`, `CAMUNDA_PROVIDED_LLM_API_KEY`, and
`CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL` in the shipped BPMN. An isolated local verification may override
those environment-supplied secrets with Ollama; that proves only the actual client/server calls against
that override, not SaaS model availability. Other engine, Connector, and model-provider combinations are
unverified. The local cluster is disposable and uses synthetic data.
The [cross-surface evidence matrix](../verification/32f8d4e/prototype-evidence.md) records exact known
versions, unknowns, included assets and per-outcome evidence gaps for earlier sources. Historical
Desktop/Hub and Tasklist reports below describe earlier resource sets and do not verify this revised
client agent, current display names, or Camunda-provided model execution.

The execution-thread setting matters when client and server use the same Connectors runtime: a synchronous
client HTTP job must not occupy the only job-execution thread while the server needs another HTTP job.
The candidate verifier uses four threads; this is not a capacity guarantee.

## Frozen-source engineering results

The [d4e6273 record](../verification/d4e6273/summary.json) completes the engineering series on clean,
unchanged source `d4e6273c862b387ee7b2a49b992cd4db5f56a922`. This does **not** close the external release gates.
The [full Maven suite](../verification/d4e6273/full-suite-checks.json) passed **190 tests across 19 suites**,
with zero failures, errors, skipped tests or reruns. The POM configures `excludedGroups=ollama`, but no test at
this source carries that tag: no tests were excluded. Native real-model checks run separately.

All three [pinned TCK MUST-gate repeats](../verification/d4e6273/tck-1-gate.json) passed: each executed
68 tests, skipped 167, passed 56 MUSTs and excluded 58 with explicit reasons. The raw assertions and
five-second Extensions/30-second RPC read timeouts were unchanged. Across 195 normal RPC calls,
min/median/max was **0.098/1.627/4.184 seconds**; the three Extensions calls took
**1.245/1.582/2.393 seconds**. These measurements are not latency guarantees or full A2A conformance.

The [native checks](../verification/d4e6273/native-native-checks.json) passed the all-operation key/version
matrix, known/unknown-resource checks and no-unauthorized-business-start assertion. All
[44 terminal cases](../verification/d4e6273/native-terminal-checks.json),
[125 context-filtered exact listing results](../verification/d4e6273/native-listing-checks.json) and
[nine failure/recovery cases](../verification/d4e6273/native-failure-checks.json) passed.
The [official SDK 1.2.3](../verification/d4e6273/sdk-real-model-sdk.json), real-agent clarification and
reconciliation, supplied BPMN client and [client version checks](../verification/d4e6273/sdk-real-model-bpmn-client-versions.json)
also passed.

The [two-agent run](../verification/d4e6273/reliability-summary.json) passed 100 sequential and 20 concurrent
exact outcomes with 120 unique IDs. All 20 were accepted within **2.606 seconds** of a 15-second business timer.
Both agents concealed foreign get/cancel/follow-up requests as not found and listed exactly 60 owned tasks.
Connectors/engine restarts preserved the existing task and allowed new work. Duplicate submissions still create
independent tasks, with no side-effect deduplication.

The [16 individual supplemental dispositions](../verification/d4e6273/requirement-dispositions.json) and
[combined 114-MUST audit](../verification/d4e6273/combined-mandatory-audit.json) distinguish **56 TCK-verified**
requirements, **eight supplementally verified applicable** requirements, and **50 inactive or other-binding**
requirements. Inactive signing and delegated-authorization conditions are not tested passes. This establishes
the recorded declared Basic JSON-RPC profile only, not production eligibility, other profiles or publication.

## Historical adaptation diagnostic

A separate AI-agent review session with prior knowledge of the repository reported
[139 seconds at source 597b152](../verification/597b152/adoption.md), starting with a ready cluster, model
and credentials. This was not a fresh human adopter or usability study and does not establish a newcomer's
time to success. The run reached an exact external real-model result,
then adapted a different deterministic process with follow-up input and the required cancellation hook.
It required no protocol edits, generator, custom worker or custom HTTP server.
The report records all supplied settings and deviations. It is a single-machine observation transcribed from
session output, without separate raw logs or image digests; it is not a reproducible runtime archive.
Deployment used the engine REST API, not Modeler. It does not close import, template or form-usability gates.

## Supplemental native failure checks

The [07b3387 failure evidence map](../verification/07b3387/failure-evidence-map.md) covers a true outage of
the verifier-owned engine during an external GetTask call and refused follow-up/cancellation correlation
transport. The outage returned HTTP 503 with UNAVAILABLE; after restoration, the stored task was unchanged
and fresh work completed exactly. Refused correlation created operator-visible incidents without a fabricated
RPC response or business-state change. Repair recovered the original requests and exact terminal outcomes.
These are functional checks on engine 8.8.21 / stock Connectors 8.9.0, not adoption or editor evidence.
Those source-pinned assets were byte-identical to d4e6273; the current 8.9 candidate has a separate prompt mapping.
The first, failed harness observation is preserved separately.
Native response loss after a committed correlation was not injected; existing Core evidence retains that scope.

## Earlier source-specific checkpoints

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
its native evidence is separate from the older reports. Those historical scoped TCK results alone could not
close the applicable gates; the frozen-source audit above supplies the current dispositions. The historical gate's client-side
label for `VER-CLIENT-002` does not remove its server-side obligation.

Across the three runs, raw Extensions-call latency was **1.630 / 1.764 / 2.221 seconds**
(min/median/max), against its unchanged five-second read timeout. Normal RPC latency across 195 requests
was **0.097 / 1.657 / 4.532 seconds**, against the pinned transport's unchanged 30-second read timeout.
These measurements describe this local configuration, not a latency guarantee.

The [0bc60d4 checkpoint](../verification/0bc60d4/summary.json) records later exact-source TCK/native/SDK
successes, two-agent load/restart results, the 8.9 native/SDK attempt and the 8.10 real-agent failure.
It also preserves the cancellation/completion defect; those successful checks did not close that defect.

The [f09fe52 cancellation checkpoint](../verification/f09fe52/summary.json) verifies the required interrupting
hook on authenticated **8.8.21 / Connectors 8.9.0**. Its 44 native cases include both terminal orderings,
24 seeded randomized completion/cancel races (17 canceled, seven completed), 12 follow-up/cancel races,
four concurrent-follow-up pairs, cancellation while input-required, missing-hook failure and terminal reads/listing.
Late business user-task completion returned 404. Separately, all 18 core process tests passed on clean f09fe52
source, including rejected late completion of an activated AI-worker job, 24 randomized orderings and bounded
index-visibility failure. These process tests use the configured 8.10.2 engine and Harness HTTP adapter;
they are not the native 8.8 runtime proof.

The [a45de8c checkpoint](../verification/a45de8c/summary.json) checks cancellation reconciliation and complete
task listing. On clean source, **28 focused process tests passed**: a committed correlation followed by
not-found/retry returns the observed canceled task; a lost response causes an operator-visible incident rather
than a fabricated protocol outcome; unavailable state returns a bounded error. These are engine-backed Harness
injections, not native network-fault proof. On **8.8.21 / Connectors 8.9.0**, all 44 native terminal cases passed
again, together with 22 API-key checks, 12 version checks and **125 exact unique echo results** listed across
four pages (37/37/37/14). Both runs recorded a clean, unchanged source commit.
Those focused checks did not themselves complete the final-source series; no earlier result is silently
carried to a changed protocol.

The [e4dd045 failure/recovery checkpoint](../verification/e4dd045/summary.json) exercises the **unmodified
shipped webhook profile** with a wrong deployment `ENGINE_PASSWORD` and an actual user lacking business-start
permission. Each caller reached its explicit five-second deadline. The three shipped attempts and 30-second
backoff produced a `CreateTask` incident after approximately 68 and 69 seconds, respectively, with no fabricated
RPC response. Correcting the secret or applying the tested combined authorization configuration, then retrying
the original job, returned the exact original result and allowed fresh external work. The authorization fixture
adds membership in the **built-in `admin` role**, not a read-only role, plus an explicit business-start grant.
Recovery does not isolate either grant's causal contribution or establish a minimal permission set.
Separate derived-input cases cover invalid and password-rotated Basic credentials, insufficient permission,
an unreachable connector endpoint, model-provider errors and exact real-model recovery.
The [bc0a693 client checkpoint](../verification/bc0a693/summary.json) records official SDK patch negotiation,
the packaged discovery expression evaluated by the engine across `1.0`, `1.0.2` and `1.0.999`, and native
received `A2A-Version: 1.0` headers. The exact packaged polling connector runs in an isolated stock-BPMN
fixture because fast work may not enter the full client's polling branch. These are supplemental,
source-specific checks. The [checkpoint's 16 dispositions](../verification/e4dd045/requirement-dispositions.json)
name the gates that were still open there; use the frozen-source audit above for their later closure.

## Prepare the cluster

Record cluster, editor, runtime, model and credential prerequisites before functional verification.
There is no setup-time threshold. Record actual supplied settings, steps, results and any deviations.
Keep the engine API authenticated. Configure the stock Connectors runtime's engine connection as usual; the
engine credentials below also authenticate the protocol's REST calls.

Set these stock Connectors environment variables explicitly:

```text
CAMUNDA_CLIENT_EXECUTION_THREADS=4
CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false
```

Four execution threads are required for the demonstrated same-runtime client/server flow; one thread can cause starvation
while the synchronous client waits for server HTTP jobs. Active-version polling remains disabled in the
declared test profile. These settings do not disable engine authentication or establish 8.8 support.

On the Self-Managed engine, the low-latency/conformance profile requires these explicit deployment settings:

```text
ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_CLASSNAME=io.camunda.exporter.CamundaExporter
ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_ARGS_BULK_DELAY=1
```

Historical exporter diagnostics below use **Self-Managed 8.8.21**; current 8.9 checks record their own effective settings.
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

Both `A2A_RPC_URL` and `A2A_AGENT_CARD_URL` must resolve and have a valid certificate from the Connectors
runtime running the supplied BPMN client and from external clients. A hostname that works only from a
container or only from the adopter's machine is not sufficient. Include the advertised hostname in the
certificate's Subject Alternative Names and configure trust on both clients.

The `CAMUNDA_PROVIDED_LLM_*` names are configuration names, not a claim that this check used Camunda's SaaS model.
For Docker Desktop, a host-local Ollama service can be reached through `host.docker.internal`; do not assume
that hostname works on a remote cluster. Model inference needs sufficient local resources.
The client task `ClientAgent` and server activity `AgentTools` reference these three secrets through their
`provider.openaiCompatible.*` inputs. Changing secret values does not require editing those activities.
Changing provider type, business tools, or system instructions requires configuring the corresponding BPMN.

## Import and deploy

Use only the Basic profile. Do not import or deploy the OAuth profile alongside it; both profiles use the
same executable process IDs. The [numbered demo README](demo/README.md) is itself an importable raw Markdown
resource and contains the ordered manifest, exact labels, setup, and example request.

For this revised import, start with a fresh Modeler project when possible. Importing or renaming resources
does not remove the earlier standalone `a2a-card.bpmn`; do not deploy it alongside
`profiles/basic/02-a2a-server.bpmn`, which now contains discovery.

The complete import closure is 11 repository resources plus the pinned upstream server AI Agent Job Worker v5
template (12 import resources total): seven BPMN/DMN/form resources, three local element-template JSON files,
and the README. The client also requires Camunda AI Agent Task template
`io.camunda.connectors.agenticai.aiagent.v1@8`; `c8ctl element-template info` confirmed it in the configured
template catalog, so its JSON is not redistributed. Confirm that the target Modeler resolves this exact ID
and version before import. The local HTTP JSON v13 snapshot may be omitted only after confirming that the
target already provides that exact ID and version. Keep both custom server templates and the pinned upstream
AI Agent Job Worker v5 template. An "Already available" notice alone does not establish version equivalence.
Use the Modeler's element-template import workflow for the three local JSON files and the
[pinned upstream template](https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json).
The upstream template remains subject to its own terms; see [third-party notices](../../THIRD_PARTY_NOTICES.md).

Deploy these seven resources together: `profiles/basic/02-a2a-server.bpmn`,
`demo/03-server-agent-card-dispute.bpmn`, `demo/01-client-agent.bpmn`, the three forms under
`demo/04-client-agent-ask.form`, `demo/05-client-agent-confirm.form`, and
`demo/06-client-agent-result.form`, plus `demo/07-server-request-validation.dmn`. Do not deploy the README
or the template JSON files. The process IDs remain `a2a-rpc`, `a2a-card-dispute`, and `a2a-client`;
the protocol and discovery webhook starts are both in `a2a-rpc`.

For Desktop Modeler or Self-Managed Hub, keep the seven deployable resources together and install the
three local templates at their exact versions. Confirm that AI Agent Task v8 is available in the target
template catalog. Do not include archived diagrams, old copies, or both
authentication profiles in the deployment. Historical Desktop/Hub deployment reports below refer to
earlier resource sets; they do not prove this revised candidate's import or runtime.

No generator execution, protocol editing, custom worker, custom HTTP server, nginx route, or standard-path
ingress is required. Wait for healthy inbound registrations on both `CardRequested` and `RpcReceived` in
process `a2a-rpc`. Externally, `curl --fail "$A2A_AGENT_CARD_URL"` must return the card, and an
unauthenticated POST with a JSON body to `A2A_RPC_URL` must return 401, not 404. A 404 means the task
webhook is not yet registered. Use your deployment's trusted CA configuration; do not use `--insecure`.

## Run the demonstration

Start process `a2a-client` through its start form, or with a `question` variable:

```json
{
  "question": "Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool."
}
```

The `ClientAgent` task uses AI Agent Task v8 and chooses its own calls to `DiscoverAgentCard`,
`SendA2AMessage`, `GetA2ATask`, and, when needed, `AskClientForInput`. The parallel multi-instance
`ClientTools` ad-hoc subprocess executes tool requests and returns their results to the next model turn.
The client sends credentials only to the configured `A2A_RPC_URL`, not to an arbitrary URL returned by a card.
Discovery and A2A 1.0 JSON-RPC are explicit BPMN/HTTP behavior, not the stock A2A 0.3 client connector.

The expected reconciliation artifact contains merchant `Northwind Electronics`, currency `USD`, paid amount `99.9`,
expected amount `49.95`, overcharge `49.95`, and recommendation `REQUEST_HUMAN_REVIEW`. The server-side
deterministic tool accepts only a validated structured `syntheticClaim`; it does not accept model-generated
financial values. The client result form displays the observed server result for review. Review and complete
the final user task.

Free text is context, not confirmation. If the server responds `INPUT_REQUIRED`, the client agent can call
`AskClientForInput`, which presents a Tasklist user task using `05-client-agent-confirm.form`. Enter merchant
`Northwind Electronics`, currency `USD`, first/second charge amounts `49.95`, expected order amount `49.95`,
and check the synthetic-only confirmation. In the bundled client process, the outbound mapping derives the
`data.syntheticClaim` part only from that form result; the model cannot supply claim fields as tool arguments.
Follow-up messages reuse the task and context IDs returned by the initial send; the model cannot supply those
identifiers either. This is a prototype interaction: the model decides whether and when to call each tool.
Polling also uses the task ID returned by the initial send rather than an AI-supplied identifier.

External clients may submit this structured confirmation on the initial request for one-shot completion,
or on a follow-up with the original `taskId` and `contextId`:

```json
{"data":{"syntheticClaim":{"merchant":"Northwind Electronics","currency":"USD","chargeAmounts":[49.95,49.95],"expectedAmount":49.95,"syntheticOnly":true}}}
```

Confirmation is validated afresh from the **current message only**: one data part, nonempty string
merchant/currency, exactly two finite nonnegative numeric charge amounts, finite nonnegative expected
amount, and boolean `syntheticOnly=true`. Strings, booleans or null are not coerced into amounts.
Missing, partial, malformed or duplicate confirmation returns INPUT_REQUIRED with no reconciliation artifact.
Nonfinite tokens such as NaN/Infinity are not valid JSON and must be rejected, not treated as amounts.
Fields are not merged from older messages, another task or the model conversation. The no-argument
reconciliation tool uses only this validated client object, never model-supplied financial arguments.
The final publication guard also checks the tool result against those confirmed values.
This confirms what the client explicitly supplied; it does not authenticate real-world financial facts.

An external client can fetch the complete `A2A_AGENT_CARD_URL` and send A2A 1.0 `SendMessage` requests to the card's
JSON-RPC interface using `X-A2A-Api-Key`. `GetTask` polls the returned task ID. Missing and invalid keys must be
rejected without business work. Standard `/.well-known/agent-card.json` discovery requires an optional route to the
direct discovery webhook; it has not been independently verified for this candidate.

For a minimal external check, set `A2A_RPC_URL`, `A2A_AGENT_CARD_URL` and `A2A_API_KEY` in your local shell
without committing their values or including them in screenshots. These shell variables do not configure connector
secrets automatically. The examples below require Bash and curl and send synthetic data only.
For a normally resolvable endpoint with a trusted certificate, initialize:

```bash
A2A_CURL_ARGS=()
```

For a Docker Desktop **local validation lab only**, `host.docker.internal` may resolve inside containers
but not on the host. Keep that advertised hostname and its certificate SAN consistent for both clients.
Set `A2A_CA_FILE` to the lab CA certificate and `A2A_CONNECTORS_PORT` to the actual published loopback port,
then use this client-scoped mapping instead:

```bash
A2A_CURL_ARGS=(--cacert "$A2A_CA_FILE" --resolve "host.docker.internal:${A2A_CONNECTORS_PORT}:127.0.0.1")
```

This affects only these curl requests, not system DNS or other clients. The certificate must include
`host.docker.internal`; curl still verifies hostname and CA trust. The Connectors Java client must trust
the same CA and resolve the advertised host normally on its Docker network. Do not use this loopback mapping
for remote clusters or production: supply real DNS and an appropriately trusted certificate there.

```bash
curl --fail "${A2A_CURL_ARGS[@]}" "$A2A_AGENT_CARD_URL"
curl --fail "${A2A_CURL_ARGS[@]}" "$A2A_RPC_URL" \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -H "X-A2A-Api-Key: $A2A_API_KEY" \
  --data '{"jsonrpc":"2.0","id":"demo-send","method":"SendMessage","params":{"message":{"messageId":"demo-request-1","role":"ROLE_USER","parts":[{"text":"Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. The expected charge was USD 49.95. Reconcile the two charges with your tool."},{"data":{"syntheticClaim":{"merchant":"Northwind Electronics","currency":"USD","chargeAmounts":[49.95,49.95],"expectedAmount":49.95,"syntheticOnly":true}}}]}}}'
```

Read `result.task.id` from the response, set `TASK_ID` to that value and poll:

```bash
curl --fail "${A2A_CURL_ARGS[@]}" "$A2A_RPC_URL" \
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
When supplying this or any other connector secret through environment variables, restart or recreate
Connectors after changing the value so the runtime loads it.
To try echo, download/import that linked BPMN separately, deploy it alongside the unchanged Basic protocol and
validation DMN, and set connector secret `A2A_AGENT_PROCESS=a2a-echo`. Echo uses only the shared `a2a-task-update`
process from the protocol: it needs no model, form or classification DMN. It is not in the default import manifest.
In `profiles/basic/02-a2a-server.bpmn`, select start event `CardRequested` and edit the
`inbound.responseExpression` property to update `body.name`, `body.description` and `body.skills`
(IDs, names, descriptions, tags and examples). Keep the complete endpoint URL, API-key scheme and
disabled-capability declarations. Discovery is part of process `a2a-rpc`; there is no separate card process.

The default outcome returns a Task. A business process can explicitly set `outcome.responseMode="message"` for a
completed text-only reply. The protocol returns `result.message` only when the task is completed, has an agent status
message and has no artifacts; all other outcomes still return `result.task`. The stored completed task remains
available through the returned message's `taskId`. The internal response-mode field is omitted from Task views.
The protocol never chooses this mode from a client message ID or request content. The supplied real-agent demo
keeps the default Task response so its reconciliation artifact is not discarded.

The agent joins text parts with spaces into `promptText` and maps `data.userPrompt.prompt =promptText`.
Do not JSON-string-encode the text: stock Connectors 8.9.17 passes that encoding literally to the model.
The input mapping evaluates FEEL on the engine, but its resulting user text is data, not another FEEL expression.
The runtime checks compare actual model-conversation input with numeric-leading, quoted, backslash,
newline, control-character and leading-equals request text. Multipart text still uses the documented space join.
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

A missing hook or no remaining matching subscription permits at most three correlation attempts with
0.3-second retry waits. Whether correlation reports success or no matching subscription, the protocol then
reconciles indexed state for up to five seconds. A visible canceled revision returns that persisted outcome,
even if the correlation response reported no match. Otherwise, a confirmed no-match with readable noncanceled
state returns `-32002`. No canceled state is written by the protocol. Missing state, or an accepted cancellation
whose terminal revision remains invisible, returns internal error `-32603` with `DEADLINE_EXCEEDED`.
A missing hook on an active task therefore incurs the full five-second reconciliation window, in addition
to the correlation attempts and connector latency, before returning `-32002`.

The correlation connector job has **one attempt** for transport/API failures: it does not automatically retry
an ambiguous write after a lost response. Such failures remain actionable incidents, not a fabricated canceled
result or `-32002`. The explicit three-attempt loop applies only to definite correlation-not-found responses.
After an uncertain transport failure, inspect the failed execution and poll `GetTask` rather than assuming
whether cancellation occurred.
This connector is shared with follow-up `SendMessage`: its transport/API failures also exhaust the single
attempt and create an incident without an RPC response, so the caller can time out. Inspect the incident and
poll the task before retrying; do not assume that a missing response means the follow-up was not delivered.

## Operational boundary and remaining gates

The API key establishes one shared trust boundary, not per-user task authorization. Possession of the key permits
operations on this agent's tasks. Engine permissions and secret distribution must match that boundary.
Task search uses the selected agent process; existing-task lookups have a three-second indexing/variable window.
`ListTasks` collects engine pages of 100 process instances and their complete root-variable batches before
applying A2A filters, sorting and pagination. Equal status timestamps are ordered by task ID descending.
Missing root state is retried at 0.25-second intervals within a ten-second scan budget; an incomplete collection
returns `-32603 / DEADLINE_EXCEEDED`, never a partial successful list. Missing/repeated engine cursors or overlapping
pages return `-32603 / DATA_LOSS`. The budget is checked between engine calls; each connector call retains its
own connection/read timeouts. Large or slow collections can fail explicitly rather than silently truncating.
Search reads the live index, not a transactionally frozen snapshot across separate A2A page requests.
The native pagination evidence covers **context-filtered listing of 125 tasks only**; no unfiltered capacity
ceiling has been measured. Only the context tag is pushed into the engine query. Status and timestamp filters
are applied after collection, so without a context filter every retained instance of the selected agent process
must be scanned. Retention is disabled in the reference stack. As history grows, an unfiltered scan can
consistently exceed the ten-second budget even when the requested page is small. This is not an unlimited
listing or production-capacity claim. A production deployment would need separately validated history cleanup
or retention and completed-task availability policies; neither is established by these non-production checks.
Push, streaming and A2A 0.3 interoperability are not advertised.
Task requests must select the advertised `A2A-Version: 1.0`. Numeric patches such as `1.0.2` use the same
semantics; other Major.Minor versions are rejected with `VERSION_NOT_SUPPORTED`.
Missing or empty version headers default to unsupported 0.3 and receive that error rather than silently selecting 1.0.
The supplied client uses 1.0. Shipped examples do not request additional client credentials during a task;
business-input clarification is not an in-task authorization flow.
Repeating a new-task submission with the same `messageId` creates independent tasks. There is no message-ID
side-effect deduplication or idempotency guarantee; the business process owns any required side-effect protection.
If `SendMessage` fails with a transport error or HTTP 409 `ABORTED`, business work may already have started.
Inspect the original incident/request and persisted task state before retrying the job or submitting again.
Do not blindly retry financial work: one observed internal connection closure left the client failed while
its agent task had reached input-required. A later successful request does not recover that original client.

The source-specific checkpoints above distinguish functional prototype evidence from deferred release approval.
The selected editor/form flows have functional evidence on that historical runtime, not the current 8.9 pair; human usability and
fresh-adopter timing are not prototype criteria. The actual8.8.21 clarification heading displayed readable
literal backslash-n separators, not a polished-layout pass. Unknown historical tool versions remain unknown.
Actual Marketplace import and external legal/eligibility approval remain deferred.
The recorded MUST-gate and SDK results apply only to their exact source and deployment settings, not
subsequent changes. Do not infer exactly-once
side effects or a retention guarantee. Engine/connector incidents are operator-visible failures, not successful
business outcomes.

### Recover authentication, permission and provider failures

If the engine is unavailable, inspect Connectors activity/worker diagnostics and restore engine connectivity
before retrying a business submission. The isolated outage check observed HTTP 503/UNAVAILABLE while the engine
was stopped; this is not a guarantee of the HTTP response for every outage. After recovery, poll GetTask for an
existing task before starting replacement work. Correlation transport incidents may leave an INPUT_REQUIRED
task unchanged: restore the failed route/configuration, retry the original job and inspect the persisted task
outcome. Do not equate a client timeout with business failure or resubmit side effects without checking state.

If a protocol REST connector exhausts retries, inspect its incident and the affected task before resubmitting
an A2A request. For `CreateTask`, the shipped setting is three attempts with a 30-second retry backoff and
20-second connection/read timeouts. The client can time out before an incident appears. A timeout does not
prove that a command did not execute. Duplicate submissions create independent tasks, not deduplicated retries.

For engine HTTP 401, correct `ENGINE_USERNAME`/`ENGINE_PASSWORD` in the runtime's secret provider.
The environment-secret check recreates only its owned Connectors container to load the corrected secret.
For HTTP 403, inspect the actual engine user's resource authorizations. Starting business work needs
`CREATE_PROCESS_INSTANCE` on its `PROCESS_DEFINITION`; lookup, variable access and correlation require their
own authorizations. A visible role assignment alone did not authorize the broker command in the recorded
repair attempt. The passing check uses **built-in `admin` membership plus an explicit user authorization** for
the selected business process. Its success cannot attribute recovery to the single explicit permission.
A minimal permission set for `ENGINE_USERNAME` is **untested and undocumented**; the broad built-in role is
a disposable-test convenience, not least-privilege advice.

After correcting the deployment, restore the failed job's retries and resolve its incident if it remains active.
The recorded 8.8 flow uses `PATCH /v2/jobs/{jobKey}` with `{"changeset":{"retries":1}}`, then
`POST /v2/incidents/{incidentKey}/resolution`. A retry can already resolve the incident; confirm its final state.
Poll the original task or inspect the original handler's recorded response before starting new work.
Both deployment-level checks observe the original request's exact completed result and a fresh external request.
Only the caller's explicit five-second timeout was observed during each fault. The eventual webhook-side HTTP
response after that deadline is **unobserved**; no server-generated timeout status is established by this check.

The additional connector-input fixtures use one attempt and one-second timeouts, start handlers through the
engine API, and repair local connector variables. They prove job-level diagnostics and repair, not webhook
responses or deployment-secret replacement. Their unreachable URL leaves the engine running: it is not an
engine-outage or restart check. The provider fixtures also start handlers through the engine API and poll over
A2A; provider errors produce `TASK_STATE_FAILED`, explicit failure text and no reconciliation artifact.
Correcting the model configuration permits a new task to complete with exact arithmetic evidence.
Basic credentials have no token-expiry mechanism; the password-rotation check is not OAuth-expiry evidence.
The OAuth profile remains nonshipping and unverified.

The original experiments, fixture diagrams, conformance patches and old generated templates/icons are nonshipping
verification or historical material. They are not part of the Modeler import set above.
Despite their location under `blueprint/`, `docker-compose.yml`, `proxy/nginx.conf`, `smoke.py` and `smoke.sh`
are historical unauthenticated experiment tooling, not this Basic prototype's installation path.
Likewise, `../scripts/deploy.sh` and `../scripts/c8run-demo.sh` deploy historical resources, not the selected
import set. Trace, coverage and token scripts are contributor diagnostics, not included runtime assets.
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
and six actual model-input character cases,
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
It also negotiates patch-varied copies of the discovered card against the same live endpoint. The report
records every SDK request version. `bpmn-client-versions.json` separately records engine-evaluated packaged
card mapping and native received headers from the supplied send and polling connectors.

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

`PROOF_AGENT_PROCESS=a2a-echo PROOF_LISTING_CHECKS=1 python3 experiment-3/tests/runtime/verify.py`
submits 125 exact echo tasks with eight callers, then compares every field across four A2A pages of 37/37/37/14
tasks. It also checks unique IDs, deterministic ordering, status/timestamp filters and total size.
`listing-checks.json` records the result. Combine `PROOF_LISTING_CHECKS=1` with the operational flag above to
exercise both against one owned runtime; neither flag is used by adopters.

`PROOF_AGENT_PROCESS=a2a-echo PROOF_FAILURE_CHECKS=1 python3 experiment-3/tests/runtime/verify.py`
checks the deployment-secret and actual-user permission runbooks above, derived connector-input faults,
password revocation, provider failure and real-model recovery. It temporarily recreates only its own Connectors
container, creates and removes an isolated engine user, and writes `failure-checks.json`.
Unlike the other echo checks, this flag requires the documented local model.
It can be combined with the operational and listing flags. Derived diagrams are nonshipping test artifacts.

`PROOF_AGENT_PROCESS=a2a-echo PROOF_FAILURE_GAP_CHECKS=1 python3 experiment-3/tests/runtime/verify.py`
checks a true outage of only the verifier's owned engine during an external GetTask call, plus refused
follow-up and cancellation correlation transport on derived nonshipping protocol copies. Correlation copies
change only the URL, retaining the shipped single attempt and 20-second connector timeouts. The check observes
bounded client errors/timeouts, operator diagnostics/incidents, unchanged business state before repair and exact
results after recovery. `failure-gap-checks.json` and `engine-outage-connectors.log` record observations.
It does not inject native response loss after commit, OAuth expiry, optional ingress or push callbacks.
No other deployment is stopped or reconfigured. These checks are not passes until the exact-source run completes.

`python3 experiment-3/tools/build_blueprint.py --check` checks the committed candidate assets against their builder,
using immutable upstream template URLs. `python3 experiment-3/tools/build_core.py --check` checks both protocol profiles.
`python3 experiment-3/tools/check_resources.py` checks the selected import set for template-version, form, decision
and process reference closure. Add `--ref <full-public-commit-SHA>` to print the 12 immutable resource URLs.
None of these commands changes an adopter's deployment. A successful runtime check is not a conformance or Modeler-import pass.
