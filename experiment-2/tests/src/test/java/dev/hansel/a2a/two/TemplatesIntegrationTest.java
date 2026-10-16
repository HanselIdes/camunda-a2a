package dev.hansel.a2a.two;

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
import java.util.HashMap;
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
        .addResourceFromClasspath("harness/h-server.bpmn")
        .addResourceFromClasspath("harness/h-push.bpmn").send().join();
    // inbound endpoints exist once the runtime picked up the deployment: GET on a POST webhook answers 405
    awaitEndpoint("/inbound/h-client-webhook");
    awaitEndpoint("/inbound/h-server");
    awaitEndpoint("/inbound/h-server-card");
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
      headers.forEach(builder::header);
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

  long agent(final String agentId) {
    final long key = start("h-server", Map.of("a2aAgentId", agentId));
    assertThat(ProcessInstanceSelectors.byKey(key)).hasActiveElements("Hold");
    return key;
  }

  @Test
  void agentCardIsServedFromTheInstanceTheAgentQueryNames() throws Exception {
    final long mine = agent("agent-card-1");
    final long other = agent("agent-card-2");
    final var response = HTTP.send(HttpRequest.newBuilder(
            URI.create(context.getConnectorsAddress() + "/inbound/h-server-card?agent=agent-card-1")).GET().build(),
        HttpResponse.BodyHandlers.ofString());
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(response.headers().firstValue("Content-Type").orElse("")).contains("application/json");
    final var card = json(response.body());
    assertThat(card.path("name").asText()).isEqualTo("Task agent");
    final var jsonRpc = card.path("supportedInterfaces").get(0);
    assertThat(jsonRpc.path("protocolBinding").asText()).isEqualTo("JSONRPC");
    assertThat(jsonRpc.path("protocolVersion").asText()).isEqualTo("1.0");
    assertThat(jsonRpc.path("url").asText()).isEqualTo("http://localhost:8080/inbound/a2a-server?agent=agent-card-1");
    assertThat(card.path("capabilities").path("pushNotifications").asBoolean()).isTrue();
    assertThat(card.path("skills")).isNotEmpty();

    assertThat(ProcessInstanceSelectors.byKey(mine)).hasCompletedElements("Card", "CardEnd");
    assertThat(ProcessInstanceSelectors.byKey(other)).hasNotActivatedElements("Card");
  }

  // A2A 1.0 Server: SendMessage (new task and follow-up) --------------------------------------------------------

  static String sendMessage(final String messageId, final String taskId, final String text) {
    final Map<String, Object> message = new HashMap<>();
    message.put("messageId", messageId);
    message.put("role", "ROLE_USER");
    message.put("parts", List.of(Map.of("text", text)));
    if (taskId != null) {
      message.put("taskId", taskId);
      message.put("contextId", "ctx-" + taskId);
    }
    final Map<String, Object> body = Map.of("jsonrpc", "2.0", "id", "req-" + messageId, "method", "SendMessage",
        "params", Map.of("message", message, "configuration", Map.of("returnImmediately", true,
            "taskPushNotificationConfig", Map.of("url", "http://client/reply/" + messageId, "token", TOKEN))));
    try {
      return RecordingServer.JSON.writeValueAsString(body);
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  @Test
  void newTaskStartsATaskEventSubProcessInTheAgentInstanceAndAnswersSubmitted() {
    final long key = agent("agent-task-1");
    final String messageId = "m-" + UUID.randomUUID();
    final var response = post("/inbound/h-server?agent=agent-task-1", sendMessage(messageId, null, "Convert 100"),
        Map.of("A2A-Version", "1.0"));
    assertThat(response.statusCode()).isEqualTo(200);
    final var rpc = json(response.body());
    assertThat(rpc.path("id").asText()).isEqualTo("req-" + messageId);
    final var task = rpc.path("result").path("task");
    assertThat(task.path("id").asText()).isEqualTo(messageId);
    assertThat(task.path("status").path("state").asText()).isEqualTo("TASK_STATE_SUBMITTED");

    final var instance = ProcessInstanceSelectors.byKey(key);
    assertThat(instance).hasCompletedElements("NewTask").hasActiveElements("Working", "Hold");
    assertThat(instance).hasLocalVariable("TaskSub", "taskId", messageId)
        .hasLocalVariable("TaskSub", "messageText", "Convert 100")
        .hasLocalVariable("TaskSub", "taskState", "TASK_STATE_SUBMITTED");
  }

  @Test
  void followUpReachesTheWaitingTaskAndBecomesToolCallResult() {
    final long key = agent("agent-task-2");
    final String messageId = "m-" + UUID.randomUUID();
    post("/inbound/h-server?agent=agent-task-2", sendMessage(messageId, null, "Convert 100"), Map.of());
    final var instance = ProcessInstanceSelectors.byKey(key);
    assertThat(instance).hasActiveElements("Working");
    context.completeUserTask("Working");
    assertThat(instance).hasActiveElements("FollowUp");

    final var response = post("/inbound/h-server?agent=agent-task-2",
        sendMessage("m-" + UUID.randomUUID(), messageId, "Celsius"), Map.of());
    final var task = json(response.body()).path("result").path("task");
    assertThat(task.path("id").asText()).isEqualTo(messageId);
    assertThat(task.path("status").path("state").asText()).isEqualTo("TASK_STATE_WORKING");

    assertThat(instance).hasCompletedElements("FollowUp").hasActiveElements("Answered");
    assertThat(instance).hasVariableSatisfies("toolCallResult", String.class, v -> assertThat(v).isEqualTo("Celsius"));
    // only one task event sub-process: the follow-up did not start a second one
    assertThat(instance).hasCompletedElement("NewTask", 1);
  }

  @Test
  void followUpForATaskThatIsNotWaitingStartsNothing() {
    final long key = agent("agent-task-3");
    final var response = post("/inbound/h-server?agent=agent-task-3",
        sendMessage("m-" + UUID.randomUUID(), "no-such-task", "hello"), Map.of());
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(ProcessInstanceSelectors.byKey(key)).hasNotActivatedElements("NewTask", "FollowUp");
  }

  @Test
  void otherMethodsGetAJsonRpcErrorAndStartNothing() {
    final long key = agent("agent-task-4");
    final var wrongMethod = post("/inbound/h-server?agent=agent-task-4",
        "{\"jsonrpc\":\"2.0\",\"id\":\"7\",\"method\":\"GetTask\",\"params\":{\"id\":\"x\"}}", Map.of());
    assertThat(json(wrongMethod.body()).path("error").path("code").asInt()).isEqualTo(-32601);
    final var noMessageId = post("/inbound/h-server?agent=agent-task-4",
        "{\"jsonrpc\":\"2.0\",\"id\":\"8\",\"method\":\"SendMessage\",\"params\":{\"message\":{\"parts\":[]}}}",
        Map.of());
    assertThat(json(noMessageId.body()).path("error").path("code").asInt()).isEqualTo(-32602);
    assertThat(ProcessInstanceSelectors.byKey(key)).hasNotActivatedElements("NewTask");
  }

  // A2A 1.0 Server: push task update ----------------------------------------------------------------------------

  @ParameterizedTest
  @ValueSource(strings = {"TASK_STATE_COMPLETED", "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_FAILED"})
  void pushPostsAStreamResponseWithTheNotificationToken(final String state) {
    final long key = start("h-push", Map.of("state", state, "text", "the answer", "taskId", "task-9",
        "contextId", "ctx-9", "pushNotification", Map.of("url", STUB.urlFromConnectors() + "/push", "token", TOKEN)));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted();
    final var request = STUB.requestsTo("/push").get(0);
    assertThat(request.method()).isEqualTo("POST");
    assertThat(request.header("X-A2A-Notification-Token")).isEqualTo(TOKEN);
    assertThat(request.header("Content-Type")).contains("application/json");
    final var task = request.json().path("task");
    assertThat(task.path("id").asText()).isEqualTo("task-9");
    assertThat(task.path("contextId").asText()).isEqualTo("ctx-9");
    assertThat(task.path("status").path("state").asText()).isEqualTo(state);
    final var message = task.path("status").path("message");
    assertThat(message.path("role").asText()).isEqualTo("ROLE_AGENT");
    assertThat(message.path("parts").get(0).path("text").asText()).isEqualTo("the answer");
  }

  @Test
  void pushReachesTheClientWebhookTemplate() {
    final String taskId = "rt-" + UUID.randomUUID();
    final long waiting = waitingClient(taskId);
    final long push = start("h-push", Map.of("state", "TASK_STATE_COMPLETED", "text", "done", "taskId", taskId,
        "contextId", "ctx", "pushNotification",
        Map.of("url", "http://localhost:8080/inbound/h-client-webhook", "token", TOKEN)));
    assertThat(ProcessInstanceSelectors.byKey(push)).isCompleted();
    assertThat(ProcessInstanceSelectors.byKey(waiting)).isCompleted();
    assertThat(variable(waiting, "toolCallResult").path("status").path("message").path("parts").get(0)
        .path("text").asText()).isEqualTo("done");
  }
}
