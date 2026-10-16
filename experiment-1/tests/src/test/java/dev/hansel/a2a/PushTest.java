package dev.hansel.a2a;

import static dev.hansel.a2a.Harness.bareTask;
import static dev.hansel.a2a.Harness.errorCode;
import static dev.hansel.a2a.Harness.result;
import static dev.hansel.a2a.Harness.state;
import static dev.hansel.a2a.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Push notification configuration and delivery, enabled by the A2A_PUSH_ENABLED secret. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn", "bpmn/a2a-correlate.bpmn",
    "bpmn/a2a-publish-reply.bpmn", "bpmn/a2a-push-notify.bpmn", "bpmn/a2a-fetch-task.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn",
    "dmn/capitals.dmn"})
class PushTest {
  record Hit(Map<String, List<String>> headers, Map<String, Object> body) {}

  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;
  HttpServer server;
  final List<Hit> hits = new CopyOnWriteArrayList<>();
  String hook;

  @BeforeEach
  void setUp() throws Exception {
    h = new Harness(client, context);
    h.pushEnabled = true;
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/hook", exchange -> {
      final var body = new String(exchange.getRequestBody().readAllBytes());
      final var headers = new java.util.HashMap<String, List<String>>();
      exchange.getRequestHeaders().forEach((k, v) -> headers.put(k.toLowerCase(), v));
      hits.add(new Hit(headers, Harness.map(body)));
      exchange.sendResponseHeaders(200, -1);
      exchange.close();
    });
    server.start();
    hook = "http://127.0.0.1:" + server.getAddress().getPort() + "/hook";
  }

  @AfterEach
  void tearDown() {
    server.stop(0);
  }

  Map<String, Object> pushCall(final String method, final String paramsJson) {
    return h.rpc(Harness.headers(), Harness.request(method, paramsJson));
  }

  @Test
  void configurationOperationsWorkOnCompletedAndWaitingTasks() {
    for (final String first : List.of("tck-complete-task-1", "tck-input-required-1")) {
      final String id = (String) task(h.send(first, "x")).get("id");
      final var created = result(pushCall("CreateTaskPushNotificationConfig",
          "{\"task_id\":\"" + id + "\",\"id\":\"cfg-1\",\"url\":\"" + hook + "\"}"));
      assertThat(created).containsEntry("id", "cfg-1").containsEntry("taskId", id).containsEntry("url", hook);

      final var generated = result(pushCall("CreateTaskPushNotificationConfig",
          "{\"task_id\":\"" + id + "\",\"url\":\"" + hook + "\"}"));
      assertThat((String) generated.get("id")).isNotBlank().isNotEqualTo("cfg-1");

      assertThat(result(pushCall("GetTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"cfg-1\"}")))
          .containsEntry("url", hook);
      final var listed = result(pushCall("ListTaskPushNotificationConfigs", "{\"task_id\":\"" + id + "\"}"));
      assertThat((List<?>) listed.get("configs")).hasSize(2);
      assertThat(listed).containsEntry("nextPageToken", "");

      assertThat(result(pushCall("DeleteTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"cfg-1\"}")))
          .isEmpty();
      assertThat(errorCode(pushCall("GetTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"cfg-1\"}")))
          .isEqualTo(-32602);
      assertThat(result(pushCall("DeleteTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"cfg-1\"}")))
          .as("delete is idempotent").isEmpty();
      assertThat((List<?>) result(pushCall("ListTaskPushNotificationConfigs", "{\"task_id\":\"" + id + "\"}"))
          .get("configs")).hasSize(1);
    }
  }

  @Test
  void invalidAndUnknownTargetsAreErrors() {
    final String id = (String) task(h.send("tck-complete-task-1", "x")).get("id");
    assertThat(errorCode(pushCall("CreateTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\"}"))).isEqualTo(-32602);
    assertThat(errorCode(pushCall("CreateTaskPushNotificationConfig", "{\"url\":\"" + hook + "\"}"))).isEqualTo(-32602);
    assertThat(errorCode(pushCall("ListTaskPushNotificationConfigs", "{\"task_id\":\"missing\"}"))).isEqualTo(-32001);
  }

  @Test
  void operationsAreRefusedWhenTheSecretDisablesPush() {
    h.pushEnabled = false;
    assertThat(errorCode(pushCall("ListTaskPushNotificationConfigs", "{\"task_id\":\"t\"}"))).isEqualTo(-32003);
  }

  @Test
  void configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange() {
    final String params = "{\"message\":{\"messageId\":\"tck-input-required-1\",\"role\":\"ROLE_USER\","
        + "\"parts\":[{\"text\":\"x\"}]},\"configuration\":{\"taskPushNotificationConfig\":{\"id\":\"c1\",\"url\":\""
        + hook + "\",\"authentication\":{\"scheme\":\"Bearer\",\"credentials\":\"secret-token\"}}}}";
    final var first = task(h.rpc(Harness.headers(), Harness.request("SendMessage", params)));
    final String id = (String) first.get("id");
    Awaitility.await().atMost(Duration.ofSeconds(20)).until(() -> hits.size() >= 1);
    h.followUp(id, "tck-complete-task-2", "go");
    Awaitility.await().atMost(Duration.ofSeconds(20)).until(() -> hits.size() >= 2);

    for (final Hit hit : hits) {
      assertThat(hit.headers().get("authorization")).containsExactly("Bearer secret-token");
      assertThat(hit.headers().get("content-type").get(0)).startsWith("application/a2a+json");
      assertThat(hit.body()).containsKey("task");
    }
    final var last = hits.get(hits.size() - 1);
    assertThat(state((Map<String, Object>) last.body().get("task"))).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(((Map<String, Object>) last.body().get("task")).get("id")).isEqualTo(id);
  }

  @Test
  void cancelIsDeliveredToo() {
    final String id = (String) task(h.send("tck-input-required-1", "x")).get("id");
    pushCall("CreateTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"url\":\"" + hook + "\"}");
    assertThat(state(bareTask(h.cancel(id)))).isEqualTo("TASK_STATE_CANCELED");
    Awaitility.await().atMost(Duration.ofSeconds(20)).until(() -> hits.size() >= 1);
    assertThat(state((Map<String, Object>) hits.get(0).body().get("task"))).isEqualTo("TASK_STATE_CANCELED");
  }

  @Test
  void failedDeliveriesNeverFailTheTaskOrRaiseIncidents() {
    final String dead = "http://127.0.0.1:1/hook";
    final String params = "{\"message\":{\"messageId\":\"tck-complete-task-1\",\"role\":\"ROLE_USER\","
        + "\"parts\":[{\"text\":\"x\"}]},\"configuration\":{\"taskPushNotificationConfig\":{\"url\":\"" + dead
        + "\"}}}";
    final var done = task(h.rpc(Harness.headers(), Harness.request("SendMessage", params)));
    assertThat(state(done)).isEqualTo("TASK_STATE_COMPLETED");
    org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(
        client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-push-notify")
            .state(io.camunda.client.api.search.enums.ProcessInstanceState.COMPLETED)).send().join().items()).isNotEmpty());
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
    assertThat(state(bareTask(h.get((String) done.get("id"))))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void tasksWithoutConfigsStartNoDeliveryProcess() {
    task(h.send("tck-complete-task-1", "x"));
    assertThat(client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-push-notify"))
        .send().join().items()).isEmpty();
  }
}
