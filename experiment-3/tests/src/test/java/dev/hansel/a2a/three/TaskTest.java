package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.bareTask;
import static dev.hansel.a2a.three.Harness.errorCode;
import static dev.hansel.a2a.three.Harness.history;
import static dev.hansel.a2a.three.Harness.state;
import static dev.hansel.a2a.three.Harness.statusText;
import static dev.hansel.a2a.three.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Every task state transition, driven through the real handler process against the TCK fixture. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn", "dmn/a2a-validate.dmn", "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn"})
class TaskTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
  }

  @Test
  void completeTaskReturnsCompletedTaskWithStatusMessage() {
    final var task = task(h.send("tck-complete-task-1", "hello"));
    assertThat(state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(task)).isEqualTo("Hello from TCK");
    assertThat(task).containsKeys("id", "contextId");
    assertThat(history(task)).hasSize(2);
    assertThat(history(task).get(0)).containsEntry("role", "ROLE_USER");
    assertThat(history(task).get(1)).containsEntry("role", "ROLE_AGENT");
  }

  @Test
  void inputRequiredThenFollowUpCompletes() {
    final var first = task(h.send("tck-input-required-1", "start"));
    assertThat(state(first)).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    final var second = task(h.followUp((String) first.get("id"), "tck-complete-task-2", "finish"));
    assertThat(state(second)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(second.get("contextId")).isEqualTo(first.get("contextId"));
    assertThat(history(second)).hasSize(3);
  }

  @Test
  void followUpsCanKeepTheTaskInputRequired() {
    final var first = task(h.send("tck-input-required-1", "start"));
    final String id = (String) first.get("id");
    assertThat(state(task(h.followUp(id, "tck-input-required-2", "m1")))).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    assertThat(state(task(h.followUp(id, "tck-input-required-3", "m2")))).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    final var done = task(h.followUp(id, "tck-complete-task-4", "m3"));
    assertThat(state(done)).isEqualTo("TASK_STATE_COMPLETED");
    final List<Object> texts = new java.util.ArrayList<>();
    for (final var m : history(done)) {
      texts.add(((Map<?, ?>) ((List<?>) m.get("parts")).get(0)).get("text"));
    }
    assertThat(texts).containsSubsequence((Object) "start", (Object) "m1", (Object) "m2", (Object) "m3");
  }

  @Test
  void terminalTaskAnswersGetAndRejectsCancelAndSend() {
    final var task = task(h.send("tck-complete-task-1", "x"));
    final String id = (String) task.get("id");
    assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(errorCode(h.cancel(id))).isEqualTo(-32002);
    assertThat(errorCode(h.followUp(id, "tck-complete-task-2", "again"))).isEqualTo(-32004);
    // still answering after the rejections
    assertThat(bareTask(h.get(id))).containsEntry("id", id);
  }

  @Test
  void cancelInputRequiredTaskAndCancelAgainFails() {
    final String id = (String) task(h.send("tck-input-required-1", "x")).get("id");
    final var canceled = bareTask(h.cancel(id));
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_CANCELED");
    assertThat(errorCode(h.cancel(id))).isEqualTo(-32002);
  }

  @Test
  void historyLengthLimitsHistoryOnGetTask() {
    final String id = (String) task(h.send("tck-input-required-1", "a")).get("id");
    h.followUp(id, "tck-input-required-2", "b");
    h.followUp(id, "tck-complete-task-3", "c");
    assertThat(history(bareTask(h.get(id, 1)))).hasSize(1);
    assertThat(history(bareTask(h.get(id, 2)))).hasSize(2);
    assertThat(history(bareTask(h.get(id, 0)))).isEmpty();
    assertThat(history(bareTask(h.get(id, 100)))).hasSizeGreaterThanOrEqualTo(4);
    assertThat(history(bareTask(h.get(id)))).hasSizeGreaterThanOrEqualTo(4);
  }

  @Test
  void contextIdIsGeneratedEchoedAndChecked() {
    final var generated = task(h.send("tck-complete-task-1", "x"));
    assertThat((String) generated.get("contextId")).isNotBlank();

    final var echoed = task(h.sendRaw("tck-complete-task-2", "x", ",\"contextId\":\"client-context\""));
    assertThat(echoed).containsEntry("contextId", "client-context");

    final var waiting = task(h.send("tck-input-required-1", "x"));
    final String id = (String) waiting.get("id");
    final var mismatch = h.sendRaw("tck-complete-task-2", "x", ",\"taskId\":\"" + id + "\",\"contextId\":\"other\"");
    assertThat(errorCode(mismatch)).isEqualTo(-32602);
    assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    final var matching = h.sendRaw("tck-complete-task-3", "x",
        ",\"taskId\":\"" + id + "\",\"contextId\":\"" + waiting.get("contextId") + "\"");
    assertThat(state(task(matching))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void taskIdsAreUnique() {
    final var a = (String) task(h.send("tck-complete-task-1", "x")).get("id");
    final var b = (String) task(h.send("tck-complete-task-2", "x")).get("id");
    assertThat(a).isNotEqualTo(b);
  }

  @Test
  void artifactsAreAttachedByMessageIdPrefix() {
    final var text = task(h.send("tck-artifact-text-1", "x"));
    assertThat(artifactParts(text)).containsExactly(Map.of("text", "Generated text content"));
    assertThat(artifactParts(task(h.send("tck-artifact-file-1", "x"))))
        .containsExactly(Map.of("raw", "dGNr", "mediaType", "text/plain", "filename", "output.txt"));
    assertThat(artifactParts(task(h.send("tck-artifact-file-url-1", "x"))))
        .containsExactly(Map.of("url", "https://example.com/output.txt", "mediaType", "text/plain",
            "filename", "output.txt"));
    assertThat(artifactParts(task(h.send("tck-artifact-data-1", "x"))))
        .containsExactly(Map.of("data", Map.of("key", "value", "count", 42)));
    assertThat(state(text)).isEqualTo("TASK_STATE_COMPLETED");
  }

  @SuppressWarnings("unchecked")
  static List<Object> artifactParts(final Map<String, Object> task) {
    final var artifacts = (List<Map<String, Object>>) task.get("artifacts");
    assertThat(artifacts).hasSize(1);
    assertThat(artifacts.get(0)).containsKeys("artifactId", "parts");
    return (List<Object>) artifacts.get(0).get("parts");
  }

  @Test
  void otherTckMessageIdsEchoAndComplete() {
    final var task = task(h.send("tck-infer-ctx-1", "x"));
    assertThat(state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(task)).startsWith("Unhandled messageId prefix: tck-infer-ctx-1");
  }

  @Test
  void returnImmediatelyAnswersBeforeTheWorkAndTheTaskCompletesAnyway() {
    final var first = task(h.sendWith("tck-complete-task-1", "{\"returnImmediately\":true}"));
    assertThat(state(first)).isIn("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED");
    final String id = (String) first.get("id");
    org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(20))
        .untilAsserted(() -> assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_COMPLETED"));
  }

  @Test
  void unknownTaskIsNotFoundForGetCancelAndFollowUp() {
    assertThat(errorCode(h.get("missing"))).isEqualTo(-32001);
    assertThat(errorCode(h.cancel("missing"))).isEqualTo(-32001);
    assertThat(errorCode(h.followUp("missing", "tck-complete-task-1", "x"))).isEqualTo(-32001);
  }

  @Test
  void noIncidentsAfterMalformedInput() {
    h.rpc(Harness.headers(), Harness.request("SendMessage", "{\"message\":5}"));
    h.rpc(Harness.headers(), Harness.request("GetTask", "{\"id\":[1]}"));
    h.rpc(Harness.headers(), Map.of("jsonrpc", "2.0"));
    h.rpc(Harness.headers(), "just a string");
    h.rpc(Harness.headers(), Harness.request("SendMessage", "{\"message\":{\"messageId\":1,\"role\":2,\"parts\":3}}"));
    final var incidents = client.newIncidentSearchRequest().send().join().items();
    assertThat(incidents).isEmpty();
  }
}
