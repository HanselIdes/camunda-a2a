package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * The real connectors runtime: the HTTP Webhook inbound connector receives the requests and the HTTP JSON
 * connector calls the engine REST API. Kept apart from the mocked tests, because the real worker would
 * compete with the mocks.
 */
class WebhookIntegrationTest {
  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://a2a.test");

  static final HttpClient HTTP = HttpClient.newHttpClient();

  String base;
  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deployAndWait() {
    final var cmd = client.newDeployResourceCommand();
    for (final String r : List.of("bpmn/a2a-card.bpmn", "bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn",
        "bpmn/a2a-correlate.bpmn", "bpmn/a2a-publish-reply.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn",
        "dmn/capitals.dmn")) {
      cmd.addResourceFromClasspath(r);
    }
    ((io.camunda.client.api.command.DeployResourceCommandStep1.DeployResourceCommandStep2) cmd).send().join();
    base = context.getConnectorsAddress().toString();
    Awaitility.await().atMost(Duration.ofSeconds(90)).pollInterval(Duration.ofSeconds(1)).until(
        () -> get(base + "/inbound/a2a-card").statusCode() == 200 && post("{}", "application/json").statusCode() != 404);
  }

  static HttpResponse<String> get(final String url) throws Exception {
    return HTTP.send(HttpRequest.newBuilder(URI.create(url)).GET().build(), HttpResponse.BodyHandlers.ofString());
  }

  HttpResponse<String> post(final String body, final String contentType) throws Exception {
    return HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a")).timeout(Duration.ofSeconds(60))
        .header("Content-Type", contentType).header("A2A-Version", "1.0")
        .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
  }

  Map<String, Object> rpc(final String method, final String paramsJson) throws Exception {
    final var response = post("{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"" + method + "\",\"params\":" + paramsJson + "}",
        "application/json");
    assertThat(response.statusCode()).isEqualTo(200);
    assertThat(response.headers().firstValue("content-type").orElse("")).startsWith("application/json");
    return Harness.map(response.body());
  }

  @Test
  void agentCardIsServedWithThePublicUrlAndTheToolSkills() throws Exception {
    final var response = get(base + "/inbound/a2a-card");
    assertThat(response.headers().firstValue("content-type").orElse("")).startsWith("application/json");
    final var card = Harness.map(response.body());
    @SuppressWarnings("unchecked")
    final var interfaces = (List<Map<String, Object>>) card.get("supportedInterfaces");
    assertThat(interfaces).containsExactly(
        Map.of("url", "http://a2a.test/a2a", "protocolBinding", "JSONRPC", "protocolVersion", "1.0"));
    @SuppressWarnings("unchecked")
    final var skills = (List<Map<String, Object>>) card.get("skills");
    assertThat(skills).extracting(s -> s.get("id")).containsExactly("get_current_time", "convert_temperature", "capital_of");
  }

  @Test
  void sendMessageGetTaskAndCancelRoundTripThroughTheRealConnectors() throws Exception {
    final var sent = rpc("SendMessage",
        "{\"message\":{\"messageId\":\"tck-input-required-1\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"hi\"}]}}");
    assertThat(sent).containsEntry("id", 7);
    final var task = Harness.task(sent);
    assertThat(Harness.state(task)).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    final String id = (String) task.get("id");

    final var got = rpc("GetTask", "{\"id\":\"" + id + "\"}");
    assertThat(Harness.state(Harness.bareTask(got))).isEqualTo("TASK_STATE_INPUT_REQUIRED");

    final var done = rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-complete-task-2\",\"role\":\"ROLE_USER\","
        + "\"taskId\":\"" + id + "\",\"parts\":[{\"text\":\"go\"}]}}");
    assertThat(Harness.state(Harness.task(done))).isEqualTo("TASK_STATE_COMPLETED");

    final var cancel = rpc("CancelTask", "{\"id\":\"" + id + "\"}");
    assertThat(Harness.errorCode(cancel)).isEqualTo(-32002);
  }

  @Test
  void unknownTaskIsNotFoundBecauseTheEngineAnswers404ToTheCorrelation() throws Exception {
    assertThat(Harness.errorCode(rpc("GetTask", "{\"id\":\"missing\"}"))).isEqualTo(-32001);
  }

  @Test
  void validationErrorsAndCapabilityErrorsComeBackAsJsonRpcErrors() throws Exception {
    assertThat(Harness.errorCode(rpc("Nope", "{}"))).isEqualTo(-32601);
    assertThat(Harness.errorCode(rpc("SendStreamingMessage", "{}"))).isEqualTo(-32004);
    assertThat(Harness.errorCode(rpc("CreateTaskPushNotificationConfig", "{}"))).isEqualTo(-32003);
    final var wrongType = post("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"GetTask\",\"params\":{\"id\":\"t\"}}", "text/plain");
    assertThat(Harness.errorCode(Harness.map(wrongType.body()))).isEqualTo(-32005);
  }

  @Test
  void followUpImmediatelyAfterInputRequiredDoesNotRace() throws Exception {
    for (int i = 0; i < 3; i++) {
      final var first = Harness.task(rpc("SendMessage",
          "{\"message\":{\"messageId\":\"tck-input-required-" + i + "\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}]}}"));
      final var second = rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-complete-task-" + i
          + "\",\"role\":\"ROLE_USER\",\"taskId\":\"" + first.get("id") + "\",\"parts\":[{\"text\":\"y\"}]}}");
      assertThat(Harness.state(Harness.task(second))).isEqualTo("TASK_STATE_COMPLETED");
    }
  }

  @Test
  void noIncidentsAfterTheRequests() throws Exception {
    rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-complete-task-1\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}]}}");
    rpc("GetTask", "{\"id\":\"missing\"}");
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }
}
