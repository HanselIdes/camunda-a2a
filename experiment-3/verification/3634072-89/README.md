# Same-minor patch validation and literal-input repair

**Overall: FAIL; do not treat this candidate as accepted or release-ready.**
Discovery/execution: October 27, 2026. All tests are synthetic, local Self-Managed checks,
not SaaS, actual UI completion, production readiness, or adoption-time evidence.
No new runtime behavior beyond literal-input handling was authorized or changed.

| Source | Disposition |
| --- | --- |
| `de16278b8f5cc401404a524e910055ae545f6768` | Unchanged public-source tests: 8.8 synchronous-response failure; 8.9 encoded-input failure and separate protocol/SDK/TCK passes. |
| `363407202ff641ee666b92ba74162de56a40fb83` | Plain-text prompt mapping, 8.9 minimum/defaults and six model-input checks; real run FAILS missing-input semantics; scoped TCK passes. |
| `91cf7a57e2adfa6e522756319c6381a6c8798de4` | Capture-only harness/test improvement. Shipped resource bytes identical to 3634072. Fresh diagnostic confirms six input equalities PASS, semantic/overall FAIL. |

These are local immutable commits, not a claim that the repaired source was pushed.
An evidence/docs commit does not change the pinned execution source.

## Required component versions

Engine and Connectors publish independent patch schedules. The selected pairs use the latest
stable patch of each component **within the same minor**, not identical patch numbers.
[discovery.json](discovery.json) retains authoritative release URLs, publication times, registry
responses and unavailable equal-number alternatives; those alternatives were not substituted.
[image-manifests.json](image-manifests.json) records official index, Linux ARM64 manifest and config digests.
Each attempt additionally records actual container image IDs and repository digests.
Docker's reported image ID may be an index digest; it is not mislabeled as the platform config.

| Required component | 8.8 attempt | Every 8.9 attempt |
| --- | --- | --- |
| Engine / deployment REST API | 8.8.44 | 8.9.26 |
| Stock Connectors | 8.8.24 | 8.9.17 |
| Secondary storage | Elasticsearch 8.17.0 | Elasticsearch 8.19.23 |
| Modeler | N/A: no editor used | N/A: no editor used |
| Deployment mechanism | Engine REST API `/v2/deployments` | Engine REST API `/v2/deployments` |

[required-component-versions.json](required-component-versions.json) attributes these requirements
per attempt, without substituting unrelated host/tool patch versions for required component versions.
All required component versions are known for these new attempts. This does not fill earlier
historical version gaps; their original failures and unknowns remain in their original evidence.

