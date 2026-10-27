# Editor-deployed external setup evidence

The documented external call succeeds with exact reconciliation evidence on the retained validation-owned
engine 8.8.21 / stock Connectors 8.9.0 / Elasticsearch 8.17.0 target after actual editor deployments.
This closes the external-call portion only. Hub visual form completion, complete historical versions
and blanket asset acceptance remain separate, incomplete criteria.

## Source and execution boundaries

| Record | Source and result |
| --- | --- |
| [Original external run](external-original/assertions.json) | `841468ecc2ff40e6fb7bf0fea381978833812ce9`, clean; PASS with disclosed local CA/client-DNS adaptation. Card, exact guide SendMessage payload, GetTask, context-filtered ListTasks; Send/Get with missing and invalid key return 401. |
| [Exact updated guide run](exact-guide/assertions.json) | `a994f22f03ae5e6a90155607ebadbf8ce97338bb`, clean; PASS using literal published Bash blocks, including the documented lab CA/resolve array. Guide SHA-256 `4464644594c747967b984e1fb06b802bc3399027bcd8a6b2864c4d9a21f1c311`. Card/send/poll commands were extracted, not rewritten. |
| [Current runtime provenance](external-original/runtime-versions.json) | Target started from 841468e with source runtime Compose plus session-only capacity/storage override. Exact image IDs/digests, engine topology, exporter configuration and current tool/model versions. These observations do not fill unknown historical versions. |
| [Desktop report](desktop-modeler-5.51.1.json) | Original asset pin b6b1baf; actual Desktop Modeler 5.51.1 import/configuration/form preview/save-reopen and eight-resource deployment. Corrected custody commit `e98027d52bb9b940b5a0e8fe04111333e4dbf864` has no public URL. Sanitized report copied unchanged with authorization; no Marketplace or Hub form acceptance follows. |
| [Deployed-source readback](external-original/deployed-source-readback.json) | Sixteen process/version pairs across Hub v1 and Desktop v2. Hub v1 is byte-identical. Seven Desktop v2 process XMLs are byte-identical; client v2 omits only the final newline. Both original/deployed hashes are retained. The Desktop report separately records exact validation-DMN readback. |
| [Ambiguous transport failure](transport-incident/health.json) | Failed client submission was not recovered or relabeled. Current topology healthy; zero container restarts/OOM. Gateway's internal heartbeat timeout caused HTTP 409 ABORTED while business work had in fact started. Root cause of the missed heartbeat is not established. |

Packaged assets and runtime configuration remain unchanged from d4e6273; later changes are documentation
or nonshipping verification harnesses. The v2 deployed client newline is editor serialization, not a
committed runtime change. Source SHA-256 values are in the earlier [inventory](../32f8d4e/asset-inventory.json).
The upstream AI Agent v5 template remains pinned at connectors commit
`844cb028a43e2a15d31f5a49e6cb0a9961c0f208`.

## Settings, commands and exact outcomes

[Setup record](external-original/setup.md) lists prerequisites, every supplied connector secret
(sensitive values withheld), setup sequence and deviations. Current versions include Docker Engine
29.9.2, Compose 5.6.1, Python 3.9.6, Ollama 0.40.3; Desktop deployment continuation reports macOS
26.7.1, Electron 43.0.0 and Chromium 150.0.7871.46. No inference about older runs is made.

Both external runs compare the complete reconciliation object:

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

The initial SendMessage already returned COMPLETED in each run. Each then made one explicit GetTask
lookup and verified the persisted result. Neither run demonstrates a WORKING-state polling interval.
The [literal guide commands](exact-guide/commands.json), `.body` raw response bytes and `.stderr` curl
progress/error output are retained. No trace exposes request headers or credential values.
Output paths in the older normalized argv record use artifact-relative names.

The guide now supports the Docker Desktop local lab explicitly: keep certificate hostname validation,
trust the generated lab CA, map only the curl request's advertised hostname to loopback, and keep normal
Docker-network resolution/Java CA trust for the BPMN client. This is not production DNS, ingress proof
or permission to disable TLS checks.

Actual editor setup preceded these calls. Desktop used an isolated process application with eight
resources, four project templates and a marker, not eight independent standalone deployments.
Hub's workspace/template publication and developer-database setup belong to its separate report;
the external verifier did not execute those steps. The original run retains its deviations rather
than being retroactively relabeled as following the later guide.

## Failed submission retained separately

The first Hub client failed at DiscoverAgent with 404 before webhook readiness. A later Tasklist-started
client failed at SendMessage with 409 ABORTED. Its original incident, request and business task remain
unchanged. [Raw engine/connector excerpts](transport-incident/) and the captured root-variable snapshot
show that the second request created work despite failing at the client:

| Item | Observed identity/state |
| --- | --- |
| Failed client | `2251799813686256`, SendMessage job `2251799813686296`, incident `2251799813686902` |
| Original RPC | `2251799813686298`, message `01a17d64-f36b-7d5e-ba0f-ff63f4fac957` |
| Business process | `2251799813686335`, ACTIVE |
| A2A task | `01a17d64-f40b-7547-8522-3a86ba9a1948`, INPUT_REQUIRED |
| Context | `01a17d64-f40a-7811-94cc-afa81c193945` |
| Agent question | `What is the expected amount for the single order at Northwind Electronics?` |

The engine logged an internal Atomix self-connection closed after missing heartbeats and warned that
the request might already have been accepted and might be unsafe to retry. No restart, OOM or leader
loss was observed. Do not equate present health with a proved explanation or a repaired original client.
The later independent external successes are separate runs, not recovery of that failed chain.

Retrying this original new-task SendMessage would create another independent task under the documented
duplicate-submission contract. No retry, synthetic success response, manual client-variable repair,
configuration change or failure injection was performed. Hub owns a separately recorded fresh form
journey. The operator warning is documentation of this observed ambiguity, not a protocol-fix claim.

## Remaining boundaries

No human ease, newcomer timing, production or publication claim follows. Deterministic adaptation is
carried forward from the accepted 597b152 informed-agent diagnostic with unchanged source, not rerun.
No conformance or full regression rerun was needed for documentation/evidence changes.
The target remains running for Hub; cleanup requires coordinator agreement.
The combined forms/editor, complete-version and all-assets criteria remain partial pending relevant
runtime evidence. Marketplace and merge authorization remain outside this task.
