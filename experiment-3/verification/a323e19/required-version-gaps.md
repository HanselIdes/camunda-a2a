# Required component-version record

The acceptance fields are engine, Connectors, Modeler, storage and deployment versions.
Do not treat missing unrelated host-tool patches as missing required component versions.
An engine REST deployment uses the API delivered by that exact engine version, not a separately
versioned deployment product. An editor not used in a runtime-only run is **not applicable**,
not an unknown editor version. Host Docker/Python/Ollama observations remain useful supplemental
provenance but are not substituted for these five fields.

| Attempt | Engine | Connectors | Modeler | Storage | Deployment |
| --- | --- | --- | --- | --- | --- |
| Accepted native8.8 reference and subsequent failure/adaptation runs | 8.8.21 | 8.9.0 | N/A: no editor used | Elasticsearch8.17.0 | Engine8.8.21 REST deployments; original source pins retained in map |
| Historical8.9 native attempt at0bc60d4 | 8.9.5 | 8.9.0 | N/A: no editor used | Elasticsearch8.17.0 | Engine8.9.5 REST deployments |
| Failed8.10 native attempt at0bc60d4 | 8.10.2 | 8.10.0 | N/A: no editor used | Elasticsearch8.17.0 configured by exact source Compose; effective digest not captured | Engine8.10.2 REST deployments; failure retained |
| d4e6273 Maven process/integration suite | Configured container8.10.2; embedded engine supplied by Process Test8.10.4 where applicable | Configured integration container8.10.0 | N/A: no editor used | **Actual integration storage product/version not retained** | Camunda Process Test8.10.4 deployment API; container engine API8.10.2 where used |
| Optional SaaS narrative diagnostic | Reported8.8.44 | Reported8.8.24 | No editor result claimed; historical editor use not established | **Provider-managed internal storage/version undisclosed in retained evidence** | No independent deployment-product version established; engine API if used is8.8.44. No editor deployment pass |
| Original Desktop preview/save-reopen report | N/A: no authorized target deployment in that stage | N/A | Desktop5.51.1 | N/A: no runtime used | N/A: no deployment submitted |
| Actual Desktop deployment continuation | 8.8.21 | 8.9.0 | Desktop5.51.1 | Elasticsearch8.17.0 | Actual Desktop5.51.1 process-application UI to engine8.8.21 |
| Actual local Hub deployment and Tasklist journey | 8.8.21 | 8.9.0 | Hub1.0-SNAPSHOT at full source e1fa2b8cec1a8d402c3a47005ede5d954d26320f | Engine Elasticsearch8.17.0; editor PostgreSQL14.24-alpine | Actual Hub project Deploy & run from that exact build to engine8.8.21 |
| External setup841468e/a994f22 | 8.8.21 | 8.9.0 | Reuses the two actual editor deployments above | Elasticsearch8.17.0 | No deployment by external verifier |

The archived Compose/c8run configuration is not an executed candidate attempt and is not a new
supported combination. Its configured H2 backend/version uncertainty is not a blocker for the selected
Basic prototype. Hub dependency WebSockets SNAPSHOT is pinned by digest; lack of a semantic patch for
that auxiliary component is not a missing engine/Connectors/Modeler/storage/deployment version.

## Irreducible retained-evidence gaps

1. The d4e6273 full-suite report and retained nineteen Surefire XML files do not record the actual
   integration storage product/version. The retained ten-line full-suite log contains no storage
   startup record. The two source runtime properties pin engine/Connectors images but not storage.
   Inspecting today's defaults/image or rerunning the suite would not establish what that historical
   execution used. No H2 or Elasticsearch version is inferred for it.
2. The optional SaaS diagnostic did not retain the managed storage product/internal version.
   This is provider-unobserved information, not an operator-controlled component to pin locally.
   It also lacks public immutable run/source provenance, a separate attribution limitation.
   No SaaS support or editor-deployment result is claimed.

The failed8.10 run records an exact configured storage version, but not an effective image digest.
If acceptance demands independently observed storage rather than exact configuration for that failed
attempt, that is an additional evidence-strength gap; it is not an unknown configured version.
Image digests are retained for accepted native8.8/8.9 runs.

The declared current runtime/editor/deployment combination has all five applicable version fields
recorded. The literal every-historical-attempt criterion remains incomplete for the two storage records
above. The coordinator must decide acceptance/scope explicitly; this report does not waive it.
No broad rerun can retroactively recover missing historical observations.