The [8.8 supported environments](https://docs.camunda.io/docs/8.8/reference/supported-environments/)
require Elasticsearch 8.16+; [8.9](https://docs.camunda.io/docs/8.9/reference/supported-environments/)
requires 8.19+. Elasticsearch
[8.19.23](https://github.com/elastic/elasticsearch/releases/tag/v8.19.23) was published October 6, 2026.
Official ARM64 image availability is not a vendor-supported-platform claim.
Ollama 0.40.3 and `qwen3-coder-30b-64k:latest`, model digest
`13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253`, were observed,
not inferred for older runs. Attempt-specific Docker/Compose/Python/curl/model metadata is retained.

## Executed attempts

| Directory | Actual result |
| --- | --- |
| `matched-88-real-1` | FAIL. Deployment 200; engine authentication 401/200; missing/invalid task keys 401; authenticated SendMessage 200 with empty body. A process started; eventual business outcome unobserved before cleanup. No retry. |
| `matched-89-real-1` | Exact nine-field reconciliation, same-task numeric-leading follow-up/history4, direct card, supplied BPMN client through review/completion via REST, and client header/version/polling checks PASS. Original native verbatim assertion FAILS because surrounding JSON quotes reach model input. |
| `matched-89-core-1` | PASS: auth rejection for 11 methods, 12 known/unknown-resource checks, no unauthorized business starts, version negotiation, 44 terminal/race cases, 125 context-filtered listing tasks on four pages, persisted-credential exclusion. |
| `matched-89-external-1` | Failed supplemental readiness GET: TLS EOF before SendMessage. Original provenance remains RUNNING because the supplemental harness did not finalize it; console records the failure. Not a behavioral pass. |
| `matched-89-external-2` | Only safe GET readiness retries changed. Exact guide card/send/get Bash and nine result fields, independent a2a-sdk1.2.3 discovery/follow-up/get/context-list/patch-version checks, credential exclusion PASS. Does not waive native failure. |
| `matched-89-tck-1` | Scoped TCK PASS: 68 executed, 167 skipped, 0 failures/errors, 56 MUST passes, 58 reasoned exclusions, 0 incidents. |
| `matched-89-quoting-1` | Four unchanged-source diagnostics complete: original request preserved, JSON-encoded model text non-verbatim in every case. Not acceptance. |
| `repaired89-real-1` | Original numeric-leading assertion and first five new equality cases PASS. Bare leading-equals JSON completes using invented fields; new INPUT_REQUIRED assertion FAILS before its context is captured. Original failed task/output retained. |
| `repaired89-tck-1` | Same scoped TCK PASS on clean 3634072: 68 executed, 167 skipped, 0 failures/errors, 56 MUST passes, 58 exclusions, 0 incidents. |
| `repaired89-real-2` | Clean 91cf7a5 capture-only rerun: all six actual model-input equalities PASS; bare JSON semantic assertion FAILS again. Original request, model conversation/tool arguments/result and returned task captured before assertion. |

Both repaired real runs first pass exact reconciliation, same-task follow-up/history4, truthful
direct HTTPS card, supplied BPMN client result-review/completion through REST, and client checks.
They stop at the retained semantic assertion. Therefore the downstream auth matrix, independent SDK
and exact-guide tail are **not executed on the repaired candidate**. Their earlier de16278 results
remain separate, not recast as current-source evidence. The 44-case/125-task suites were not rerun
on the repaired source. Maven/CPT, load/restart studies, actual form UI, Desktop/Hub and SaaS were not rerun.

The original external guide task was initially COMPLETED and fetched once with GetTask: persisted
lookup, not a working-state polling transition. It uses the documented client-scoped validation CA
and `--resolve`, with hostname verification intact. No shared DNS change or TLS bypass.
The native log's generic "authenticated echo" label also appears in real-model mode; deployed assets,
source mode and exact arithmetic artifact distinguish it from echo.

## Precise failures

### 8.8: synchronous webhook results are unavailable

The unchanged Basic blueprint requires `synchronousResponse=true` and
`correlation.variables.rpcResponse`. Exact Connectors
[8.8.24 source](https://github.com/camunda/connectors/tree/c56eb981a05bb829f8ff2d505eede80ce390cf13)
starts a process with `.send().join()`, without the required synchronous completed-result path.
Authenticated SendMessage returns empty HTTP200, causing the native TypeError.
Connector logs confirm process `2251799813685351` started. Immediate indexed searches being empty
does not prove no work happened. No blind resend; later 8.9 success cannot establish 8.8 support.

### 8.9 before repair: reversible encoding changes actual model text

The `EncodePrompt` script creates JSON-string `jsonPrompt`. Quotes acquire backslashes and outer
quotes; literal backslashes double; actual LF becomes literal `\u000a`; TAB/CR/BS/FF/U+0001 become
literal escape sequences. All four diagnostic requests reach INPUT_REQUIRED.
Original request text is unchanged. Decoding stored text can reconstruct it, but the model path
does not decode it. The model sees different codepoints, which can alter meaning, not just presentation.
The captured connector conversation is not an intercepted provider HTTP payload.

Exact Connectors 8.9.17
[AgentMessagesHandlerImpl](https://github.com/camunda/connectors/blob/81f90be6ba9c35d1cac14427761434393042c53b/connectors/agentic-ai/src/main/java/io/camunda/connector/agenticai/aiagent/agent/AgentMessagesHandlerImpl.java)
passes `userPrompt.prompt()` directly into text content;
[ContentConverterImpl](https://github.com/camunda/connectors/blob/81f90be6ba9c35d1cac14427761434393042c53b/connectors/agentic-ai/src/main/java/io/camunda/connector/agenticai/aiagent/framework/langchain4j/ContentConverterImpl.java)
passes text unchanged into LangChain4j.
[JobHandlerContext](https://github.com/camunda/connectors/blob/81f90be6ba9c35d1cac14427761434393042c53b/connector-runtime/connector-runtime-core/src/main/java/io/camunda/connector/runtime/core/outbound/JobHandlerContext.java)
binds already engine-evaluated variables. No legacy JSON decode belongs in this observed path.
The repaired agent uses the existing multipart space join into `promptText`, mapped directly.
Numeric-leading follow-up plus numeric/quote/backslash/LF/all32C0+DEL/leading-equals inputs are exact
in the recorded actual model conversation.

### Remaining material failure: missing-input grounding

For case6, submitted request and actual model text are both exactly `={"synthetic":true}`.
The existing, unchanged `SYSTEM` in
[`build_blueprint.py`](../../tools/build_blueprint.py) says merchant, currency, two charge amounts
and expected amount are required; if any are missing, call no tool and reply `NEED_INPUT:`.
This is not merely a newly invented test expectation.

In both fresh repaired runs the model instead calls `review_duplicate_charge` with invented
`Acme Store`, `USD`, first/second/expected amounts `29.99`. In the second captured conversation
it asks for those details in prose **while simultaneously calling the tool**.
The tool returns paid59.98, overcharge29.99, syntheticOnly=true; the demo publishes COMPLETED.
The state assertion remains enforced; the full second chain is in
[literal-model-inputs.json](repaired89-real-2/literal-model-inputs.json):
`literalInputVerdict=PASS`, `semanticVerdict=FAIL`, `verdict=FAIL`.

The existing mechanical outcome guard requires a real named tool-result record and
`syntheticOnly=true`. Those conditions pass: this is not fabricated arithmetic outside the tool,
but invented inputs accepted by the tool. That guard does not establish input provenance/completeness.
No refund, financial service call or real dispute decision occurs, but the missing-input behavior
is materially wrong. A deterministic completeness/grounding check of required business fields is
the bounded repair direction; prompt-only assurances or a broad model replacement are insufficient.
No such behavior change has been made or waived.

## Assets, scope and cleanup

[asset-inventory.json](asset-inventory.json) records exact source blobs/SHA256s and prior
dispositions. The six changed selected resources are agent/card/client BPMN, Basic protocol metadata,
and two custom A2A templates. The controlled-agent test fixture mirrors the prompt repair;
other fixture/echo/OAuth changes are metadata only, not new support.
Eleven repository imports plus the pinned upstream AI Agent template remain the full12 closure;
upstream raw readback was HTTP200 with the recorded hash.
Proposed SaaS/Web URL import omits only stock REST and AI JSON, leaving10 imports and exact-version
registry prerequisites (HttpJson@12, AI Agent@5). It is not a verified SaaS import.
No standard template asset was deleted, no archival script became supported, and legal notices are unchanged.

The 34 current Python harness tests pass, including rejection of encoded input and a test proving
semantic failure is recorded and still raises. Both generators match their committed outputs;
12-resource closure and changed packaged BPMN lint pass. These are not substitutes for failed runtime semantics.

Ten sequential uniquely owned stacks used fresh storage/secrets, Basic engine auth/authorizations,
shared task API key and verified direct TLS. Storage/engine/Connectors caps are1536/2560/1024MiB;
connector heap512MiB. Four threads, active-version polling disabled, exporter bulk delay1s.
No ambiguous SendMessage retry, shared process kill, pruning, profile edit or DNS change.
[final-owned-cleanup.json](final-owned-cleanup.json) confirms all20 owned ports closed and no owned
containers/networks/volumes; the two pre-existing secondary containers remain running.
Image cache remains. Earlier404/409 failed chains stay in their historical checkpoints.

[sanitization.json](sanitization.json) records selected input/output hashes and transformations.
Absolute account paths and literal auth headers are sanitized; no profiles/screenshots/private planning
are copied. Full originals remain private. Runtime logs are selected diagnostic anchors, not complete logs.
`nonshipping-harness/` contains diagnostic infrastructure only, not installation assets or supported servers.
`SHA256SUMS` records the resulting evidence. No push, main/PR-state change, merge, or Marketplace action.
