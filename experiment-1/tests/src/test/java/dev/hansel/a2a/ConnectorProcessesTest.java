package dev.hansel.a2a;

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
@TestDeployment(resources = {"bpmn/a2a-correlate.bpmn", "bpmn/a2a-publish-reply.bpmn", "bpmn/a2a-push-notify.bpmn", "bpmn/a2a-fetch-task.bpmn"})
class ConnectorProcessesTest {
  CamundaClient client;
  CamundaProcessTestContext context;

  @Test
  void publishReplyPostsTheReplyToThePublicationEndpoint() {
    final var captured = new java.util.concurrent.atomic.AtomicReference<Map<String, Object>>();
    context.mockJobWorker(Harness.HTTP_JSON).withHandler((c, job) -> {
      captured.set(job.getVariablesAsMap());
      c.newCompleteCommand(job).send().join();
    });
    final var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-publish-reply").latestVersion()
        .variables(Map.of("corrId", "c-1", "replyResult", Map.of("task", Map.of("id", "t")))).send().join();
    io.camunda.process.test.api.CamundaAssert.assertThat(pi).isCompleted();
    final var vars = captured.get();
    assertThat((String) vars.get("url")).endsWith("/v2/messages/publication");
    assertThat(vars.get("method")).isEqualTo("POST");
    @SuppressWarnings("unchecked")
    final var body = (Map<String, Object>) vars.get("body");
    assertThat(body).containsEntry("name", "a2a-reply").containsEntry("correlationKey", "c-1")
        .containsEntry("timeToLive", 15000);
    assertThat(vars.get("ignoreNullValues")).isEqualTo("true");
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
