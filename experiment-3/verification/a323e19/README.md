# Actual Hub and Tasklist form evidence

The selected Basic prototype's actual Hub import, configuration, save/reopen and deployment checks
passed. A separately authorized fresh synthetic Tasklist journey completed the deployed ask, answer
and result forms through the real UI. The two earlier failed clients and original input-required
business task remain preserved, not repaired or counted as successful executions.

This integrates a separate informed-agent session's authorized JSON evidence, not a new execution
by the integrator. Asset source is `b6b1baf55fe32e5ff0f961e6dab6c99b966cbe3c`; all twelve immutable
SHA-256/Git blob pairs match the [existing inventory](../32f8d4e/asset-inventory.json).
Runtime was provisioned from `841468ecc2ff40e6fb7bf0fea381978833812ce9`.
The integration baseline is `a323e19dd35869e3bfc97ced1fb0687a9a71375f`; no packaged asset changed.

| Outcome | Relevant actual evidence | Scope |
| --- | --- | --- |
| Hub import/render/configure | [Final Hub report](hub-validation-current.json) | Twelve files, four BPMN diagrams, validation DMN, four templates and three form previews. Templates required workspace publication. Thirteen external-reference notices retained, not zero-problem UI proof. |
| Save/reopen | [Keyboard/autosave/reload observations](hub-save-reopen-observations.json) | Temporary nonfunctional card note persisted; restoration of original content persisted. Browser reload only, not service-restart durability. |
| Hub deployment | [Engine resource integrity](hub-deployed-resource-integrity.json), final report | Actual project Deploy & run; eight process definitions and validation decision at v1. All four original BPMN files byte-identical. Immediate run failed discovery with 404, retained. Desktop later deployed v2 separately. |
| Ask form | Final report's fresh journey | Actual deployed start form, intentionally incomplete synthetic request, one distinct fresh H2 client. Delayed indexing did not cause a second start. |
| Answer form | [Rendered question](tasklist-fresh-answer-observations.json), [UI completion](tasklist-fresh-answer-completion.json) | Expected-amount question dynamically rendered; assigned, filled and completed through UI with observed 204 responses. Heading shows literal backslash-n separators on 8.8.21, readable but not formatting-perfect. |
| Result form | [Actual displayed values](tasklist-fresh-result-observations.json), [completed journey](tasklist-fresh-journey-result.json) | Paid99.9USD, expected49.95USD, overcharge49.95USD, REQUEST_HUMAN_REVIEW and no-financial-action text. Assigned/completed through UI; unique client COMPLETED/hasIncident=false. No REST form-completion substitution. |
| Failure retention | Final report and [owned-runtime incident evidence](../a994f22/README.md#failed-submission-retained-separately) | Original discovery404 and ambiguous SendMessage409 retained. Business work existed after409. No original-job retry, cancel, configuration change or exactly-once claim. |

## Exact source-version map

Hub source: `camunda/camunda-hub@e1fa2b8cec1a8d402c3a47005ede5d954d26320f`,
application `1.0-SNAPSHOT`, supported local development profile with license enforcement unchanged.
Observed tools: Temurin25.0.5+8-LTS, Maven3.10.0, Node24.22.1, npm12.2.1.
Hub dependency images: PostgreSQL14.24-alpine, Keycloak26.3.3, Identity8.10.2,
Mailpit1.32.0 and WebSockets SNAPSHOT; exact digests are retained in the final report.
The WebSockets semantic build version is unknown beyond its SNAPSHOT tag and immutable digest.
Hub's PostgreSQL is editor storage, not engine secondary storage.

Deployment target: engine8.8.21, stock Connectors8.9.0, Elasticsearch8.17.0, Basic authentication
and authorizations enforced. Desktop deployment was Modeler5.51.1; current engine/image/model/host-tool
pins are in the [preceding external report](../a994f22/external-original/runtime-versions.json).
Hub and Desktop checks share the declared target, not a second advertised runtime combination.
[Required component fields and irreducible gaps](required-version-gaps.md) distinguish no-editor
N/A and engine-versioned REST deployment from missing observations. The retained Maven integration
storage and optional SaaS managed-storage records remain incomplete. Missing unrelated host-tool
patches are not blockers for those required fields. This current run cannot backfill historical observations.

## Setup record and deviations

The runtime owner's [prerequisites and supplied settings](../a994f22/external-original/setup.md) and
[literal updated-guide external commands](../a994f22/exact-guide/commands.json) remain applicable.
Actual editor steps were:

1. Run the supported isolated local Hub development dependencies and backend/frontend.
   The Hub stack contains no engine; add only the separate authenticated validation target.
2. Log in through the actual local developer login, create an isolated workspace/project and assign
   only the owned target. Import the twelve original pinned assets.
3. Publish the four element templates to that workspace at their pinned versions; inspect the
   rendered properties, secret references, BPMN/DMN/form links and previews.
4. Confirm keyboard edits/autosave survive browser reload, restore the original note, and reload again.
5. Use project Deploy & run against the owned environment. Observe actual definition inventory,
   then wait for card/RPC webhook registrations before starting client work.
6. After preserving the initial404 and409 failures and inspecting runtime health, execute one separately
   authorized fresh synthetic Tasklist journey. Match task identities to the unique client before UI actions.
   Assign/complete the dynamic answer and result tasks; verify that client completed without an incident.

Local Hub setup required these disclosed adaptations: Identity host port8085 instead of8080; selected
dependencies under a dedicated Compose project rather than the Make target that calls down with volumes;
four obsolete CAMUNDA_CONSOLE settings omitted only from the child process; an owned deployment environment
added without replacing existing environment definitions; and workspace template publication.
The local profile's Flyway clean-first strategy reset the owned development database on backend startup.
The first workspace/imports were recreated before deployment. This is not a service-restart persistence pass.
No license guard, commercial permission, host-global configuration or unrelated engine was changed.
Early automation attempts using fill or premature reload were not counted; only settled actual UI actions were.
Build/audit warnings remain recorded, not silently fixed or presented as a warning-free pipeline.

The external local-lab DNS mapping and CA trust are now explicit in the guide. Hub developer startup
is a source-build validation environment, not evidence that installing Hub from scratch is a turnkey
blueprint prerequisite. No human ease, newcomer timing or production suitability claim follows.

## Dispositions and privacy

Recommend accepting the selected import-set editor/configuration/deployment and actual runtime-form
outcomes on this one declared combination, together with the separate Desktop/external reports.
This does not accept archived OAuth/Compose/smoke/deploy/c8run scripts as supported assets.
Current relevant-runtime outcome mapping is complete for those functional surfaces; the criterion
requiring exact versions for *every historical attempt* remains incomplete.
Marketplace import/publication, legal approval, broad8.8+ compatibility and merge remain outside this result.

[Sanitation provenance](sanitation-provenance.json) records original/published report hashes and each
transformation. Absolute session paths, runtime owner identity, private routes/profile/log indices and
fresh task/context identifiers were removed or replaced. Screenshots, private identity mappings,
browser profiles, credentials and raw Hub logs were not copied. The twelve public source hashes,
software versions, synthetic field observations, failures and limitations are retained.
After final evidence capture, the coordinator authorized cleanup. The Hub session stopped its owned
services/dependencies without deleting retained Hub volumes. The runtime owner then removed only its
unique validation Compose project and project-scoped named volumes. [Final incident/container state](runtime-final-before-cleanup.json)
and [cleanup verification](runtime-cleanup.json) are retained; two original incidents were still present
before shutdown. No retry or incident resolution was performed. Owned ports60146/60147/60148 no longer
listen, and unrelated secondary container identities were unchanged.
