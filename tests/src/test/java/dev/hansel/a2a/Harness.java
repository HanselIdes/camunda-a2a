package dev.hansel.a2a;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.camunda.client.CamundaClient;
import io.camunda.client.api.command.ProblemException;
import io.camunda.process.test.api.CamundaProcessTestContext;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Stands in for the HTTP JSON connector in process tests: every job of type io.camunda:http-json:1 is
 * turned into the engine call the connector would have made. Everything else (processes, DMN, FEEL,
 * message correlation, timers) is the real engine.
 */
final class Harness {
  static final ObjectMapper JSON = new ObjectMapper();
  static final String HTTP_JSON = "io.camunda:http-json:1";

  final CamundaClient client;
  final CamundaProcessTestContext context;
  final List<String> calls = new CopyOnWriteArrayList<>();

  Harness(final CamundaClient client, final CamundaProcessTestContext context) {
    this.client = client;
    this.context = context;
    context
        .mockJobWorker(HTTP_JSON)
        .withHandler(
            (jobClient, job) -> {
              final Map<String, Object> vars = job.getVariablesAsMap();
              final String url = (String) vars.get("url");
              @SuppressWarnings("unchecked")
              final Map<String, Object> body = (Map<String, Object>) vars.get("body");
              calls.add(url);
              try {
                if (url.endsWith("/v2/process-instances")) {
                  @SuppressWarnings("unchecked")
                  final Map<String, Object> variables = (Map<String, Object>) body.get("variables");
                  client
                      .newCreateInstanceCommand()
                      .bpmnProcessId((String) body.get("processDefinitionId"))
                      .latestVersion()
                      .variables(variables)
                      .send()
                      .join();
                } else if (url.endsWith("/v2/messages/correlation")) {
                  @SuppressWarnings("unchecked")
                  final Map<String, Object> variables =
                      (Map<String, Object>) body.getOrDefault("variables", Map.of());
                  try {
                    client
                        .newCorrelateMessageCommand()
                        .messageName((String) body.get("name"))
                        .correlationKey((String) body.get("correlationKey"))
                        .variables(variables)
                        .send()
                        .join();
                  } catch (final ProblemException e) {
                    if (e.code() == 404) {
                      jobClient
                          .newThrowErrorCommand(job)
                          .errorCode("NOT_FOUND")
                          .errorMessage("no message subscription")
                          .send()
                          .join();
                      return;
                    }
                    throw e;
                  }
                } else if (url.endsWith("/v2/messages/publication")) {
                  @SuppressWarnings("unchecked")
                  final Map<String, Object> variables =
                      (Map<String, Object>) body.getOrDefault("variables", Map.of());
                  client
                      .newPublishMessageCommand()
                      .messageName((String) body.get("name"))
                      .correlationKey((String) body.get("correlationKey"))
                      .timeToLive(java.time.Duration.ofMillis(((Number) body.get("timeToLive")).longValue()))
                      .variables(variables)
                      .send()
                      .join();
                } else {
                  throw new IllegalStateException("unexpected http call " + url);
                }
                jobClient.newCompleteCommand(job).send().join();
              } catch (final RuntimeException e) {
                jobClient.newFailCommand(job).retries(0).errorMessage(String.valueOf(e)).send().join();
              }
            });
  }

  /** Simulates the webhook: starts a handler instance and waits for the response body. */
  Map<String, Object> rpc(final Map<String, String> headers, final Object body) {
    final var result =
        client
            .newCreateInstanceCommand()
            .bpmnProcessId("a2a-rpc")
            .latestVersion()
            .variables(Map.of("rpc", body, "hdr", headers))
            .withResult()
            .requestTimeout(java.time.Duration.ofSeconds(60))
            .send()
            .join();
    return responseOf(result.getVariablesAsMap());
  }

  @SuppressWarnings("unchecked")
  private static Map<String, Object> responseOf(final Map<String, Object> variables) {
    return (Map<String, Object>) variables.get("rpcResponse");
  }

  static Map<String, String> headers() {
    return new LinkedHashMap<>(Map.of("content-type", "application/json", "a2a-version", "1.0"));
  }

  static Object parse(final String json) {
    try {
      return JSON.readValue(json, Object.class);
    } catch (final Exception e) {
      throw new IllegalArgumentException(e);
    }
  }

  static Map<String, Object> map(final String json) {
    try {
      return JSON.readValue(json, new TypeReference<Map<String, Object>>() {});
    } catch (final Exception e) {
      throw new IllegalArgumentException(e);
    }
  }

  /** Builds a JSON-RPC request body. */
  static Map<String, Object> request(final String method, final String paramsJson) {
    final Map<String, Object> m = new LinkedHashMap<>();
    m.put("jsonrpc", "2.0");
    m.put("id", 1);
    m.put("method", method);
    m.put("params", parse(paramsJson));
    return m;
  }
}
