package dev.hansel.a2a;

import static dev.hansel.a2a.Harness.errorCode;
import static dev.hansel.a2a.Harness.state;
import static dev.hansel.a2a.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Behavior beyond what the TCK checks: odd ids, big and unusual payloads, concurrency, repeated requests. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn", "bpmn/a2a-correlate.bpmn",
    "bpmn/a2a-publish-reply.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn", "dmn/capitals.dmn"})
class EdgeCaseTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
  }

  @Test
  void requestIdIsEchoedWhateverItsType() {
    for (final Object id : new Object[] {1, "abc", 0, "", 1.5}) {
      final var request = Harness.request("Nope", "{}");
      request.put("id", id);
      assertThat(h.rpc(Harness.headers(), request)).as("id %s", id).containsEntry("id", id);
    }
    final var withoutId = Harness.request("Nope", "{}");
    withoutId.remove("id");
    assertThat(h.rpc(Harness.headers(), withoutId)).containsKeys("jsonrpc", "error");
  }

  @Test
  void batchRequestsAndNonObjectBodiesAreInvalidRequests() {
    assertThat(errorCode(h.rpc(Harness.headers(), List.of(Harness.request("GetTask", "{}"))))).isEqualTo(-32600);
    assertThat(errorCode(h.rpc(Harness.headers(), 42))).isEqualTo(-32600);
    assertThat(errorCode(h.rpc(Harness.headers(), "{}"))).isEqualTo(-32600);
    assertThat(errorCode(h.rpc(Harness.headers(), Map.of("method", "GetTask", "params", Map.of())))).isEqualTo(-32600);
  }

  @Test
  void unicodeAndLargeMessagesAreStoredAndReturnedUnchanged() {
    final String text = "Grüße 日本語 🚀 \\\"quoted\\\" line\\nbreak";
    final var unicode = task(h.send("tck-complete-task-1", text));
    assertThat(state(unicode)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(Harness.history(unicode).get(0).toString()).contains("Grüße 日本語 🚀");

    final String big = "x".repeat(200_000);
    final var large = task(h.send("tck-complete-task-2", big));
    assertThat(state(large)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(large.toString().length()).isGreaterThan(200_000);
  }

  @Test
  void aRepeatedMessageIdCreatesANewTaskEachTime() {
    final var first = task(h.send("tck-complete-task-same", "x"));
    final var second = task(h.send("tck-complete-task-same", "x"));
    assertThat(first.get("id")).isNotEqualTo(second.get("id"));
  }

  @Test
  void tasksShareAContextWhenTheClientReusesIt() {
    final var a = task(h.sendRaw("tck-complete-task-1", "x", ",\"contextId\":\"shared\""));
    final var b = task(h.sendRaw("tck-complete-task-2", "x", ",\"contextId\":\"shared\""));
    assertThat(a.get("contextId")).isEqualTo("shared").isEqualTo(b.get("contextId"));
    assertThat(a.get("id")).isNotEqualTo(b.get("id"));
  }

  @Test
  void concurrentRequestsDoNotInterfere() {
    final List<CompletableFuture<Map<String, Object>>> futures = new ArrayList<>();
    for (int i = 0; i < 12; i++) {
      final String prefix = i % 3 == 0 ? "tck-input-required-" : i % 3 == 1 ? "tck-complete-task-" : "tck-artifact-text-";
      final String id = prefix + i;
      futures.add(CompletableFuture.supplyAsync(() -> h.send(id, "request " + id)));
    }
    final var ids = new java.util.HashSet<Object>();
    for (int i = 0; i < futures.size(); i++) {
      final var task = task(futures.get(i).join());
      ids.add(task.get("id"));
      assertThat(state(task)).isEqualTo(i % 3 == 0 ? "TASK_STATE_INPUT_REQUIRED" : "TASK_STATE_COMPLETED");
      assertThat(Harness.history(task).get(0).toString()).contains("request " + (i % 3 == 0 ? "tck-input-required-"
          : i % 3 == 1 ? "tck-complete-task-" : "tck-artifact-text-") + i);
    }
    assertThat(ids).hasSize(12);
  }

  @Test
  void concurrentFollowUpsToOneTaskAreSerializedOnTheSubscription() {
    final String id = (String) task(h.send("tck-input-required-1", "start")).get("id");
    final var f1 = CompletableFuture.supplyAsync(() -> h.followUp(id, "tck-input-required-2", "one"));
    final var f2 = CompletableFuture.supplyAsync(() -> h.followUp(id, "tck-input-required-3", "two"));
    final var r1 = f1.join();
    final var r2 = f2.join();
    // one follow-up is accepted, the other finds no subscription while the task is working and is refused
    // or is accepted after the first one returned the task to INPUT_REQUIRED; neither may raise an incident
    for (final var r : List.of(r1, r2)) {
      assertThat(r).satisfiesAnyOf(x -> assertThat(x).containsKey("result"), x -> assertThat(x).containsKey("error"));
    }
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }

  @Test
  void unknownParamsAndExtensionHeadersAreTolerated() {
    final var headers = Harness.headers();
    headers.put("a2a-extensions", "urn:example:unknown");
    final var response = h.rpc(headers, Harness.request("SendMessage",
        "{\"message\":{\"messageId\":\"tck-complete-task-1\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"x\"}],"
            + "\"extraField\":1},\"metadata\":{\"a\":1},\"unknown\":true}"));
    assertThat(state(task(response))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void pagingAndHistoryParametersAcceptSnakeCaseAndCamelCase() {
    final String id = (String) task(h.send("tck-input-required-1", "a")).get("id");
    h.followUp(id, "tck-complete-task-2", "b");
    final var snake = h.rpc(Harness.headers(), Harness.request("GetTask", "{\"id\":\"" + id + "\",\"history_length\":1}"));
    assertThat(Harness.history(Harness.bareTask(snake))).hasSize(1);
    final var list = h.rpc(Harness.headers(), Harness.request("ListTasks", "{\"pageSize\":7}"));
    assertThat(Harness.result(list)).containsEntry("pageSize", 7);
  }

  @Test
  void aTaskThatReachedInputRequiredCanBeCanceledEvenAfterFollowUps() {
    final String id = (String) task(h.send("tck-input-required-1", "a")).get("id");
    h.followUp(id, "tck-input-required-2", "b");
    assertThat(state(Harness.bareTask(h.cancel(id)))).isEqualTo("TASK_STATE_CANCELED");
    assertThat(errorCode(h.followUp(id, "tck-complete-task-3", "c"))).isEqualTo(-32004);
  }
}
