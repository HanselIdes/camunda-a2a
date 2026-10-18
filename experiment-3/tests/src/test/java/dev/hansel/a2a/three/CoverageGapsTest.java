package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.bareTask;
import static dev.hansel.a2a.three.Harness.errorCode;
import static dev.hansel.a2a.three.Harness.result;
import static dev.hansel.a2a.three.Harness.state;
import static dev.hansel.a2a.three.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.assertions.JobSelector;
import io.camunda.process.test.api.assertions.JobSelectors;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** The unusual paths: a message that is not a task, a follow-up to a task that is not waiting. */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn", "bpmn/a2a-agent.bpmn", "dmn/a2a-validate.dmn", "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn"})
class CoverageGapsTest {
  static final JobSelector AGENT = JobSelectors.byJobType("io.camunda.agenticai:aiagent:subprocess:2");

  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
  }

  /** Waits for an open request in real time: moving the engine clock would also expire the request itself. */
  <T> T advanceUntilDone(final CompletableFuture<T> future, final Duration ignored) throws Exception {
    return future.get(60, java.util.concurrent.TimeUnit.SECONDS);
  }

  @Test
  void aMessageThatAsksForADirectReplyGetsAMessageAndNoTask() {
    final var response = h.send("tck-message-response-1", "hello");
    final var message = (Map<?, ?>) result(response).get("message");
    assertThat(result(response)).doesNotContainKey("task");
    assertThat(message.get("role")).isEqualTo("ROLE_AGENT");
    assertThat(message.get("parts").toString()).contains("Direct message response");
  }

  @Test
  void aFollowUpToATaskThatIsWorkingNotWaitingIsRejected() throws Exception {
    h.agentProcess = "a2a-agent";
    final var first = CompletableFuture.supplyAsync(() -> h.send("m-1", "A slow question"));
    final String[] id = new String[1];
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> {
      final var tasks = client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-agent"))
          .send().join().items();
      assertThat(tasks).hasSize(1);
      final long key = tasks.get(0).getProcessInstanceKey();
      final var vars = client.newVariableSearchRequest().filter(f -> f.name("task").processInstanceKey(key))
          .send().join().items();
      assertThat(vars).isNotEmpty();
      id[0] = (String) Harness.map(vars.get(0).getValue()).get("id");
    });
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(
        () -> assertThat(state(bareTask(h.get(id[0])))).isEqualTo("TASK_STATE_WORKING"));
    final var follow = CompletableFuture.supplyAsync(() -> h.followUp(id[0], "m-2", "more"));
    assertThat(errorCode(advanceUntilDone(follow, Duration.ofSeconds(1)))).isEqualTo(-32004);
    // the task itself is untouched and finishes normally
    context.completeJobOfAdHocSubProcess(AGENT, Map.of("agent", Map.of("responseText", "Done.")),
        r -> r.completionConditionFulfilled(true).cancelRemainingInstances(true));
    advanceUntilDone(first, Duration.ofSeconds(1));
  }

  Map<String, Object> push(final String method, final String paramsJson) {
    return h.rpc(Harness.headers(), Harness.request(method, paramsJson));
  }

  /** Runs a request against the engine directly, as if another client changed the state at that moment. */
  void direct(final String method, final String path) {
    try {
      Harness.HTTP.send(java.net.http.HttpRequest.newBuilder(java.net.URI.create(h.rest + path))
          .header("Content-Type", "application/json").method(method, java.net.http.HttpRequest.BodyPublishers.ofString("{}"))
          .build(), java.net.http.HttpResponse.BodyHandlers.ofString());
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  static long keyIn(final String call) {
    return Long.parseLong(call.replaceAll("^[A-Z]+ /v2/[a-z-]+/(\\d+)/.*$", "$1"));
  }

  @Test
  void aConfigCreatedTwiceWithTheSameIdIsReplaced() {
    h.pushEnabled = true;
    final String id = (String) task(h.send("tck-complete-task-1", "x")).get("id");
    push("CreateTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c\",\"url\":\"https://a.example\"}");
    final var replaced = result(push("CreateTaskPushNotificationConfig",
        "{\"task_id\":\"" + id + "\",\"id\":\"c\",\"url\":\"https://b.example\"}"));
    assertThat(replaced).containsEntry("url", "https://b.example");
    assertThat((List<?>) result(push("ListTaskPushNotificationConfigs", "{\"task_id\":\"" + id + "\"}")).get("configs"))
        .hasSize(1);
    assertThat(h.calls).anyMatch(c -> c.startsWith("PUT /v2/cluster-variables/global/"));
  }

  @Test
  void deletingAConfigThatIsAlreadyGoneStillSucceeds() {
    h.pushEnabled = true;
    final String id = (String) task(h.send("tck-complete-task-1", "x")).get("id");
    push("CreateTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c\",\"url\":\"https://a.example\"}");
    // someone else deletes the config right before the endpoint does: the endpoint's DELETE answers 404
    h.beforeEngineCall = call -> {
      if (call.startsWith("DELETE /v2/cluster-variables/global/")) {
        direct("DELETE", call.substring("DELETE ".length()));
      }
    };
    assertThat(result(push("DeleteTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c\"}"))).isEmpty();
    assertThat(errorCode(push("GetTaskPushNotificationConfig", "{\"task_id\":\"" + id + "\",\"id\":\"c\"}")))
        .isEqualTo(-32602);
  }

  @Test
  void cancelingATaskWhoseProcessEndedMeanwhileIsRefused() {
    final String id = (String) task(h.send("tck-input-required-1", "x")).get("id");
    // the agent process ends right before the endpoint stores the canceled task
    h.beforeEngineCall = call -> {
      if (call.startsWith("PUT /v2/element-instances/")) {
        client.newCancelInstanceCommand(keyIn(call)).send().join();
      }
    };
    assertThat(errorCode(h.cancel(id))).isEqualTo(-32002);
  }

  @Test
  void cancelingSucceedsWhenTheProcessEndsBetweenStoringAndCanceling() {
    final String id = (String) task(h.send("tck-input-required-1", "x")).get("id");
    h.beforeEngineCall = call -> {
      if (call.endsWith("/cancellation")) {
        client.newCancelInstanceCommand(keyIn(call)).send().join();
      }
    };
    assertThat(state(bareTask(h.cancel(id)))).isEqualTo("TASK_STATE_CANCELED");
  }

  @Test
  void aTaskWhoseVariableIsNotVisibleYetIsNotFound() {
    // an instance that carries the task tag but no task variable, as the search shows for a moment after a start
    client.newDeployResourceCommand().addProcessModel(io.camunda.zeebe.model.bpmn.Bpmn.createExecutableProcess("ghost")
        .startEvent().endEvent().done(), "ghost.bpmn").send().join();
    client.newCreateInstanceCommand().bpmnProcessId("ghost").latestVersion()
        .tags(java.util.Set.of("a2a", "task-ghost")).send().join();
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(client.newProcessInstanceSearchRequest()
        .filter(f -> f.tags(java.util.Set.of("task-ghost"))).send().join().items()).hasSize(1));
    assertThat(errorCode(h.get("ghost"))).isEqualTo(-32001);
  }
}
