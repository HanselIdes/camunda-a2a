package dev.hansel.a2a.three;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * Tier 2: each A2A 1.0 element template on its own, on the real connectors runtime. Every template is applied to a
 * one-purpose harness process in src/test/resources/harness. Outbound templates call a recording server in this
 * JVM; inbound templates are called over HTTP like an A2A peer would call them.
 */
class TemplatesIntegrationTest {
  static final RecordingServer STUB = new RecordingServer();
  static final String TOKEN = "test-push-token";
  static final HttpClient HTTP = HttpClient.newHttpClient();

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withConnectorsEnabled(true)
      .withConnectorsSecret("A2A_CONNECTORS_URL", "http://localhost:8080")
      .withConnectorsSecret("A2A_PUSH_TOKEN", TOKEN)
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://a2a.test")
      .withConnectorsSecret("A2A_PUSH_ENABLED", "true")
      // keep the harness deployments between tests: after a purge the connectors runtime has to register
      // every webhook again, which made endpoint readiness the slowest and flakiest part of each test
      .withDataDeletionMode(io.camunda.process.test.api.DataDeletionMode.NONE);
  static boolean deployed;

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deploy() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(60));
    STUB.requests.clear();
    STUB.routes.clear();
    if (deployed) {
      return;
    }
    deployed = true;
    client.newDeployResourceCommand().addResourceFromClasspath("harness/h-client-fetch.bpmn")
        .addResourceFromClasspath("harness/h-client-send.bpmn")
        .addResourceFromClasspath("harness/h-client-webhook.bpmn")
        .addResourceFromClasspath("harness/h-card.bpmn")
        .addResourceFromClasspath("harness/h-rpc.bpmn")
        .addResourceFromClasspath("harness/h-push.bpmn").send().join();
    // inbound endpoints exist once the runtime picked up the deployment: GET on a POST webhook answers 405
    awaitEndpoint("/inbound/h-client-webhook");
    awaitEndpoint("/inbound/h-rpc");
    awaitEndpoint("/inbound/h-card");
  }

  void awaitEndpoint(final String path) {
    Awaitility.await().atMost(Duration.ofSeconds(120)).pollInterval(Duration.ofSeconds(1)).until(() -> {
      try {
        return HTTP.send(HttpRequest.newBuilder(URI.create(context.getConnectorsAddress() + path)).GET().build(),
            HttpResponse.BodyHandlers.ofString()).statusCode() != 404;
      } catch (final Exception e) {
        return false;
      }
    });
  }

  long start(final String processId, final Map<String, Object> variables) {
    return client.newCreateInstanceCommand().bpmnProcessId(processId).latestVersion().variables(variables).send()
        .join().getProcessInstanceKey();
  }

  JsonNode variable(final long instance, final String name) {
    final var items = client.newVariableSearchRequest().filter(f -> f.processInstanceKey(instance).name(name)).send()
        .join().items();
    assertThat(items).as("variable " + name).isNotEmpty();
    try {
      return RecordingServer.JSON.readTree(items.get(0).getValue());
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  HttpResponse<String> post(final String path, final String body, final Map<String, String> headers) {
    try {
      final var builder = HttpRequest.newBuilder(URI.create(context.getConnectorsAddress() + path))
          .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
      headers.forEach(builder::setHeader);
      return HTTP.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  JsonNode json(final String body) {
    try {
      return RecordingServer.JSON.readTree(body);
    } catch (final Exception e) {
      throw new IllegalStateException(body, e);
    }
  }

  static String task(final String id, final String state) {
    return "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"result\":{\"task\":{\"id\":\"" + id + "\",\"contextId\":\"ctx\","
        + "\"status\":{\"state\":\"" + state + "\"}}}}";
  }

  // A2A 1.0 Client ----------------------------------------------------------------------------------------------

  @Test
  void clientFetchesTheAgentCardFromTheDefaultLocation() {
    STUB.routes.put("/.well-known/agent-card.json",
        r -> new RecordingServer.Response(200, "{\"name\":\"Stub agent\",\"supportedInterfaces\":[]}"));
    final long key = start("h-client-fetch", Map.of("stubUrl", STUB.urlFromConnectors(),
        "cardPath", ".well-known/agent-card.json"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    final var request = STUB.requestsTo("/.well-known/agent-card.json").get(0);
    assertThat(request.method()).isEqualTo("GET");
    assertThat(request.header("A2A-Version")).isEqualTo("1.0");
    assertThat(variable(key, "agentResponse").path("result").path("name").asText()).isEqualTo("Stub agent");
  }

  @Test
  void clientFetchesTheAgentCardFromACustomLocationWithTheAgentQuery() {
    STUB.routes.put("/a2a-server-card", r -> new RecordingServer.Response(200, "{\"name\":\"Custom\"}"));
    final long key = start("h-client-fetch", Map.of("stubUrl", STUB.urlFromConnectors(),
        "cardPath", "a2a-server-card?agent=agent-42"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    assertThat(STUB.requestsTo("/a2a-server-card").get(0).query()).isEqualTo("agent=agent-42");
    assertThat(variable(key, "agentResponse").path("result").path("name").asText()).isEqualTo("Custom");
  }

  @Test
  void clientSendsANewTaskWithAPushNotificationConfig() {
    STUB.routes.put("/rpc", r -> new RecordingServer.Response(200, task("remote-1", "TASK_STATE_SUBMITTED")));
    final long key = start("h-client-send", Map.of("stubUrl", STUB.urlFromConnectors(), "text", "Hello agent",
        "webhookUrl", "http://client/reply"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();

    final var request = STUB.requestsTo("/rpc").get(0);
    assertThat(request.method()).isEqualTo("POST");
    assertThat(request.header("A2A-Version")).isEqualTo("1.0");
    final var body = request.json();
    assertThat(body.path("jsonrpc").asText()).isEqualTo("2.0");
    assertThat(body.path("method").asText()).isEqualTo("SendMessage");
    final var message = body.path("params").path("message");
    assertThat(message.path("role").asText()).isEqualTo("ROLE_USER");
    assertThat(message.path("parts").get(0).path("text").asText()).isEqualTo("Hello agent");
    assertThat(message.path("messageId").asText()).isNotBlank();
    assertThat(message.has("taskId")).as("no taskId on a new task").isFalse();
    final var config = body.path("params").path("configuration");
    assertThat(config.path("returnImmediately").asBoolean()).isTrue();
    assertThat(config.path("taskPushNotificationConfig").path("url").asText()).isEqualTo("http://client/reply");
    assertThat(config.path("taskPushNotificationConfig").path("token").asText()).isEqualTo(TOKEN);

    final var response = variable(key, "agentResponse");
    assertThat(response.path("result").path("id").asText()).isEqualTo("remote-1");
    assertThat(response.path("error").isNull() || response.path("error").isMissingNode()).isTrue();
  }

  @Test
  void clientContinuesATaskWithTaskIdAndContextIdAndWithoutPush() {
    STUB.routes.put("/rpc", r -> new RecordingServer.Response(200, task("remote-1", "TASK_STATE_COMPLETED")));
    final long key = start("h-client-send", Map.of("stubUrl", STUB.urlFromConnectors(), "text", "Celsius",
        "remoteTaskId", "remote-1", "remoteContextId", "ctx-1"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    final var body = STUB.requestsTo("/rpc").get(0).json();
    assertThat(body.path("params").path("message").path("taskId").asText()).isEqualTo("remote-1");
    assertThat(body.path("params").path("message").path("contextId").asText()).isEqualTo("ctx-1");
    assertThat(body.path("params").path("configuration").path("returnImmediately").asBoolean()).isFalse();
    assertThat(body.path("params").path("configuration").has("taskPushNotificationConfig")).isFalse();
    assertThat(variable(key, "agentResponse").path("result").path("status").path("state").asText())
        .isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void clientUsesTheJsonRpcUrlFromTheAgentCardWhenSet() {
    STUB.routes.put("/from-card", r -> new RecordingServer.Response(200, task("remote-2", "TASK_STATE_SUBMITTED")));
    final long key = start("h-client-send", Map.of("stubUrl", "http://unused.invalid", "text", "Hi",
        "rpcUrl", STUB.urlFromConnectors() + "/from-card?agent=a1"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    assertThat(STUB.requestsTo("/from-card").get(0).query()).isEqualTo("agent=a1");
  }

  @Test
  void clientMapsAJsonRpcErrorIntoTheResult() {
    STUB.routes.put("/rpc", r -> new RecordingServer.Response(200,
        "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"error\":{\"code\":-32601,\"message\":\"Method not found\"}}"));
    final long key = start("h-client-send", Map.of("stubUrl", STUB.urlFromConnectors(), "text", "Hi"));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    final var response = variable(key, "agentResponse");
    assertThat(response.path("error").path("code").asInt()).isEqualTo(-32601);
    assertThat(response.path("result").isNull()).isTrue();
  }

  @Test
  void clientRaisesAnIncidentWhenTheServerFails() {
    STUB.routes.put("/rpc", r -> new RecordingServer.Response(500, "{\"oops\":true}"));
    final long key = start("h-client-send", Map.of("stubUrl", STUB.urlFromConnectors(), "text", "Hi"));
    assertThat(ProcessInstanceSelectors.byKey(key)).hasActiveIncidents();
  }

  // A2A 1.0 Client Webhook --------------------------------------------------------------------------------------

  long waitingClient(final String taskId) {
    final long key = start("h-client-webhook", Map.of("agentResponse", Map.of("result", Map.of("id", taskId))));
    assertThat(ProcessInstanceSelectors.byKey(key)).hasActiveElements("Replied");
    return key;
  }

  static String pushTask(final String taskId, final String state) {
    return "{\"task\":{\"id\":\"" + taskId + "\",\"contextId\":\"ctx\",\"status\":{\"state\":\"" + state + "\"}}}";
  }

  @ParameterizedTest
  @ValueSource(strings = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED",
      "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"})
  void clientWebhookWakesUpOnFinalAndInterruptedStates(final String state) {
    final String taskId = "t-" + UUID.randomUUID();
    final long key = waitingClient(taskId);
    final var response = post("/inbound/h-client-webhook", pushTask(taskId, state),
        Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(response.statusCode()).isBetween(200, 299);
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    final var result = variable(key, "toolCallResult");
    assertThat(result.path("id").asText()).isEqualTo(taskId);
    assertThat(result.path("status").path("state").asText()).isEqualTo(state);
  }

  @Test
  void clientWebhookCorrelatesOnTheTaskIdOfAMessageReply() {
    // a follow-up's reply is a Message: the client waits on its taskId, since a Message's own id is the messageId
    final String taskId = "t-" + UUID.randomUUID();
    final long key = start("h-client-webhook", Map.of("agentResponse",
        Map.of("result", Map.of("messageId", "reply-m1", "role", "ROLE_AGENT", "taskId", taskId))));
    assertThat(ProcessInstanceSelectors.byKey(key)).hasActiveElements("Replied");
    post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_COMPLETED"),
        Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
  }

  @Test
  void clientWebhookAcceptsAStatusUpdatePayload() {
    final String taskId = "t-" + UUID.randomUUID();
    final long key = waitingClient(taskId);
    post("/inbound/h-client-webhook", "{\"statusUpdate\":{\"taskId\":\"" + taskId + "\",\"contextId\":\"ctx\","
        + "\"status\":{\"state\":\"TASK_STATE_COMPLETED\"}}}", Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
  }

  @ParameterizedTest
  @ValueSource(strings = {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"})
  void clientWebhookKeepsWaitingWhileTheTaskRuns(final String state) {
    final String taskId = "t-" + UUID.randomUUID();
    final long key = waitingClient(taskId);
    post("/inbound/h-client-webhook", pushTask(taskId, state), Map.of("X-A2A-Notification-Token", TOKEN));
    // then a final state proves the event was still waiting, not completed by the earlier push
    post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_COMPLETED"),
        Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    assertThat(variable(key, "toolCallResult").path("status").path("state").asText())
        .isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void aPushThatArrivesBeforeTheClientWaitsIsKeptForTheMessageTtl() {
    // a fast server can push before the send task has returned and the webhook event is waiting
    final String taskId = "early-" + UUID.randomUUID();
    final var response = post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_COMPLETED"),
        Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(response.statusCode()).isBetween(200, 299);
    final long key = start("h-client-webhook", Map.of("agentResponse", Map.of("result", Map.of("id", taskId))));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    assertThat(variable(key, "toolCallResult").path("status").path("state").asText()).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void clientWebhookIgnoresAWrongOrMissingToken() {
    final String taskId = "t-" + UUID.randomUUID();
    final long key = waitingClient(taskId);
    post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_FAILED"),
        Map.of("X-A2A-Notification-Token", "wrong"));
    post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_FAILED"), Map.of());
    post("/inbound/h-client-webhook", pushTask(taskId, "TASK_STATE_COMPLETED"),
        Map.of("X-A2A-Notification-Token", TOKEN));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    assertThat(variable(key, "toolCallResult").path("status").path("state").asText())
        .isEqualTo("TASK_STATE_COMPLETED");
  }

  // A2A 1.0 Server: Agent Card ----------------------------------------------------------------------------------

  HttpResponse<String> get(final String path) throws Exception {
    return HTTP.send(HttpRequest.newBuilder(URI.create(context.getConnectorsAddress() + path)).GET().build(),
        HttpResponse.BodyHandlers.ofString());
  }

  @Test
  void agentCardIsServedOnGetWithTheConfiguredEndpointAndCapabilities() throws Exception {
    final var response = get("/inbound/h-card");
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(response.headers().firstValue("Content-Type").orElse("")).contains("application/json");
    assertThat(response.headers().firstValue("Cache-Control").orElse("")).contains("max-age");
    final var card = json(response.body());
    assertThat(card.path("name").asText()).isEqualTo("Task agent");
    assertThat(card.path("version").asText()).isEqualTo("1.0.0");
    final var jsonRpc = card.path("supportedInterfaces").get(0);
    assertThat(jsonRpc.path("protocolBinding").asText()).isEqualTo("JSONRPC");
    assertThat(jsonRpc.path("protocolVersion").asText()).isEqualTo("1.0");
    assertThat(jsonRpc.path("url").asText()).isEqualTo("http://a2a.test/a2a");
    assertThat(card.path("capabilities").path("pushNotifications").asBoolean()).isTrue();
    assertThat(card.path("capabilities").path("streaming").asBoolean()).isFalse();
    assertThat(card.path("skills").get(0).path("id").asText()).isEqualTo("answer");
    assertThat(card.path("defaultInputModes").get(0).asText()).isEqualTo("text/plain");
    // the editable card part and the protocol part merge into one card, with no wrapper keys left over
    assertThat(card.has("card")).isFalse();
    assertThat(card.has("response")).isFalse();
  }

  @Test
  void everyCardRequestStartsOneRunOfTheCardProcess() throws Exception {
    final int before = client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("h-card")).send()
        .join().items().size();
    get("/inbound/h-card");
    get("/inbound/h-card");
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> assertThat(
        client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("h-card")).send().join().items())
        .hasSize(before + 2));
  }

  // A2A 1.0 Server: JSON-RPC endpoint ---------------------------------------------------------------------------

  @Test
  void rpcEndpointWaitsForTheRunAndReturnsRpcResponseAsTheBody() {
    final var response = post("/inbound/h-rpc", "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"Probe\",\"params\":{}}",
        Map.of("A2A-Version", "1.0"));
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(response.headers().firstValue("Content-Type").orElse("")).contains("application/json");
    final var body = json(response.body());
    assertThat(body.path("jsonrpc").asText()).isEqualTo("2.0");
    assertThat(body.path("id").asInt()).isEqualTo(5);
    // rpc is the request body and hdr the headers, lower-cased
    assertThat(body.path("result").path("method").asText()).isEqualTo("Probe");
    assertThat(body.path("result").path("version").asText()).isEqualTo("1.0");
    assertThat(body.path("result").path("contentType").asText()).contains("application/json");
  }

  @Test
  void rpcEndpointAcceptsTheA2aMediaType() {
    final var response = post("/inbound/h-rpc", "{\"jsonrpc\":\"2.0\",\"id\":6,\"method\":\"Probe\",\"params\":{}}",
        Map.of("Content-Type", "application/a2a+json"));
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(json(response.body()).path("result").path("method").asText()).isEqualTo("Probe");
  }

  @Test
  void rpcEndpointOnlyTakesPost() throws Exception {
    assertThat(get("/inbound/h-rpc").statusCode()).isEqualTo(405);
  }

  // A2A 1.0 Server: push task update ----------------------------------------------------------------------------

  static Map<String, Object> pushPayload(final String taskId, final String state) {
    return Map.of("task", Map.of("id", taskId, "contextId", "ctx-" + taskId,
        "status", Map.of("state", state, "message", Map.of("messageId", "m-" + taskId, "role", "ROLE_AGENT",
            "parts", List.of(Map.of("text", "the answer"))))));
  }

  @Test
  void pushPostsTheStreamResponseWithTokenAndAuthorization() {
    final var config = Map.of("url", STUB.urlFromConnectors() + "/push", "token", TOKEN,
        "authentication", Map.of("scheme", "Bearer", "credentials", "abc123"));
    final long key = start("h-push", Map.of("config", config, "payload", pushPayload("task-9", "TASK_STATE_COMPLETED")));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted().hasCompletedElements("End");
    final var request = STUB.requestsTo("/push").get(0);
    assertThat(request.method()).isEqualTo("POST");
    assertThat(request.header("X-A2A-Notification-Token")).isEqualTo(TOKEN);
    assertThat(request.header("Authorization")).isEqualTo("Bearer abc123");
    assertThat(request.header("Content-Type")).contains("application/a2a+json");
    final var task = request.json().path("task");
    assertThat(task.path("id").asText()).isEqualTo("task-9");
    assertThat(task.path("status").path("state").asText()).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(task.path("status").path("message").path("parts").get(0).path("text").asText()).isEqualTo("the answer");
  }

  @Test
  void pushWithoutTokenAndAuthenticationSendsNeitherHeader() {
    final long key = start("h-push", Map.of("config", Map.of("url", STUB.urlFromConnectors() + "/push"),
        "payload", pushPayload("task-10", "TASK_STATE_INPUT_REQUIRED")));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted().hasCompletedElements("End");
    final var request = STUB.requestsTo("/push").get(0);
    assertThat(request.header("X-A2A-Notification-Token")).isNull();
    assertThat(request.header("Authorization")).isNull();
  }

  @Test
  void aDeliveryThatFailsEndsAtTheErrorBoundaryInsteadOfRaisingAnIncident() {
    STUB.routes.put("/push", r -> new RecordingServer.Response(500, "{}"));
    final long key = start("h-push", Map.of("config", Map.of("url", STUB.urlFromConnectors() + "/push"),
        "payload", pushPayload("task-11", "TASK_STATE_COMPLETED")));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted().hasCompletedElements("GaveUp");
    assertThat(STUB.requestsTo("/push")).isNotEmpty();
  }

  @Test
  void pushReachesTheClientWebhookTemplateAsTheA2aMediaType() {
    final String taskId = "rt-" + UUID.randomUUID();
    final long waiting = waitingClient(taskId);
    final var config = Map.of("url", "http://localhost:8080/inbound/h-client-webhook", "token", TOKEN);
    final long push = start("h-push", Map.of("config", config, "payload", pushPayload(taskId, "TASK_STATE_COMPLETED")));
    assertThat(ProcessInstanceSelectors.byKey(push)).isCompleted().hasCompletedElements("End");
    assertThat(ProcessInstanceSelectors.byKey(waiting)).isCompleted();
    assertThat(variable(waiting, "toolCallResult").path("status").path("message").path("parts").get(0)
        .path("text").asText()).isEqualTo("the answer");
  }
}
