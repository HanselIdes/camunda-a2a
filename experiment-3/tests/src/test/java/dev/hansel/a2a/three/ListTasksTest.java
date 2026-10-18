package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.errorCode;
import static dev.hansel.a2a.three.Harness.result;
import static dev.hansel.a2a.three.Harness.task;
import static dev.hansel.a2a.three.Harness.bareTask;
import static dev.hansel.a2a.three.Harness.state;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** ListTasks tier 2: tasks are found by instance tags, asked for their state, filtered, sorted and paged. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn", "dmn/a2a-validate.dmn", "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn"})
class ListTasksTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
  }

  String create(final String ctx, final String messageId) {
    return (String) task(h.sendRaw(messageId, "x", ",\"contextId\":\"" + ctx + "\"")).get("id");
  }

  @SuppressWarnings("unchecked")
  List<Map<String, Object>> tasks(final Map<String, Object> response) {
    return (List<Map<String, Object>>) result(response).get("tasks");
  }

  /** Search results lag the engine by the exporter flush interval, so wait for the expected number. */
  Map<String, Object> listEventually(final String params, final int expected) {
    final var holder = new Object[1];
    Awaitility.await().atMost(Duration.ofSeconds(30)).pollInterval(Duration.ofMillis(500)).untilAsserted(() -> {
      final var r = h.list(params);
      assertThat(result(r)).containsEntry("totalSize", expected);
      holder[0] = r;
    });
    @SuppressWarnings("unchecked")
    final var r = (Map<String, Object>) holder[0];
    return r;
  }

  @Test
  void listsTheTasksOfAContextNewestFirstWithoutArtifacts() throws Exception {
    final String a = create("ctx-list", "tck-artifact-text-1");
    Thread.sleep(1100);                       // timestamps have a resolution of one second
    final String b = create("ctx-list", "tck-complete-task-2");
    create("another-context", "tck-complete-task-3");
    final var r = listEventually("{\"context_id\":\"ctx-list\"}", 2);
    final var tasks = tasks(r);
    assertThat(tasks).extracting(t -> t.get("id")).containsExactly(b, a);
    assertThat(tasks).allSatisfy(t -> assertThat(t).doesNotContainKey("artifacts").containsEntry("contextId", "ctx-list"));
    assertThat(result(r)).containsEntry("nextPageToken", "").containsEntry("pageSize", 50);

    final var withArtifacts = tasks(h.list("{\"context_id\":\"ctx-list\",\"include_artifacts\":true}"));
    assertThat(withArtifacts.stream().filter(t -> t.containsKey("artifacts")).count()).isEqualTo(1);
  }

  @Test
  void pagesWithCursorTokens() throws Exception {
    final List<String> ids = new ArrayList<>();
    for (int i = 0; i < 5; i++) {
      ids.add(create("ctx-pages", "tck-complete-task-" + i));
      Thread.sleep(1050);
    }
    listEventually("{\"context_id\":\"ctx-pages\"}", 5);
    final var first = h.list("{\"context_id\":\"ctx-pages\",\"page_size\":2}");
    assertThat(tasks(first)).hasSize(2);
    final String token = (String) result(first).get("nextPageToken");
    assertThat(token).isEqualTo("2");
    final var second = h.list("{\"context_id\":\"ctx-pages\",\"pageSize\":2,\"pageToken\":\"" + token + "\"}");
    assertThat(tasks(second)).hasSize(2);
    final var third = h.list("{\"context_id\":\"ctx-pages\",\"page_size\":2,\"page_token\":\"4\"}");
    assertThat(tasks(third)).hasSize(1);
    assertThat(result(third)).containsEntry("nextPageToken", "").containsEntry("totalSize", 5);
    final List<Object> all = new ArrayList<>();
    for (final var page : List.of(first, second, third)) {
      tasks(page).forEach(t -> all.add(t.get("id")));
    }
    assertThat(all).containsExactlyElementsOf(new ArrayList<>(ids.reversed()));
  }

  @Test
  void filtersByStatusAndTimestamp() throws Exception {
    create("ctx-filter", "tck-complete-task-1");
    final String waiting = create("ctx-filter", "tck-input-required-2");
    listEventually("{\"context_id\":\"ctx-filter\"}", 2);
    final var inputRequired = tasks(h.list("{\"context_id\":\"ctx-filter\",\"status\":\"TASK_STATE_INPUT_REQUIRED\"}"));
    assertThat(inputRequired).extracting(t -> t.get("id")).containsExactly(waiting);
    assertThat(tasks(h.list("{\"context_id\":\"ctx-filter\",\"status\":\"TASK_STATE_FAILED\"}"))).isEmpty();
    assertThat(tasks(h.list("{\"context_id\":\"ctx-filter\",\"status_timestamp_after\":\"2999-01-01T00:00:00Z\"}"))).isEmpty();
    assertThat(tasks(h.list("{\"context_id\":\"ctx-filter\",\"statusTimestampAfter\":\"2000-01-01T00:00:00Z\"}"))).hasSize(2);
  }

  @Test
  void historyLengthLimitsTheHistoryOfEachTask() throws Exception {
    final String id = create("ctx-history", "tck-input-required-1");
    h.followUp(id, "tck-complete-task-2", "again");
    listEventually("{\"context_id\":\"ctx-history\"}", 1);
    final var limited = tasks(h.list("{\"context_id\":\"ctx-history\",\"history_length\":1}"));
    assertThat(Harness.history(limited.get(0))).hasSize(1);
    assertThat(Harness.history(tasks(h.list("{\"context_id\":\"ctx-history\"}")).get(0))).hasSizeGreaterThan(1);
  }

  @Test
  void unknownContextAndOddContextIdsAreHandled() throws Exception {
    assertThat(tasks(h.list("{\"context_id\":\"nothing-here\"}"))).isEmpty();
    final String odd = "context with spaces/and:odd*chars-" + "x".repeat(150);
    create(odd, "tck-complete-task-1");
    listEventually("{\"context_id\":\"" + odd + "\"}", 1);
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }

  @Test
  void finishedTasksStayListedAfterTheirProcessEnded() {
    final String id = create("ctx-done", "tck-complete-task-1");
    // the fixture process has ended; the task is read from the history of its task variable
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(client.newProcessInstanceSearchRequest()
        .filter(f -> f.processDefinitionId(Harness.FIXTURE).state(io.camunda.client.api.search.enums.ProcessInstanceState.COMPLETED))
        .send().join().items()).hasSize(1));
    final var listed = tasks(listEventually("{\"context_id\":\"ctx-done\"}", 1));
    assertThat(listed.get(0)).containsEntry("id", id);
    assertThat(state(listed.get(0))).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_COMPLETED");
  }
}
