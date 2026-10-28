# Numbered blueprint, REST v13, and server-agent icon verification

**PASS for the focused checks below** on clean source
`69e77dfa276870c67c4da49a0a58f9c8006e70c9`, based on
`7209d88107b4621f3420fc548f69ef88a9729ccb`.
The baseline numbered the server first and used REST v12 in the import bundle.
This candidate orders the models as client, server protocol, and server agent,
pins current REST assignments to v13, and retains the server template's embedded
agent icon through generation. Runtime process IDs and diagram geometry are unchanged.

## Focused authenticated runtime

The [sanitized runtime report](client-agent-e2e.json) records a fresh run on
Camunda 8.9.26, stock Connectors 8.9.17, and Elasticsearch 8.19.23.
The seven-resource numbered BPMN/DMN/form set deployed successfully. The client
discovered the integrated Agent Card over direct HTTPS, used the authenticated
task endpoint, requested explicit confirmation, followed up and polled the
same task, and reviewed the exact nine-field synthetic reconciliation artifact.
Missing and invalid API keys were rejected. Both the client process and the
server task completed, and the disposable stack was removed.

REST v13 adds an explicit `followRedirects=false` input to the client tools.
The fresh run verifies those mappings with the 8.9.17 runtime; it does not
establish support for every engine/Connectors combination.
The actual AI Agent Task v8 client and AI Agent Job Worker v5 server calls used
a local Ollama override. Shipped `CAMUNDA_PROVIDED_LLM_*` references were unchanged.
SaaS model execution, 8.8 support, full A2A conformance, and Marketplace eligibility
are not established by this record.

## Source and Modeler checks

The [validation record](validation.json) records reproducible generation,
14 resource tests, the 12-resource import closure, 18 automated layout checks,
lint and official BPMN XSD validation for all four shipping/profile BPMNs,
three form-schema checks, nine affected Python tests, and a clean Maven run
of 38 tests across three affected suites.

An isolated Camunda Modeler 5.51.1 instance rendered the expanded
`AgentTools` subprocess's header icon as an 18-by-18 SVG image. Its data URL
exactly matched both `zeebe:modelerTemplateIcon` in the generated BPMN and
`icon.contents` in the pinned upstream Job Worker v5 template. Saving a copy
in Modeler retained the same metadata. The inner script task icon is unchanged.
This is a focused icon-rendering check, not a new whole-diagram visual review.
The qualification remains 18 automated layout checks versus the earlier
three shipping-diagram visual reviews; unchanged DI does not imply every route
is globally bend-optimal.

The full Python unit discovery is **not a passing full-suite result**: preparation
exposed two unchanged baseline errors, an import of the absent `client_versions`
module and `reliability.timed_echo` parsing a floating-point DI coordinate with
`int()`. The affected selectors above pass. Clean Maven validation uses the
current numbered resource names rather than stale `target` copies.

REST v13 is pinned to Connectors 8.10.2 commit
`b490d065b59ffe4788319609dbe41deb25e68e3f`; the bundled snapshot matches the
upstream JSON except for the omitted REST icon. Its engine constraint is `^8.9`.
The server remains on Job Worker v5 from
`844cb028a43e2a15d31f5a49e6cb0a9961c0f208`, with no connector-variant change.
Earlier source-pinned evidence is preserved without modification.
