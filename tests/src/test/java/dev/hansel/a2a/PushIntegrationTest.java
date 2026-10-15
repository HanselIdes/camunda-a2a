package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/** Push notifications end to end with the real connectors: the HTTP JSON connector delivers to a host server. */
class PushIntegrationTest {
  record Hit(Map<String, List<String>> headers, Map<String, Object> body) {}

  static final List<Hit> HITS = new CopyOnWriteArrayList<>();
  static final HttpServer SERVER;

  static {
    try {
      SERVER = HttpServer.create(new InetSocketAddress("0.0.0.0", 0), 0);
      SERVER.createContext("/hook", exchange -> {
        final var body = new String(exchange.getRequestBody().readAllBytes());
        final var headers = new java.util.HashMap<String, List<String>>();
        exchange.getRequestHeaders().forEach((k, v) -> headers.put(k.toLowerCase(), v));
        HITS.add(new Hit(headers, Harness.map(body)));
        exchange.sendResponseHeaders(200, -1);
        exchange.close();
      });
      SERVER.start();
    } catch (final Exception e) {
      throw new ExceptionInInitializerError(e);
    }
  }

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://a2a.test")
      .withConnectorsSecret("A2A_PUSH_ENABLED", "true");

  static final HttpClient HTTP = HttpClient.newHttpClient();

  CamundaClient client;
  CamundaProcessTestContext context;
  String base;

  @BeforeEach
  void deployAndWait() {
    final var cmd = client.newDeployResourceCommand();
    for (final String r : List.of("bpmn/a2a-card.bpmn", "bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn",
        "bpmn/a2a-correlate.bpmn", "bpmn/a2a-publish-reply.bpmn", "bpmn/a2a-push-notify.bpmn",
        "bpmn/a2a-fetch-task.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn", "dmn/capitals.dmn")) {
      cmd.addResourceFromClasspath(r);
    }
    ((io.camunda.client.api.command.DeployResourceCommandStep1.DeployResourceCommandStep2) cmd).send().join();
    base = context.getConnectorsAddress().toString();
    HITS.clear();
    Awaitility.await().atMost(Duration.ofSeconds(90)).pollInterval(Duration.ofSeconds(1)).until(() -> {
      try {
        return HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a-card")).GET().build(),
            HttpResponse.BodyHandlers.ofString()).statusCode() == 200
            && HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a")).GET().build(),
                HttpResponse.BodyHandlers.ofString()).statusCode() == 405;
      } catch (final Exception e) {
        return false;
      }
    });
  }

  Map<String, Object> rpc(final String method, final String paramsJson) throws Exception {
    final var response = HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a"))
        .timeout(Duration.ofSeconds(60)).header("Content-Type", "application/json").header("A2A-Version", "1.0")
        .POST(HttpRequest.BodyPublishers.ofString("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"" + method
            + "\",\"params\":" + paramsJson + "}")).build(), HttpResponse.BodyHandlers.ofString());
    return Harness.map(response.body());
  }

  @Test
  void cardDeclaresPushAndDeliveryReachesTheHostWithTheConfiguredAuthentication() throws Exception {
    final var card = Harness.map(HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a-card")).GET().build(),
        HttpResponse.BodyHandlers.ofString()).body());
    @SuppressWarnings("unchecked")
    final var caps = (Map<String, Object>) card.get("capabilities");
    assertThat(caps).containsEntry("pushNotifications", true);

    final String hook = "http://host.docker.internal:" + SERVER.getAddress().getPort() + "/hook";
    final var first = Harness.task(rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-input-required-1\","
        + "\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}]},\"configuration\":{\"taskPushNotificationConfig\":"
        + "{\"url\":\"" + hook + "\",\"authentication\":{\"scheme\":\"Bearer\",\"credentials\":\"tok-1\"}}}}"));
    rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-complete-task-2\",\"role\":\"ROLE_USER\",\"taskId\":\""
        + first.get("id") + "\",\"parts\":[{\"text\":\"go\"}]}}");
    Awaitility.await().atMost(Duration.ofSeconds(30)).until(() -> HITS.size() >= 2);
    for (final Hit hit : HITS) {
      assertThat(hit.headers().get("authorization")).containsExactly("Bearer tok-1");
      assertThat(hit.headers().get("content-type").get(0)).startsWith("application/a2a+json");
      assertThat(hit.body()).containsKey("task");
    }
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }

  @Test
  void configurationOperationsWorkThroughTheRealConnectors() throws Exception {
    final String id = (String) Harness.task(rpc("SendMessage", "{\"message\":{\"messageId\":\"tck-complete-task-1\","
        + "\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}]}}")).get("id");
    final var created = Harness.result(rpc("CreateTaskPushNotificationConfig",
        "{\"task_id\":\"" + id + "\",\"id\":\"c1\",\"url\":\"http://example.test/hook\"}"));
    assertThat(created).containsEntry("id", "c1").containsEntry("taskId", id);
    assertThat((List<?>) Harness.result(rpc("ListTaskPushNotificationConfigs", "{\"task_id\":\"" + id + "\"}"))
        .get("configs")).hasSize(1);
    assertThat(Harness.result(rpc("DeleteTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c1\"}")))
        .isEmpty();
    assertThat(Harness.errorCode(rpc("GetTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c1\"}")))
        .isEqualTo(-32602);
  }
}
