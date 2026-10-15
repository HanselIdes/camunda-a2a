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
  /** Whether the simulated deployment has the A2A_PUSH_ENABLED secret set to true. */
  volatile boolean pushEnabled;

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
                  @SuppressWarnings("unchecked")
                  final List<String> tags = (List<String>) body.getOrDefault("tags", List.of());
                  client
                      .newCreateInstanceCommand()
                      .bpmnProcessId((String) body.get("processDefinitionId"))
                      .latestVersion()
                      .variables(variables)
                      .tags(new java.util.LinkedHashSet<>(tags))
                      .send()
                      .join();
                } else if (url.endsWith("/v2/process-instances/search")) {
                  // stands in for the connector's resultExpression that turns the matches into task ids
                  @SuppressWarnings("unchecked")
                  final var filter = (Map<String, Object>) body.get("filter");
                  @SuppressWarnings("unchecked")
                  final var wanted = new java.util.LinkedHashSet<String>((List<String>) filter.get("tags"));
                  final var items = client.newProcessInstanceSearchRequest()
                      .filter(f -> f.processDefinitionId("a2a-task").tags(wanted)).send().join().items();
                  final var taskIds = new java.util.ArrayList<String>();
                  for (final var item : items) {
                    for (final String tag : item.getTags()) {
                      if (tag.startsWith("task-")) {
                        taskIds.add(tag.substring(5));
                      }
                    }
                  }
                  jobClient.newCompleteCommand(job).variables(Map.of("taskIds", taskIds)).send().join();
                  return;
                } else if (url.endsWith("/v2/expression/evaluation")) {
                  // stands in for the connector's resultExpression {pushEnabled: response.body.result = "true"}
                  jobClient.newCompleteCommand(job).variables(Map.of("pushEnabled", pushEnabled)).send().join();
                  return;
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
                  // a push notification to a destination: do the POST like the connector, and turn a failure into
                  // the BPMN error that the connector's errorExpression raises
                  try {
                    @SuppressWarnings("unchecked")
                    final Map<String, Object> headers = (Map<String, Object>) vars.get("headers");
                    final var request = java.net.http.HttpRequest.newBuilder(java.net.URI.create(url))
                        .timeout(java.time.Duration.ofSeconds(5))
                        .POST(java.net.http.HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
                    if (headers != null) {
                      headers.forEach((k, v) -> request.header(k, String.valueOf(v)));
                    }
                    final var response = java.net.http.HttpClient.newHttpClient()
                        .send(request.build(), java.net.http.HttpResponse.BodyHandlers.ofString());
                    if (response.statusCode() >= 400) {
                      throw new IllegalStateException("status " + response.statusCode());
                    }
                  } catch (final Exception e) {
                    jobClient.newThrowErrorCommand(job).errorCode("PUSH_FAILED").errorMessage(String.valueOf(e))
                        .send().join();
                    return;
                  }
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

  // ---- A2A conveniences used by the process tests ------------------------------------------

  static final String ALL_RESOURCES_NOTE = "see @TestDeployment on each test class";

  Map<String, Object> send(final String messageId, final String text) {
    return sendRaw(messageId, text, "");
  }

  /** extraMessageJson is spliced into the message object, for example ,"taskId":"t". */
  Map<String, Object> sendRaw(final String messageId, final String text, final String extraMessageJson) {
    return rpc(headers(), request("SendMessage", "{\"message\":{\"messageId\":\"" + messageId
        + "\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"" + text + "\"}]" + extraMessageJson + "}}"));
  }

  Map<String, Object> sendWith(final String messageId, final String configurationJson) {
    return rpc(headers(), request("SendMessage", "{\"message\":{\"messageId\":\"" + messageId
        + "\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}]},\"configuration\":" + configurationJson + "}"));
  }

  Map<String, Object> followUp(final String taskId, final String messageId, final String text) {
    return sendRaw(messageId, text, ",\"taskId\":\"" + taskId + "\"");
  }

  Map<String, Object> get(final String taskId) {
    return rpc(headers(), request("GetTask", "{\"id\":\"" + taskId + "\"}"));
  }

  Map<String, Object> get(final String taskId, final int historyLength) {
    return rpc(headers(), request("GetTask", "{\"id\":\"" + taskId + "\",\"historyLength\":" + historyLength + "}"));
  }

  Map<String, Object> list(final String paramsJson) {
    return rpc(headers(), request("ListTasks", paramsJson));
  }

  Map<String, Object> cancel(final String taskId) {
    return rpc(headers(), request("CancelTask", "{\"id\":\"" + taskId + "\"}"));
  }

  @SuppressWarnings("unchecked")
  static Map<String, Object> result(final Map<String, Object> response) {
    org.assertj.core.api.Assertions.assertThat(response).as("response %s", response).containsKey("result");
    return (Map<String, Object>) response.get("result");
  }

  /** The task of a SendMessage response ({"task": ...}). */
  @SuppressWarnings("unchecked")
  static Map<String, Object> task(final Map<String, Object> response) {
    return (Map<String, Object>) result(response).get("task");
  }

  /** The task of a GetTask or CancelTask response (a bare Task). */
  static Map<String, Object> bareTask(final Map<String, Object> response) {
    return result(response);
  }

  @SuppressWarnings("unchecked")
  static String state(final Map<String, Object> task) {
    return (String) ((Map<String, Object>) task.get("status")).get("state");
  }

  @SuppressWarnings("unchecked")
  static List<Map<String, Object>> history(final Map<String, Object> task) {
    final var h = (List<Map<String, Object>>) task.get("history");
    return h == null ? List.of() : h;
  }

  @SuppressWarnings("unchecked")
  static String statusText(final Map<String, Object> task) {
    final var message = (Map<String, Object>) ((Map<String, Object>) task.get("status")).get("message");
    return message == null ? null : (String) ((Map<String, Object>) ((List<?>) message.get("parts")).get(0)).get("text");
  }

  @SuppressWarnings("unchecked")
  static int errorCode(final Map<String, Object> response) {
    org.assertj.core.api.Assertions.assertThat(response).as("response %s", response).containsKey("error");
    return ((Number) ((Map<String, Object>) response.get("error")).get("code")).intValue();
  }
}
