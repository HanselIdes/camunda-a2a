# Timed clean adoption report

Candidate: `597b1524d58a41db9d7465d523073bce0fd9223e`.
Reported outcome: **PASS in 139 seconds** against the 15-minute adoption target.
All business data was synthetic. Credentials, keys and allocated host ports are withheld.

## Source and evidence limits

The independent adopter used a fresh, clean clone at the candidate SHA.
Engineering source was `d4e6273c862b387ee7b2a49b992cd4db5f56a922`; the intervening
commit changed only the blueprint guide and verification JSON.
Instructions came from `experiment-3/blueprint/README.md` and its linked echo contract
reference and card-dispute follow-up mappings.

The adopter transcribed results from session tool output. No separate raw log or image digests
were captured. Images were pulled by tag: `camunda/camunda:8.8.21`,
`camunda/connectors-bundle:8.9.0` and `elasticsearch:8.17.0`.
The local model was `qwen3-coder-30b-64k:latest`, local ID `13cd851c8a12`.
The disposable stack and clone were deleted after the run. This report is an observed
adoption result, not a self-contained reproducible runtime archive.

## Timing boundary

The timer started on 2026-10-27 at 04:12:13 UTC, after the following were ready:

- Elasticsearch 8.17.0 and Self-Managed engine 8.8.21, with Basic authentication,
  authorizations enabled and unprotected API access disabled.
- An initialized engine user with built-in admin membership, random engine password
  and A2A API key; exporter class name and one-second bulk delay.
- A disposable local certificate authority and server certificate with Subject Alternative
  Names `localhost`, `host.docker.internal` and `127.0.0.1`, PKCS12 keystore and truststore.
- Warm local Ollama model; the warm-up request took 10.9 seconds.

The stock Connectors 8.9.0 image was already pulled. The timed interval included Connectors
configuration/start, deployment, external checks, adaptation of another process and its checks.

## Settings supplied

Values containing credentials or environment-specific addresses are withheld.

| Surface | Settings |
| --- | --- |
| Normal engine connection | `CAMUNDA_CLIENT_MODE=self-managed`, `CAMUNDA_CLIENT_REST_ADDRESS`, `CAMUNDA_CLIENT_GRPC_ADDRESS`, `CAMUNDA_CLIENT_AUTH_METHOD=basic`, `CAMUNDA_CLIENT_AUTH_USERNAME`, `CAMUNDA_CLIENT_AUTH_PASSWORD` |
| Connector execution | `CAMUNDA_CLIENT_EXECUTION_THREADS=4`, `CAMUNDA_CONNECTOR_POLLING_ACTIVEVERSIONSENABLED=false`, `CAMUNDA_CONNECTOR_SECRETPROVIDER_ENVIRONMENT_PREFIX=SECRET_` |
| Direct HTTPS | `SERVER_SSL_ENABLED=true`, `SERVER_SSL_KEY_STORE`, `SERVER_SSL_KEY_STORE_TYPE=PKCS12`, `SERVER_SSL_KEY_STORE_PASSWORD`; outbound truststore path/type/password through `JAVA_TOOL_OPTIONS` |
| Readiness | `HEALTHCHECK_URL=https://127.0.0.1:8080/actuator/health/readiness` |
| Engine REST secrets | `ENGINE_URL` without `/v2`, `ENGINE_USERNAME`, `ENGINE_PASSWORD` |
| A2A secrets | `A2A_API_KEY`, `A2A_AGENT_PROCESS` initially `a2a-card-dispute`, then `adopt-wordcount`; `A2A_RPC_URL` and `A2A_AGENT_CARD_URL` using HTTPS `host.docker.internal` URLs and `/inbound/a2a`, `/inbound/a2a-card` |
| Model secrets | `CAMUNDA_PROVIDED_LLM_API_ENDPOINT` using the host-local `/v1` service; `CAMUNDA_PROVIDED_LLM_API_KEY` using Ollama's dummy value; `CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL=qwen3-coder-30b-64k:latest` |
| Engine exporter, before timing | `ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_CLASSNAME=io.camunda.exporter.CamundaExporter`, `ZEEBE_BROKER_EXPORTERS_CAMUNDAEXPORTER_ARGS_BULK_DELAY=1` |

No nginx/ingress, well-known route, generator, protocol edits, custom worker/server, OAuth profile,
blueprint Compose file or smoke script was used.

## Observed timeline

| Elapsed seconds | Step and outcome |
| --- | --- |
| 2 | Connectors 8.9.0 started and became healthy. |
| 9 | Deployed Basic protocol, validation decision, discovery card, real agent, BPMN client and three forms together through the engine REST deployment API. |
| 17 | Discovery returned HTTP 200 with JSON-RPC 1.0 interface and API-key scheme. Unauthenticated task request returned HTTP 401. |
| 33 | CA-verified external SendMessage/GetTask returned COMPLETED and the exact reconciliation artifact below. |
| 96 | Authored `adopt-wordcount`, updated only the card's business name/description/skills, deployed both, selected it with `A2A_AGENT_PROCESS` and recreated Connectors. Discovery showed the new skill; unauthenticated RPC still returned 401. |
| 132 | Different-process follow-up, cancellation and terminal-operation checks passed as listed below. |
| 139 | Engine search showed both word-count business instances completed and zero incidents. |

The real-model artifact was named `reconciliation`: merchant `Northwind Electronics`, currency `USD`,
charge amounts `[49.95, 49.95]`, paid amount `99.9`, expected amount `49.95`, overcharge amount `49.95`,
recommendation `REQUEST_HUMAN_REVIEW`, and `syntheticOnly=true`.
Status text was: "Synthetic charges reconciled for human review. No refund or financial action was performed."

The separately authored, nonshipping word-count process used `a2a-task-update`, `a2a-send` with the
documented task-ID correlation and follow-up mappings, a FEEL word counter, and the root interrupting
`a2a-cancel` subprocess copied verbatim from echo.

- New task returned INPUT_REQUIRED with "Reply with the text whose words should be counted."
- Follow-up "one two three four five" on the same task/context returned COMPLETED,
  "Counted 5 words.", artifact `{words: 5}`, and history length four.
- Canceling that completed task returned `-32002`; GetTask retained COMPLETED and the artifact.
- Canceling another INPUT_REQUIRED task returned CANCELED without artifacts or a status message.
  Repeat cancellation returned `-32002`, follow-up returned `-32004`, and GetTask plus context-filtered
  ListTasks agreed on CANCELED.
- Cancellation of an unknown task returned `-32001`.

## Deviations and remaining gates

1. Deployment used REST, not Modeler. Actual Modeler/Marketplace import, template import and form usability remain unverified.
2. The external caller used a certificate-valid `localhost` URL while the card advertised `host.docker.internal`. This does not independently prove that an external client can resolve the advertised hostname. The guide now explicitly requires advertised URLs to work from both external clients and Connectors.
3. Switching environment-supplied `A2A_AGENT_PROCESS` required recreating Connectors. The guide now states this at the adaptation step as well as in recovery instructions.
4. The BPMN client form flow and real-model clarification were not repeated here; their separate engineering evidence remains scoped to d4e6273.
5. The engine user had built-in admin membership. This is not least-privilege evidence.
6. This was one run on one Docker Desktop/macOS machine, not a multi-adopter study.

Owned containers, volumes and network were removed, along with the temporary clone and certificates.
Unrelated pre-existing containers were untouched. Import, legal/eligibility and publication approval remain
separate gates; this result authorizes neither merge nor publication.
