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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn", "bpmn/a2a-echo.bpmn", "dmn/a2a-validate.dmn"})
class DeterministicProcessTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
    h.agentProcess = "a2a-echo";
  }

  @Test
  void anotherProcessCompletesThroughTheTaskContractWithoutAModel() {
    final var completed = task(h.send("echo-request", "Hello from a deterministic process"));
    assertThat(state(completed)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(completed)).isEqualTo("Hello from a deterministic process");
    assertThat(history(completed)).hasSize(2);
    assertThat(history(completed).get(0)).containsEntry("messageId", "echo-request");
    final var fetched = h.get((String) completed.get("id"));
    assertThat(fetched.get("result")).isEqualTo(completed);
  }

  @Test
  void independentRequestsKeepTheirOwnTextAndTaskIds() {
    final var first = task(h.send("first", "First result"));
    final var second = task(h.send("second", "Second result"));
    assertThat(first.get("id")).isNotEqualTo(second.get("id"));
    assertThat(statusText(first)).isEqualTo("First result");
    assertThat(statusText(second)).isEqualTo("Second result");
    assertThat(history(first).get(0)).containsEntry("messageId", "first");
    assertThat(history(second).get(0)).containsEntry("messageId", "second");
  }
}
