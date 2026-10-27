# Editor-deployed external setup verification

Source: `841468ecc2ff40e6fb7bf0fea381978833812ce9`, clean before execution.
This is an informed-agent functional check, not a fresh-adopter study, setup-time measurement,
production-readiness result or acceptance of visual form completion.

## Prerequisites and supplied settings

The target was a separately owned Docker Compose runtime with exclusive loopback ports,
network and storage. No existing primary/secondary engine or Hub dependency was altered.
The source runtime Compose and low-latency exporter override supplied the configuration.
A session-only override added named persistent volumes, a gRPC port and memory ceilings:
Elasticsearch 1 GiB, engine 2.5 GiB, Connectors 1 GiB with a 512 MiB Java heap.
Engine Java heap remained 1536 MiB; Elasticsearch heap remained 512 MiB.
Docker had 7.75 GiB total memory and approximately 2.3 GiB existing container usage before setup;
56 GiB filesystem capacity was free.

Observed software: engine 8.8.21, stock Connectors 8.9.0, Elasticsearch 8.17.0,
Docker Engine 29.9.2, Docker Compose 5.6.1, Python 3.9.6, local Ollama 0.40.3.
Model: `qwen3-coder-30b-64k:latest`,
digest `13cd851c8a123721a1b448f47d94733d63966757363e002dae4a0ef8a0eb9253`.
Runtime image IDs/digests and effective exporter settings are recorded separately.

Platform settings: Basic authentication, unprotected API false, authorizations true,
generated validation-only user with built-in admin membership; no least-privilege claim.
Engine REST and gRPC addresses were explicit, not global c8ctl profiles.
Connectors used Basic engine authentication, request timeout PT40S, four execution threads,
environment secret prefix SECRET_, active-version polling false.
The engine used Elasticsearch secondary storage, CamundaExporter and bulk delay one second.
Retention remained disabled.

Every connector secret supplied:

| Secret | Supplied setting |
| --- | --- |
| ENGINE_URL | Owned engine's Docker service URL |
| ENGINE_USERNAME / ENGINE_PASSWORD | Generated validation-only engine identity; values withheld |
| A2A_API_KEY | Generated validation-only shared key; withheld |
| A2A_RPC_URL | `https://host.docker.internal:60147/inbound/a2a` |
| A2A_AGENT_CARD_URL | `https://host.docker.internal:60147/inbound/a2a-card` |
| A2A_PUBLIC_URL | `https://host.docker.internal:60147/inbound` |
| A2A_PUSH_ENABLED | false |
| A2A_AGENT_PROCESS | a2a-card-dispute |
| CAMUNDA_PROVIDED_LLM_API_ENDPOINT | `http://host.docker.internal:11434/v1` |
| CAMUNDA_PROVIDED_LLM_API_KEY | Documented local provider dummy key; value withheld |
| CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL | qwen3-coder-30b-64k:latest |
| PROOF_RESTRICTED_PASSWORD | Generated unused failure-fixture secret inherited from contributor Compose; withheld |

Generated engine/API/TLS/restricted passwords are stored only in permission-restricted session artifacts,
not this report. TLS was enabled on Connectors using a generated local certificate and Java trust store.
The certificate's SAN covers host.docker.internal, localhost and 127.0.0.1.
External curl and internal Java clients use the validation CA; verification is never disabled.
The local model name configuration is not evidence of using Camunda's SaaS model.

## Setup sequence and deviations

1. Reconciled clean source and available Docker capacity, images and ports.
2. Started a unique Compose project with authenticated engine and configured stock Connectors.
   Verified empty process/decision/instance/task inventories, topology 200 with credentials,
   topology 401 without them, HTTPS readiness 200, model endpoint reachability on the owned network,
   effective exporter delay one second and exact image provenance. No resources were predeployed.
3. Separate Hub validation session imported/configured/published the templates and deployed the
   eight resources through its actual editor. Parent reported developer setup required a Flyway
   development-database reset; details and ownership belong to the separate Hub evidence.
4. Separate Desktop validation used the actual Modeler 5.51.1 process-application workflow:
   eight original resources, four pinned templates, empty .process-application marker.
   It submitted all eight resources. The editor reported deployment, and engine inventory showed
   all eight process IDs and validation decision at version 2. Seven process XMLs match the source
   bytes; the client XML omits only its final newline. Both hashes are retained in the readback record.
   No roundtrip duplicate was deployed.
5. This verifier fetched the advertised card and executed the guide's exact external SendMessage
   payload followed by its GetTask polling request, then context-filtered ListTasks.
   Missing/invalid keys were rejected for SendMessage and GetTask. No form task was completed.

The macOS host does not resolve `host.docker.internal`; external curl used client-scoped
`--resolve host.docker.internal:60147:127.0.0.1`. The owned Docker network resolves it normally.
This is an explicit setup adaptation, not standard-path ingress or globally configured DNS.
The CA was passed with `--cacert`. Actual sanitized argument vectors, exit codes, HTTP status and
raw response bytes are retained. Output-path names and secret/CA variables in commands are normalized.

Two provisioning harness attempts were cleaned before the retained target:
the first external TLS probe ran before readiness, and the second assumed curl existed in the
Connectors image. The retained target used bounded HTTPS readiness and the engine container's
existing wget for a read-only model endpoint probe. Neither failure required a product/configuration
change or deployment to a shared engine.

These are deviations from a self-contained only-the-guide installation: contributor Compose/bootstrap,
local certificate generation and trust, client DNS mapping, editor-specific process-application grouping,
Hub workspace/template publication and developer setup. Their functional results must not be relabeled
as newcomer ease or a fully deviation-free installation.

## Results and boundary

PASS for the external setup portion: the card advertises the exact URL, API-key scheme, skill
and disabled push; the guide's payload completed a real-model task. The complete reconciliation object
equals the expected nine fields, not just HTTP 200 or plausible text. Authenticated GetTask and
context-filtered ListTasks return that task; missing/invalid keys return 401.

The SendMessage response already contained the completed task. One explicit GetTask request confirmed
the persisted completed result; this run does not demonstrate a working-state polling interval.
Existing native scoped evidence covers slow/polling behavior separately.

The deterministic adaptation evidence is carried forward from source 597b152, qualified as an
informed-agent raw-XML diagnostic with no BPMNDI and no timing acceptance. Packaged source hashes
remain unchanged; no adaptation was rerun and no target secret was switched for this check.

Visual client forms, Hub runtime completion and the combined editor/form criterion are owned by the
separate session. This external pass cannot substitute for them. The runtime remains up until those
checks and the parent coordinator release it. No broad suite, conformance rerun, failure injection,
runtime modification, publication or merge occurred.
