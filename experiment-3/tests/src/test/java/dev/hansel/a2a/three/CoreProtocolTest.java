package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.history;
import static dev.hansel.a2a.three.Harness.state;
import static dev.hansel.a2a.three.Harness.statusText;
import static dev.hansel.a2a.three.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"core/a2a-protocol.bpmn", "bpmn/a2a-echo.bpmn", "dmn/a2a-validate.dmn",
    "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn"})
class CoreProtocolTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
    h.agentProcess = "a2a-echo";
  }

  @Test
  void completesAndReadsExactResultsWithoutPost88EngineApis() {
    final var completed = task(h.send("core-echo", "Core result"));
    assertThat(state(completed)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(completed)).isEqualTo("Core result");
    assertThat(h.get((String) completed.get("id")).get("result")).isEqualTo(completed);
    assertThat(h.calls).noneMatch(c -> c.contains("/cluster-variables") || c.contains("/expression/evaluation"));
  }

  @Test
  void messageIdsCannotSelectConformanceSpecificBusinessBehavior() {
    final var completed = task(h.send("tck-message-response-1", "Real echo"));
    assertThat(statusText(completed)).isEqualTo("Real echo");
    assertThat(history(completed)).hasSize(2);
  }

  @Test
  void anotherAgentsTaskCannotBeReadOrChanged() {
    h.agentProcess = Harness.FIXTURE;
    final var other = task(h.send("tck-complete-task-other", "Other agent"));
    h.agentProcess = "a2a-echo";
    final String id = (String) other.get("id");
    assertThat(h.get(id).toString()).contains("TASK_NOT_FOUND");
    assertThat(h.cancel(id).toString()).contains("TASK_NOT_FOUND");
    assertThat(h.followUp(id, "foreign", "Change task").toString()).contains("TASK_NOT_FOUND");
  }

  @Test
  void disabledPushIsRejectedBeforeCreatingBusinessWork() {
    final var response = h.sendWith("push-disabled",
        "{\"taskPushNotificationConfig\":{\"url\":\"https://example.invalid/callback\"}}");
    assertThat(response.toString()).contains("PUSH_NOTIFICATION_NOT_SUPPORTED");
    assertThat(h.calls).noneMatch(c -> c.equals("POST /v2/process-instances"));
  }

  @Test
  void taskLookupWaitsForDelayedProcessIndexVisibility() {
    final var completed = task(h.send("index-lag", "Indexed result"));
    final var misses = new AtomicInteger(2);
    h.afterEngineResponse = (call, body) ->
        call.equals("POST /v2/process-instances/search") && misses.getAndDecrement() > 0
            ? Map.of("items", List.of()) : body;
    assertThat(h.get((String) completed.get("id")).get("result")).isEqualTo(completed);
    assertThat(misses.get()).isNegative();
  }

  @Test
  void unknownTaskLookupHasABoundedExpiry() {
    final long start = System.nanoTime();
    assertThat(h.get("missing-task").toString()).contains("TASK_NOT_FOUND");
    assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(8));
    assertThat(h.calls.stream().filter(c -> c.equals("POST /v2/process-instances/search")).count())
        .isBetween(2L, 20L);
  }
}
