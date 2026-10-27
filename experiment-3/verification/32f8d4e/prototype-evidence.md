# Prototype evidence integration

Inventory source: `32f8d4e451b36ec35ee6fa0f03880b6d893205dc`. This is a documentation audit,
not a new test execution. The only declared runtime combination is authenticated Self-Managed
**engine 8.8.21 / stock Connectors 8.9.0 / Elasticsearch 8.17.0**, Basic, push disabled,
direct HTTPS, local model. Other runtime combinations below are historical attempts, not advertised support.
Informed-agent functional checks are allowed. There is no adoption-time or human-usability acceptance claim.
Later evidence integrations below retain original execution pins. The
[actual Hub/Tasklist report](../a323e19/README.md) establishes the previously missing visual form journey;
the exact-version record for every historical attempt remains incomplete.

## Attempted combinations and exact-version gaps

`Unknown` means not recorded in the cited evidence, not an inferred default. A deployment method
is not a separately versioned product: record its tool version as unknown when absent.

| Attempt and original source | Engine / Connectors / storage | Editor and deployment | Recorded result and limits |
| --- | --- | --- | --- |
| Native reference, `d4e6273c862b387ee7b2a49b992cd4db5f56a922` | 8.8.21 / 8.9.0 / Elasticsearch 8.17.0; image IDs/digests in [native provenance](../d4e6273/native-provenance.json) | No Modeler used; Python verifier, Docker Compose, engine REST deployment. Python/Docker/Compose exact versions unknown. | Native auth/version, terminal/listing/failure checks, real model/BPMN client/SDK, three scoped TCK repeats and two-agent workload/restarts passed. Not editor or visual form completion. |
| Native outage/transport supplement, `07b33876396bfcb8c0dfa58336dd1bd2cfd0b640` | 8.8.21 / 8.9.0 / Elasticsearch 8.17.0; [image digests](../07b3387/runtime-provenance.json) | No Modeler used; Python verifier/Compose/REST, exact tool versions unknown. | Three native gap cases passed; [failed harness attempt](../07b3387/failed-attempt-runtime-provenance.json) at d7290ae retained. Packaged assets unchanged from d4e6273. |
| Earlier 8.8 checkpoints, 96357f5 / 0bc60d4 / f09fe52 / a45de8c / e4dd045 / bc0a693 | Same 8.8.21 / 8.9.0 / Elasticsearch 8.17.0; each directory retains its own full source pin/provenance | No Modeler used; isolated native Compose/REST; exact tool versions unknown. | Historical scopes only: do not transfer their PASS to changed source. Cancellation defect at 0bc60d4 and QName failure at b7e3dfb remain failures. |
| 8.9 matrix, `0bc60d4b57697284f0ef8bbf4c039db65bf4b118` | 8.9.5 / 8.9.0 / Elasticsearch 8.17.0; [provenance/digests](../0bc60d4/89-runtime-provenance.json) | No Modeler used; isolated Compose/REST, exact tool versions unknown. | Native/real-model/BPMN client/SDK passed on that older source. No final-source terminal/failure/conformance series for this combination; not advertised. |
| 8.10 native matrix, same 0bc60d4 source | 8.10.2 / 8.10.0 / Elasticsearch 8.17.0 configured by that source's runtime Compose; [failed provenance](../0bc60d4/810-failed-runtime-provenance.json) has no captured image digests | No Modeler used; isolated Compose/REST, exact tool versions unknown. | Real-agent result FAILED without expected reconciliation; SDK unrun. Not supported by the successful Maven suite. |
| Maven process/integration suite, d4e6273 | Configured engine 8.10.2 / Connectors 8.10.0 for integration tests; Camunda Process Test 8.10.4. Storage product/version and runtime image digests not recorded in [suite report](../d4e6273/full-suite-checks.json). | No Modeler used; `mvn -q clean test` in tests directory. Exact Maven/JDK patch versions unknown. | 190 tests/19 suites, zero failures/errors/skips/reruns. Mix of engine-backed Harness adapters, mocked business/model jobs and stock-connector integration; not a native 8.10 candidate profile pass. |
| Optional SaaS attempt, source not pinned in public report | Reported engine 8.8.44 / Connectors 8.8.24; managed storage/version unknown | Modeler/deployment tool versions unknown; [historical disclosure](../../README.md#candidate-validation-profiles-not-a-release) only | Secret registration unavailable and webhook 403, including valid key; blocked/unverified, not advertised. Exact source/provenance gap remains. |
| Functional adaptation diagnostic, `597b1524d58a41db9d7465d523073bce0fd9223e` | Reported 8.8.21 / 8.9.0 / Elasticsearch 8.17.0; tags, no captured image digests | No Modeler used; Docker Desktop/macOS and REST, exact Docker/Desktop/macOS versions unknown | [Transcribed informed-agent run](../597b152/adoption.md), not a fresh adopter or timing criterion. Derived raw-XML process had no BPMNDI. |
| Desktop import/render/preview/save-reopen, `b6b1baf55fe32e5ff0f961e6dab6c99b966cbe3c` | No target deployment submitted; engine/Connectors/storage not established by this check | Camunda Modeler **5.51.1**, macOS version unknown; actual installed Electron app via CDP | [Integrated report](desktop-modeler-5.51.1.json) covers pinned imports, template property persistence, required-field form preview and save/reopen only. Auto-discovered local engine warning says 8.10, not an exact engine patch or authorized deployment target. Playground exposes schema 19 internally; actual getXML output and saved copies retain schema 18 for all three unchanged forms. Saved copies not runtime-tested. |
| Desktop deployment and external continuation, runtime source 841468e; exact guide source `a994f22f03ae5e6a90155607ebadbf8ce97338bb` | 8.8.21 / 8.9.0 / Elasticsearch8.17.0, current image digests captured | Desktop5.51.1 on macOS26.7.1/Electron43.0.0/Chromium150.0.7871.46; actual process-application UI deployment; Docker29.9.2, Compose5.6.1, Python3.9.6, local Ollama0.40.3; exact curl version in provenance | [Native external result and Desktop deployment](../a994f22/README.md) PASS within scope. Hub v1/ Desktop v2 coexist; v2 client omits final newline, seven other process XMLs/DMN exact. No form-UI acceptance. Current tool observations cannot fill older unknown versions. |
| Self-Managed Hub editor and actual Tasklist journey, assets b6b1baf | Owned engine8.8.21 / Connectors8.9.0 / Elasticsearch8.17.0; editor PostgreSQL14.24-alpine | Hub `1.0-SNAPSHOT`, full source `e1fa2b8cec1a8d402c3a47005ede5d954d26320f`; Temurin25.0.5+8-LTS/Maven3.10.0/Node24.22.1/npm12.2.1; dependency versions/digests in [integrated report](../a323e19/hub-validation-current.json) | Actual import/configure/save-reload/deploy and distinct fresh ask/answer/result Tasklist journey PASS; prior404/409 failures retained. WebSockets build only SNAPSHOT+digest known. No human-usability claim; literal backslash-n heading limitation disclosed. |
| Archived quickstart/c8run configuration, not a candidate attempt report | Compose declares 8.10.2 / 8.10.0 / H2 RDBMS (H2 version unknown); c8run script defaults 8.10.2, bundled Connectors/storage versions unknown | No candidate Modeler/deployment report | Configuration values are not observed execution evidence. Historical scripts/proxy disable auth or use other skills; excluded from the selected Basic prototype. |

The model pin for the native reference is local Ollama `qwen3-coder-30b-64k:latest`,
digest `13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253`.
Exact Ollama server version is unknown. SDK is `a2a-sdk==1.2.3`.
The TCK pin is `263b9cfaf16a554bdfb166a7ba5b67716e946349`, patched-source SHA-256
`8fd33aea1814e32723545d3725af254505bf990363c355679f9f779de7aed74a`.
Unknown deployment/editor versions prevent claiming a fully observed version matrix.

## Outcome-to-evidence map

These are local evidence IDs, not copied acceptance text. PASS is scoped to the cited source and runtime.
PARTIAL/GAP rows cannot become passes because an unrelated unit test or editor preview succeeded.

| ID / promised outcome | Relevant evidence | Disposition and remaining gap |
| --- | --- | --- |
| SETUP: documented setup and exact external response | [Editor-deployed external setup](../a994f22/README.md), exact-guide commands/assertions at a994f22; [Hub steps/deviations](../a323e19/README.md#setup-record-and-deviations) | External-call portion PASS on declared runtime, all nine result fields. Prerequisites/settings/editor workflow and adaptations recorded, including workspace template publication/Flyway dev reset. Original841468e run retains deviation; guide commands at a994f22 include lab CA/DNS. No timing threshold or turnkey Hub-install claim. |
| CONTRACT: select a different deterministic process without protocol edits/workers | Diagnostic's word-count follow-up/cancel cases; [native terminal checks](../d4e6273/native-terminal-checks.json) on controlled fixture | Functional adaptation observed. Raw-XML diagnostic fixture is nonshipping, lacked diagram layout and was not Modeler-authored. |
| AGENT: exact real-model arithmetic and same-task clarification | [SDK report](../d4e6273/sdk-real-model-sdk.json), [series sdk-real-model stage](../d4e6273/series-provenance.json), `verify.py` assertions at d4e6273 | Native PASS, not just HTTP success. Exact artifact, verbatim numeric-leading follow-up, four-message history. No SaaS/Camunda-provided-model pass. |
| DISCOVERY: truthful direct HTTPS URL/skills/auth and useful client context | [Client expression/header report](../d4e6273/sdk-real-model-bpmn-client-versions.json), SDK explicit discovery, native stage | Native PASS: direct connector URLs, explicit card fetch, received 1.0 headers and patch-varied expressions. TCK has scoped hostname/path adaptations, not standard-path ingress proof. |
| EDITORS: import/configure/deploy and complete all forms | [Desktop deployment](../a994f22/desktop-modeler-5.51.1.json), [actual Hub/Tasklist](../a323e19/README.md) | Selected-original-asset flows PASS on declared runtime: Desktop/Hub import/configure/deploy; actual Tasklist ask/answer/result UI and unique client completion. Desktop seven XMLs/DMN exact, client final newline omitted. Edited/serialized roundtrip copies not runtime-tested; no blanket editor-version or polished-layout claim. |
| VERSIONS: every advertised combination | Version table above; [asset hashes](asset-inventory.json) | Reference native combination only. 8.9 historical, 8.10 native failed, SaaS blocked. Exact editor/deployment/storage unknowns remain explicit, not broad 8.8+ support. |
| CONFORMANCE: applicable declared-profile mandatory requirements | [114-MUST audit](../d4e6273/combined-mandatory-audit.json), [16 supplemental dispositions](../d4e6273/requirement-dispositions.json), three `tck-*-gate.json` reports | PASS for recorded Basic profile: 56 TCK, eight supplemental, 50 inactive/other-binding. Exclusions are not passes; not full A2A conformance. |
| CLIENTS: independent SDK and supplied BPMN client | SDK, client-version and series reports above | Native PASS: SDK discovery/send/poll/list/clarification and client-to-real-agent result, with user task completed through engine REST. Polling task copied into isolated fixture for actual header proof; not proof every fast full-client run polled. |
| ERRORS: unsupported capabilities, bad request/version/IDs/content types/context | [Pinned TCK gate](../d4e6273/tck-1-gate.json), [native auth/version matrix](../d4e6273/native-native-checks.json), supplemental audit | Native scoped checks with requirement-level TCK dispositions. Legacy `ValidationTest` accepting a missing version is not candidate version evidence; candidate rejects default 0.3. |
| LIFECYCLE: immediate/slow/nonblocking/poll/input/cancel/repeat/terminal operations | TCK repeats on explicitly nonshipping fixture; SDK real-agent; 44 native terminal records | PASS within recorded fixtures/runtimes; cancellation also rejects late completion with 404. Controlled fixture is not the public demo. |
| DATA: artifacts/history limits/failure/list/pagination | TCK gate, SDK artifact/history, [native listing](../d4e6273/native-listing-checks.json) | Native PASS with **125 context-filtered** exact results. Unfiltered scan ceiling/retention cleanup unmeasured; no partial-success pagination or unlimited-history claim. |
| RACES: follow-up serialization/cancel-completion/terminal agreement | 44 native terminal cases; [Core case list](../d4e6273/full-suite-cases.json), CoreProtocolTest | Native races plus deterministic engine-backed injections. Commit-then-lost-response/NOT_FOUND and invisible-state branches are Core adapter checks, not native network-loss proof. |
| LOAD: 100 sequential/20 concurrent/two-agent exactness | [Reliability summary](../d4e6273/reliability-summary.json), alpha/beta workload records | Native PASS: 120 unique exact outcomes, measured overlapping working tasks, foreign get/cancel/follow-up boundaries, exact owned listings. Not a production-capacity guarantee. |
| RETRIES: duplicates/delayed index/restarts | Reliability records; native transport repair; CoreListingTest/CoreProtocolTest cases | Independent duplicate tasks and owned restarts native PASS. Synthetic cursor/batch/index faults tested through Harness; no claim those faults were induced on a production exporter. |
| AUTH: valid HTTPS key/engine auth, reject missing/invalid keys before work | Native matrix/provenance; SDK TLS verification | Native PASS with platform authorizations enabled and no unauthorized business starts; credentials checked absent from stored variables. Shared trust boundary, no per-user isolation. |
| FAILURES: credentials/permissions/model/outage/core transport | [Native failure map](../07b3387/failure-evidence-map.md), d4e6273 failure records | Applicable checks PASS with distinctions between deployment-wide secret failures, derived input/provider faults and true owned-engine outage. Combined admin membership/grant repair is not least-privilege proof. |
| SUBMIT-AMBIGUITY: failed external call can leave business work active | [Editor-target incident/health](../a994f22/README.md#failed-submission-retained-separately) | Observed HTTP409 ABORTED left original client failed and matching business task INPUT_REQUIRED. Preserved, not recovered/retried or called a product fix. Operator guidance prohibits blind new-task retry; healthy later calls are separate results. |
| WAITS: bounded infrastructure failures and operator repair | Same native failure map; Core expiry tests | Explicit 503, five-second caller timeouts and actionable incidents/diagnostics; no fabricated success. Eventual webhook responses after caller timeout unobserved. Native loss after correlation commit not injected. |
| OPERATIONS: history retention/resource use/cleanup | Guide; runtime Compose/exporter configuration; owned cleanup logs | Constraints documented: retention disabled, one-second exporter flush/four threads. Enabled retention/visual cleanup/unfiltered ceiling remain unverified, not production eligibility. |
| ASSETS: every selected BPMN/DMN/template/form works in its relevant surface | Per-file [inventory](asset-inventory.json), [Hub twelve-hash verification and actual forms](../a323e19/README.md), Desktop, native records | Selected twelve imports have applicable editor/runtime evidence; deterministic echo separately covered natively. Recommend acceptance for this declared set only. Archived OAuth/proxy/Compose/smoke/deploy/c8run scripts remain excluded, not newly passing assets. Static closure alone is not editor execution. |
| REPRODUCE: exact commands/source/result provenance | d4e6273 series and original summaries; 07b3387 commands/raw logs; guide | Evidence is immutable and source-specific. Adaptation diagnostic lacks raw logs/digests. No historical test rerun or relabeling in this integration. |
| EXCLUDED: push callbacks/settings, OAuth expiry, optional standard-path ingress | Declared card/profile, native failure map | NOT APPLICABLE to selected Basic push-disabled direct-URL profile; unsupported-capability rejection remains checked. No delivery/expiry/ingress pass. |
| RELEASE: Marketplace/legal/publication/LinkedIn | Separate authorization required | Deferred, not prototype functionality or an authorization to merge/submit/publish. Human usability/ease/adoption timing not claimed. |

## Asset and script boundary

The selected import set is exactly the 11 repository resources plus upstream AI Agent v5 returned by
`tools/check_resources.py`, pinned at `camunda/connectors@844cb028a43e2a15d31f5a49e6cb0a9961c0f208`.
The [inventory](asset-inventory.json) records every selected local file's SHA-256/Git blob,
the separately linked deterministic echo, and every other tracked file in `blueprint/` and `scripts/`.
No file is accepted merely because its directory is named blueprint.

`blueprint/docker-compose.yml`, `proxy/nginx.conf`, `smoke.py`, `smoke.sh`, `scripts/deploy.sh`
and `scripts/c8run-demo.sh` belong to the historical unauthenticated experiment, not candidate installation.
The smoke program expects time/temperature/capital tools, not synthetic charge reconciliation.
The OAuth profile is nonshipping/unverified. Trace/coverage/token scripts are contributor diagnostics;
generators and tests are contributor-only, not adopter prerequisites. No execution of these archival scripts
is implied by the native candidate evidence.

## Desktop report provenance and remaining integration

`desktop-modeler-5.51.1.json` is an unchanged sanitized report supplied by the separate editor-validation
session and integrated here with explicit authorization. Its local custody commit is
`d6e321cca6d1795a91d467480fba41d5a096742f`; that custody commit has no public URL.
This identifies report provenance, not a publicly accessible source repository or a new execution.
All 11 local source SHA-256/blob pairs match this inventory; the twelfth upstream template has its own pin.
Engine-profile and duplicate bundled/project-template warnings remain in the report.
The report's editor PASS is deliberately narrower than runtime or human-usability acceptance.

Later [editor-deployed external evidence](../a994f22/README.md) records current exact runtime/tool versions,
actual Desktop deployment and exact updated guide commands. It does not fill unknown historical versions.
The original Desktop report above remains immutable at its earlier preview-only scope.
The [later Hub integration](../a323e19/README.md) supplies durable actual editor/form evidence and
setup/deviation records for the selected original imports. Runtime checks do not cover edited roundtrip
copies. Recommend acceptance of the relevant-runtime outcome map for the declared profile with preserved
failure records and exclusions. The [required component-version gap analysis](../a323e19/required-version-gaps.md) identifies the precise
remaining omissions: historical Maven integration storage product/version and optional SaaS managed
storage/version. No-editor is N/A; REST deployment API follows the engine version. Missing unrelated
host-tool patches or a WebSockets semantic patch are not blockers for these required fields.
The failed8.10 attempt has exact configured Elasticsearch8.17.0 but no effective image digest;
optional SaaS separately lacks immutable public run/source provenance.
