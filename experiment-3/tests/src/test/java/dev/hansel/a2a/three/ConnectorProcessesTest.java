package dev.hansel.a2a.three;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.command.ProblemException;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/** The two small reusable processes, with the HTTP JSON connector mocked at the job level. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn"})
class ConnectorProcessesTest {
  CamundaClient client;
  CamundaProcessTestContext context;

  /** Runs a2a-await for up to `seconds` against reads that find nothing for `misses` reads, then the task at revision 2. */
  private Map<String, Object> await(final int misses, final int seconds, final Map<String, Object> until) {
    final var reads = new AtomicInteger();
    context.mockJobWorker(Harness.HTTP_JSON).withHandler((c, job) -> {
      final var items = reads.incrementAndGet() <= misses ? List.of()
          : List.of(Map.of("value", "{\"id\":\"t\",\"rev\":2,\"status\":{\"state\":\"TASK_STATE_COMPLETED\"},"
              + "\"history\":[{\"messageId\":\"m-1\"}]}"));
      c.newCompleteCommand(job).variables(Map.of("items", items)).send().join();
    });
    final var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-await").latestVersion()
        .variables(Map.of("probe", Map.of("path", "/v2/variables/search", "body", Map.of()), "until", until,
            "deadline", java.time.Instant.now().plusSeconds(seconds).toString()))
        .withResult().send().join();
    final Map<String, Object> out = new java.util.HashMap<>(pi.getVariablesAsMap());
    out.put("reads", reads.get());
    return out;
  }

  @SuppressWarnings("unchecked")
  private static Map<String, Object> check(final Map<String, Object> out) {
    return (Map<String, Object>) out.get("check");
  }

  @Test
  void awaitReadsAgainUntilTheWriteIsVisible() {
    final var out = await(3, 20, Map.of("kind", "task", "minRev", 2));
    assertThat(out.get("reads")).isEqualTo(4);
    assertThat(check(out)).containsEntry("visible", true);
  }

  @Test
  void awaitGivesUpAtTheDeadline() {
    final var out = await(100, 1, Map.of("kind", "task", "minRev", 1));
    assertThat((Integer) out.get("reads")).isGreaterThanOrEqualTo(1);
    assertThat(check(out)).containsEntry("visible", false).containsEntry("seen", null);
  }

  @Test
  void awaitChecksRevisionSettledStateAndMessageId() {
    assertThat(check(await(0, 0, Map.of("kind", "task", "minRev", 3)))).containsEntry("visible", false);
    assertThat(check(await(0, 0, Map.of("kind", "task", "minRev", 0, "settled", true)))).containsEntry("visible", true);
    assertThat(check(await(0, 0, Map.of("kind", "task", "minRev", 0, "messageId", "m-2")))).containsEntry("visible", false);
    assertThat(check(await(0, 0, Map.of("kind", "task", "minRev", 0, "messageId", "m-1")))).containsEntry("visible", true);
  }

  // one await per test: every await registers its own mock worker, and earlier ones would take later jobs
  @Test
  void awaitWaitsForAConfigToAppear() {
    assertThat(check(await(2, 20, Map.of("kind", "present")))).containsEntry("visible", true);
  }

  @Test
  void awaitSeesThatAConfigIsGone() {
    assertThat(check(await(5, 20, Map.of("kind", "absent")))).containsEntry("visible", true);
  }

  @Test
  void awaitReportsAConfigThatStaysAfterItsTries() {
    assertThat(check(await(0, 1, Map.of("kind", "absent")))).containsEntry("visible", false);
  }

  private long correlate(final int notFoundBeforeSuccess, final int tries) {
    final var calls = new AtomicInteger();
    context.mockJobWorker(Harness.HTTP_JSON).withHandler((c, job) -> {
      if (calls.incrementAndGet() <= notFoundBeforeSuccess) {
        c.newThrowErrorCommand(job).errorCode("NOT_FOUND").send().join();
      } else {
        c.newCompleteCommand(job).send().join();
      }
    });
    final var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-correlate").latestVersion()
        .variables(Map.of("messageName", "a2a-get", "taskId", "t", "payload", Map.of("x", 1), "tries", tries))
        .send().join();
    io.camunda.process.test.api.CamundaAssert.assertThat(pi).isCompleted();
    return calls.get();
  }

  private boolean correlated() {
    final var items = client.newVariableSearchRequest().filter(f -> f.name("correlated")).send().join().items();
    return Boolean.parseBoolean(items.get(items.size() - 1).getValue());
  }

  @Test
  void correlatesOnTheFirstTry() {
    assertThat(correlate(0, 3)).isEqualTo(1);
    assertThat(correlated()).isTrue();
  }

  @Test
  void retriesWhileThereIsNoSubscriptionAndThenSucceeds() {
    assertThat(correlate(2, 3)).isEqualTo(3);
    assertThat(correlated()).isTrue();
  }

  @Test
  void givesUpAfterTheConfiguredNumberOfTries() {
    assertThat(correlate(100, 2)).isEqualTo(2);
    assertThat(correlated()).isFalse();
  }

  @Test
  void aRealCorrelationOnTheEngineIs404WithoutSubscription() {
    try {
      client.newCorrelateMessageCommand().messageName("nobody").correlationKey("k").send().join();
      throw new AssertionError("expected 404");
    } catch (final ProblemException e) {
      assertThat(e.code()).isEqualTo(404);
    }
  }
}
