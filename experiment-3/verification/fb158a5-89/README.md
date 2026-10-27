# Confirmed synthetic prototype: exact 8.9 validation

**PASS for the bounded synthetic prototype on the exact pair below.** This is not a production,
arbitrary-language grounding, financial-action, SaaS-runtime or changed-form UI claim.
Earlier failures remain in this directory and the [preceding checkpoint](../3634072-89/README.md).
Execution date: October 27, 2026.

| Component | Exact observed version |
| --- | --- |
| Engine and deployment REST API | Camunda 8.9.26 |
| Stock Connectors | 8.9.17 |
| Secondary storage | Elasticsearch 8.19.23 |
| Modeler | N/A: no editor used in these runs |
| Deployment mechanism | Engine `/v2/deployments` |
| Model runtime | Ollama 0.40.3 |
| Model | `qwen3-coder-30b-64k:latest`, digest `13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253` |

These are latest stable patches within the same minor, not equal patch numbers. Release/registry
discovery and official index/platform/config digests are retained in `discovery.json` and
`image-manifests.json`. Every attempt records actual images and component/tool versions in its
control directory and `required-component-versions.json`. No 8.8 or arbitrary 8.9+ combination is claimed.

## What changed

Free text remains verbatim model context. It no longer authorizes the model to invent required
business fields. The client explicitly confirms merchant, currency, two charge amounts, expected
amount and `syntheticOnly=true` in one current-message `data.syntheticClaim` object.

The engine validates types/completeness before arithmetic. Missing/partial/invalid confirmation
produces INPUT_REQUIRED without arithmetic evidence. The tool has no model financial parameters:
its input mapping reads the validated client object. The publication guard checks the result against
that object. No fields merge from old messages, other tasks or model context.
Conflicting free text may be refused or asked about again; it cannot change the confirmed result.
This confirms client input, not real-world truth.

The supplied answer form collects explicit fields with no model prefill. The client sends them on
the same task/context. External clients can send the structured object initially for one-shot
completion. The final nine-field reconciliation output is unchanged.

## Immutable execution sources

| Commit | Scope |
| --- | --- |
| `081846361ede65acfb2d2b931819a04ba50bec79` | Initial confirmation source, form/client, guide and coupled checks. |
| `893587670b5f6bc20822643ac916932d938a87d2` | Correct text+data join so confirmation parts cannot append a space to actual user text. Final shipped executable bytes. |
| `994c3f5c89b52b165782b3019e761ecb68d58196` | Test-only safe-refusal assertion and valid JSON diagnostic capture. |
| `fb158a5798baa5cdbba9514a537c5e16098ef936` | Test-only standalone SDK fixture under retained Python `-I`. Both final full real and scoped TCK runs use this clean commit. |

Evidence/docs commits do not change the pinned executed source. `asset-inventory.json` records
exact blobs and SHA256s: 11 local imports plus pinned upstream AI Agent v5 (raw readback200/hash match).
The 10-resource Web/SaaS URL set omits only stock REST and AI template URLs; the full12 closure remains
for clean Self-Managed Hub and exact-version Desktop fallback. Exact HttpJson@12 and AI Agent@5 must
resolve in the target registry; an import collision does not prove equivalence.
No standard template was deleted; archival scripts remain nonshipping; legal notices are unchanged.

## Executed outcomes

| Attempt | Result |
| --- | --- |
| `confirmed89-real-1` | FAIL at retained literal-input assertion: joining a data part as empty text appended a space. Happy-path reconciliation/follow-up/client already worked. Corrected in8935876; original failure preserved. |
| `confirmed89-real-2` | Native happy path and six literal cases pass. New hostile-text test expected completion but model safely asked again with no artifact. Assertion was too strict for the approved prototype invariant; corrected to require exact unchanged fields if anything is published, otherwise allow INPUT_REQUIRED with no artifact. Original observation preserved, not reclassified as a full pass. |
| `confirmed89-real-3` | Native real/client/literal/confirmation/auth checks pass. Overall FAIL at SDK subprocess startup: Python isolated mode cannot import the new sibling fixture module. No SDK requests executed. Fixed only the standalone test fixture. |
| `confirmed89-real-4` | **Full native real-model suite PASS**, including SDK1.2.3 and exact current external guide. |
| `confirmed89-tck-1` | **Scoped TCK PASS**:68 executed,167 skipped,0 failures/errors,56 MUST passes,58 reasoned exclusions,0 incidents. Not unrestricted A2A conformance. |

The final real run actually checks:

- Exact nine-field Northwind result; incomplete free text followed by numeric-leading text plus
  explicit confirmation on the same task/context, four history messages and terminal lookup.
- Supplied BPMN client free-text intake → confirmation user task → structured follow-up → exact
  result review → process COMPLETED. Tasks completed through engine REST, **not UI**.
- Actual model-input equality for numeric-leading text, quotes, backslashes/literal escape sequences,
  LF, all32 C0 controls plus DEL, and leading-equals JSON. Bare JSON asks for confirmation with no artifact.
- 46 exact-engine expression cases for complete/missing/partial/malformed confirmation, zero,
  negative/non-numeric values and nonfinite JSON rejection; eight real request turns checking invalid,
  duplicate, partial follow-up, hostile text and cross-task non-leakage.
- Missing/invalid task keys across11 methods,12 known/unknown resource checks, no unauthorized business
  starts, version negotiation and persisted credential/header exclusion.
- Independent official Python a2a-sdk1.2.3 discovery, send/follow-up, exact result, GetTask,
  context-filtered listing and patch-version negotiation.
- Literal current guide Bash card/SendMessage/GetTask and exact nine fields over verified HTTPS.
  Initial result was COMPLETED; one GetTask proves persistent lookup, not a working-state transition.

See `confirmed89-real-4/{runtime-provenance,literal-model-inputs,confirmation-checks,native-checks,sdk}.json`,
its `bpmn-client-versions.json` and `exact-guide/assertions.json`. The guide hash matches the executed
source; later documentation-only changes retain the same executable Bash blocks.
The generic native "authenticated echo" log label also occurs in real-model mode; deployed assets and
exact reconciliation identify the actual mode.

38 Python harness tests, deterministic generator checks,12-resource closure, official Camunda form
schema1.18.0 validation and changed packaged BPMN lint pass. `static-checks.json` records commands/tools.
No Maven runtime, broad version matrix, load study, restart study, actual changed-form UI or SaaS
import/runtime rerun is substituted for these results.

## Preservation, sanitation and cleanup

Five sequential newly owned stacks used fresh storage/secrets, Basic engine authentication and
authorizations, shared task API key and verified direct TLS. Four connector execution threads,
active-version polling disabled, exporter bulk delay1s; disposable resource caps are recorded.
Every attempt was captured before owned teardown. No ambiguous request was blindly resubmitted.
`final-owned-cleanup.json` confirms all10 owned ports closed and no owned containers/networks/volumes;
both pre-existing secondary containers remain running. No shared kills, pruning, DNS/profile edits.

`sanitization.json` records input/output hashes and transformations. Account/session/temp paths and
literal credential headers are sanitized. Full private originals remain retained; only selected runtime
diagnostic log anchors are included. In the first structured diagnostic, non-JSON Infinity/NaN values
are explicitly represented as `{"nonJsonToken":"..."}` markers so the published report itself is valid
JSON; later diagnostics retain the actual submitted malformed JSON as a string. Both were rejected400.
No profiles, screenshots or private planning were copied. `nonshipping-harness/` is diagnostic tooling,
not supported installation assets. `SHA256SUMS` covers the resulting evidence.
