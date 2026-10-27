package dev.hansel.a2a.three;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.ActivatedJob;
import io.camunda.client.api.worker.JobClient;
import io.camunda.process.test.api.CamundaProcessTestContext;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Stands in for the HTTP JSON connector in process tests. Every job of type io.camunda:http-json:1 is sent as the
 * real HTTP request to the test engine's REST API (secrets resolved like the connectors runtime does), and the
 * element's own resultExpression is evaluated by the engine on the real response. So the processes run against the
 * real search API, including its lag behind writes. The few outside calls are a stub (the Tech Stuff tool) or a real
 * POST (push deliveries).
 */
final class Harness {
  static final ObjectMapper JSON = new ObjectMapper();
  static final String HTTP_JSON = "io.camunda:http-json:1";
  /** The scripted stand-in for the agent that most process tests run against, like the TCK. */
  static final String FIXTURE = "a2a-tck-fixture";
  static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

  final CamundaClient client;
  final CamundaProcessTestContext context;
  final String rest;
  /** "METHOD path" of every HTTP call, in order. */
  final List<String> calls = new CopyOnWriteArrayList<>();
  /** Whether the simulated deployment has the A2A_PUSH_ENABLED secret set to true. */
  volatile boolean pushEnabled;
  /** The process the endpoint starts for a new task (secret A2A_AGENT_PROCESS). */
  volatile String agentProcess = FIXTURE;
  /** Runs before each engine call with "METHOD path", so a test can change engine state at that exact moment. */
  volatile java.util.function.Consumer<String> beforeEngineCall = call -> {};
  volatile java.util.function.BiFunction<String, Integer, Integer> afterEngineStatus = (call, status) -> status;
  volatile java.util.function.BiFunction<String, Object, Object> afterEngineResponse = (call, body) -> body;

  Harness(final CamundaClient client, final CamundaProcessTestContext context) {
    this.client = client;
    this.context = context;
    final String address = context.getCamundaRestAddress().toString();
    this.rest = address.endsWith("/") ? address.substring(0, address.length() - 1) : address;
    context.mockJobWorker(HTTP_JSON).withHandler(this::handle);
  }

  private String secrets(final String s) {
    return s.replace("{{secrets.ENGINE_URL}}", rest)
        .replace("{{secrets.A2A_AGENT_PROCESS}}", agentProcess)
        .replace("{{secrets.A2A_PUSH_ENABLED}}", String.valueOf(pushEnabled));
  }

  private void handle(final JobClient jobClient, final ActivatedJob job) {
    try {
      final Map<String, Object> vars = job.getVariablesAsMap();
      final String url = secrets(String.valueOf(vars.get("url")));
      final String method = String.valueOf(vars.getOrDefault("method", "POST")).toUpperCase();
      final Object body = stripNulls(vars.get("body"));
      calls.add(method + " " + (url.startsWith(rest) ? url.substring(rest.length()) : url));
      if (url.startsWith("https://api.restful-api.dev/")) {
        // the Tech Stuff tool and its resultExpression {toolCallResult: response.body}
        jobClient.newCompleteCommand(job).variables(Map.of("toolCallResult", List.of(
            Map.of("id", "1", "name", "Apple iPhone 12 Pro Max"),
            Map.of("id", "2", "name", "Samsung Galaxy Z Fold2")))).send().join();
        return;
      }
      if (!url.startsWith(rest)) {
        deliver(jobClient, job, url, vars, body);
        return;
      }
      beforeEngineCall.accept(method + " " + url.substring(rest.length()));
      final var request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(30))
          .header("Content-Type", "application/json");
      final String payload = body == null ? null : secrets(JSON.writeValueAsString(body));
      request.method(method, payload == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(payload));
      final var response = HTTP.send(request.build(), HttpResponse.BodyHandlers.ofString());
      final int status = afterEngineStatus.apply(method + " " + url.substring(rest.length()), response.statusCode());
      if (status >= 400) {
        // the errorExpression shared by the engine calls: 404 and 409 become BPMN errors, anything else fails
        final String code = status == 404 ? "NOT_FOUND" : status == 409 ? "CONFLICT" : null;
        if (code != null && job.getCustomHeaders().containsKey("errorExpression")) {
          jobClient.newThrowErrorCommand(job).errorCode(code).errorMessage(response.body()).send().join();
        } else {
          jobClient.newFailCommand(job).retries(0).errorMessage(status + " " + response.body()).send().join();
        }
        return;
      }
      final Object responseBody = afterEngineResponse.apply(method + " " + url.substring(rest.length()),
          response.body() == null || response.body().isBlank() ? null : JSON.readValue(response.body(), Object.class));
      final String resultExpression = job.getCustomHeaders().get("resultExpression");
      final var complete = jobClient.newCompleteCommand(job);
      if (resultExpression != null && !resultExpression.isBlank()) {
        final Map<String, Object> responseVar = new LinkedHashMap<>();
        responseVar.put("status", status);
        responseVar.put("body", responseBody);
        final Object result = evaluate(resultExpression, Map.of("response", responseVar));
        if (result instanceof Map<?, ?> m && !m.isEmpty()) {
          @SuppressWarnings("unchecked")
          final Map<String, Object> variables = (Map<String, Object>) m;
          complete.variables(variables);
        }
      }
      complete.send().join();
    } catch (final Exception e) {
      jobClient.newFailCommand(job).retries(0).errorMessage(String.valueOf(e)).send().join();
    }
  }

  /** A push notification to a destination: the POST the push template makes, failures become PUSH_FAILED. */
  private void deliver(final JobClient jobClient, final ActivatedJob job, final String url, final Map<String, Object> vars,
      final Object body) {
    try {
      @SuppressWarnings("unchecked")
      final Map<String, Object> headers = (Map<String, Object>) vars.get("headers");
      final var request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(5))
          .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(body)));
      if (headers != null) {
        headers.forEach((k, v) -> request.header(k, String.valueOf(v)));
      }
      final var response = HTTP.send(request.build(), HttpResponse.BodyHandlers.ofString());
      if (response.statusCode() >= 400) {
        throw new IllegalStateException("status " + response.statusCode());
      }
      jobClient.newCompleteCommand(job).send().join();
    } catch (final Exception e) {
      jobClient.newThrowErrorCommand(job).errorCode("PUSH_FAILED").errorMessage(String.valueOf(e)).send().join();
    }
  }

  /** Evaluates a FEEL expression with the engine, the way the connectors runtime evaluates result expressions. */
  Object evaluate(final String expression, final Map<String, Object> variables) throws Exception {
    final String payload = JSON.writeValueAsString(Map.of("expression", expression, "variables", variables));
    final var response = HTTP.send(HttpRequest.newBuilder(URI.create(rest + "/v2/expression/evaluation"))
        .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(payload)).build(),
        HttpResponse.BodyHandlers.ofString());
    if (response.statusCode() >= 400) {
      throw new IllegalStateException("expression evaluation failed: " + response.body());
    }
    return map(response.body()).get("result");
  }

  @SuppressWarnings("unchecked")
  private static Object stripNulls(final Object value) {
    if (value instanceof Map<?, ?> m) {
      final Map<String, Object> out = new LinkedHashMap<>();
      ((Map<String, Object>) m).forEach((k, v) -> {
        if (v != null) {
          out.put(k, stripNulls(v));
        }
      });
      return out;
    }
    if (value instanceof List<?> l) {
      return l.stream().map(Harness::stripNulls).toList();
    }
    return value;
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
            .requestTimeout(Duration.ofSeconds(60))
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
