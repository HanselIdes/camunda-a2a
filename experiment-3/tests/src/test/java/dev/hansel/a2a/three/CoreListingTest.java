package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.errorCode;
import static dev.hansel.a2a.three.Harness.result;
import static dev.hansel.a2a.three.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.IntStream;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

@CamundaProcessTest
@TestDeployment(resources = {"core/a2a-protocol.bpmn", "bpmn/a2a-echo.bpmn", "dmn/a2a-validate.dmn"})
class CoreListingTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
    h.agentProcess = "a2a-echo";
  }

  @SuppressWarnings("unchecked")
  private static List<Map<String, Object>> tasks(final Map<String, Object> response) {
    return (List<Map<String, Object>>) result(response).get("tasks");
  }

  @Test
  void emptyListsAndCollidingContextTagsRetainExactContextFiltering() {
    assertThat(result(h.list("{}"))).containsEntry("totalSize", 0).containsEntry("nextPageToken", "");
    final var first = task(h.sendRaw("context-one", "First context", ",\"contextId\":\"a b\""));
    task(h.sendRaw("context-two", "Other context", ",\"contextId\":\"a?b\""));
    assertThat(tasks(h.list("{\"contextId\":\"a b\"}"))).containsExactly(first);
    assertThat(tasks(h.list("{\"contextId\":\"unknown-context\"}"))).isEmpty();
  }

  @Test
  void listsAll125ExactTasksAcrossEngineAndA2APagesWithStableTimestampTies() {
    final List<Map<String, Object>> expected;
    try (var executor = Executors.newFixedThreadPool(8)) {
      final var submissions = IntStream.range(0, 125).mapToObj(index -> CompletableFuture.supplyAsync(() ->
          task(h.sendRaw("core-page-" + index, "Exact result " + index, ",\"contextId\":\"core-pagination\"")),
          executor)).toList();
      expected = new ArrayList<>(submissions.stream().map(CompletableFuture::join).toList());
    }
    expected.sort(Comparator.<Map<String, Object>, String>comparing(
        value -> ((Map<?, ?>) value.get("status")).get("timestamp").toString())
        .thenComparing(value -> value.get("id").toString()).reversed());
    assertThat(expected.stream().map(value -> ((Map<?, ?>) value.get("status")).get("timestamp")).distinct().count())
        .as("the workload exercises equal-timestamp ordering").isLessThan(125);
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() ->
        assertThat(result(h.list("{\"contextId\":\"core-pagination\",\"pageSize\":37}")))
            .containsEntry("totalSize", 125));
    final var observed = new ArrayList<Map<String, Object>>();
    String token = "";
    do {
      final var page = h.list("{\"contextId\":\"core-pagination\",\"pageSize\":37,\"includeArtifacts\":true,"
          + "\"pageToken\":\"" + token + "\"}");
      assertThat(result(page)).containsEntry("totalSize", 125).containsEntry("pageSize", 37);
      observed.addAll(tasks(page));
      token = (String) result(page).get("nextPageToken");
      assertThat(observed).hasSizeLessThanOrEqualTo(125);
    } while (!token.isEmpty());
    assertThat(observed).containsExactlyElementsOf(expected);
    assertThat(observed.stream().map(value -> value.get("id")).distinct().count()).isEqualTo(125);
    assertThat(tasks(h.list("{\"contextId\":\"core-pagination\",\"status\":\"TASK_STATE_FAILED\"}"))).isEmpty();
    assertThat(tasks(h.list("{\"contextId\":\"core-pagination\","
        + "\"statusTimestampAfter\":\"2999-01-01T00:00:00Z\"}"))).isEmpty();
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }

  @Test
  void waitsForTheEntireRootVariableBatchInsteadOfOmittingUnindexedTasks() {
    final var expected = task(h.send("delayed-list-state", "Exact delayed result"));
    final var misses = new AtomicInteger(2);
    h.afterEngineResponse = (call, body) ->
        call.startsWith("POST /v2/variables/search") && misses.getAndDecrement() > 0
            ? Map.of("items", List.of()) : body;
    assertThat(tasks(h.list("{}"))).containsExactly(expected);
    assertThat(misses.get()).isNegative();
  }

  @ParameterizedTest
  @ValueSource(strings = {"missing", "null", "malformed"})
  void incompleteRootStateExpiresWithAnErrorInsteadOfAPartialSuccessfulList(final String mode) {
    final var expected = task(h.send("invisible-list-state", "Must not disappear"));
    h.afterEngineResponse = (call, body) -> {
      if (!call.startsWith("POST /v2/variables/search")) {
        return body;
      }
      if (mode.equals("missing")) {
        return Map.of("items", List.of());
      }
      return Map.of("items", ((List<?>) ((Map<?, ?>) body).get("items")).stream().map(item -> {
        final var value = (Map<?, ?>) item;
        return Map.of("scopeKey", value.get("scopeKey"), "processInstanceKey", value.get("processInstanceKey"),
            "value", mode.equals("null") ? "null" : "{}");
      }).toList());
    };
    final long start = System.nanoTime();
    final var response = h.list("{}");
    h.afterEngineResponse = (call, body) -> body;
    assertThat(errorCode(response)).isEqualTo(-32603);
    assertThat(response.toString()).contains("DEADLINE_EXCEEDED").doesNotContain("result=");
    assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(15));
    assertThat(Harness.bareTask(h.get((String) expected.get("id")))).isEqualTo(expected);
  }

  @Test
  void missingRepeatedAndOverlappingEngineCursorsCannotReturnTruncatedSuccess() throws Exception {
    h.send("valid-engine-cursor", "Provides an engine-issued cursor");
    final String value = Harness.JSON.writeValueAsString(Map.of("id", "unreturned", "contextId", "unreturned",
        "rev", 1, "history", List.of(), "artifacts", List.of(), "status",
        Map.of("state", "TASK_STATE_COMPLETED", "timestamp", "2026-10-27T00:00:00Z")));
    for (final String mode : List.of("missing", "repeated", "overlapping")) {
      final var pages = new AtomicInteger();
      final var engineCursor = new AtomicReference<String>();
      h.afterEngineResponse = (call, body) -> {
        final int offset;
        if (call.equals("POST /v2/process-instances/search")) {
          final int page = pages.getAndIncrement();
          if (page == 0) {
            engineCursor.set((String) ((Map<?, ?>) ((Map<?, ?>) body).get("page")).get("endCursor"));
            assertThat(engineCursor.get()).as("use an engine-valid cursor before injecting repetition").isNotEmpty();
          }
          offset = mode.equals("overlapping") ? 0 : page * 100;
          return Map.of("items", IntStream.range(offset, offset + 100)
              .mapToObj(index -> Map.of("processInstanceKey", String.valueOf(index + 1))).toList(),
              "page", Map.of("endCursor", mode.equals("missing") ? "" : engineCursor.get()));
        }
        if (call.startsWith("POST /v2/variables/search")) {
          offset = mode.equals("overlapping") ? 0 : (pages.get() - 1) * 100;
          return Map.of("items", IntStream.range(offset, offset + 100).mapToObj(index -> {
            final String key = String.valueOf(index + 1);
            return Map.of("scopeKey", key, "processInstanceKey", key, "value", value);
          }).toList());
        }
        return body;
      };
      final var pending = CompletableFuture.supplyAsync(() -> h.list("{}"));
      Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
        assertThat(client.newIncidentSearchRequest().send().join().items())
            .extracting(incident -> incident.getElementId() + ": " + incident.getErrorMessage()).isEmpty();
        assertThat(pending.isDone()).as("the malformed scan returns an explicit response: %s", mode).isTrue();
      });
      final var response = pending.join();
      h.afterEngineResponse = (call, body) -> body;
      assertThat(errorCode(response)).as(mode).isEqualTo(-32603);
      assertThat(response.toString()).contains("DATA_LOSS").doesNotContain("result=");
      assertThat(pages.get()).isEqualTo(mode.equals("missing") ? 1 : 2);
    }
  }
}
