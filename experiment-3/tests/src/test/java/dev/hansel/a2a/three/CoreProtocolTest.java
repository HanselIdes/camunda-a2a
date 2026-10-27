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
import io.camunda.zeebe.model.bpmn.Bpmn;
import io.camunda.zeebe.model.bpmn.instance.zeebe.ZeebeScript;
import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"core/a2a-protocol.bpmn", "bpmn/a2a-echo.bpmn", "dmn/a2a-validate.dmn",
    "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn", "bpmn/a2a-literal-prompt.bpmn",
    "bpmn/a2a-controlled-business.bpmn", "bpmn/a2a-controlled-agent.bpmn"})
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
  void onlyAdvertisedMajorMinorIsAcceptedAndPatchDoesNotChangeTaskSemantics() {
    final var completed = task(h.send("version-contract", "Versioned result"));
    for (final String version : List.of("1.0", "1.0.2", "1.0.999")) {
      final var headers = Harness.headers();
      headers.put("a2a-version", version);
      assertThat(h.rpc(headers, Harness.request("GetTask", "{\"id\":\"" + completed.get("id") + "\"}"))
          .get("result")).as("version %s", version).isEqualTo(completed);
    }
    for (final String version : List.of("1.1", "1.9", "2.0", "0.3", "1", "1.x", "1.0.x", "")) {
      final var headers = Harness.headers();
      headers.put("a2a-version", version);
      assertThat(ValidationTest.error(h.rpc(headers, Harness.request("ListTasks", "{}"))).get("code"))
          .as("unsupported version %s", version).isEqualTo(-32009);
    }
    final var headers = Harness.headers();
    headers.remove("a2a-version");
    assertThat(ValidationTest.error(h.rpc(headers, Harness.request("ListTasks", "{}"))).get("code"))
        .as("missing version defaults to unsupported 0.3").isEqualTo(-32009);
  }

  @Test
  void cancellationResponseCannotContradictConcurrentBusinessCompletion() {
    h.agentProcess = "a2a-controlled-business";
    final var working = task(h.sendWith("cancel-completion-race", "{\"returnImmediately\":true}"));
    assertThat(state(working)).isEqualTo("TASK_STATE_WORKING");
    final var completed = new AtomicBoolean();
    h.beforeEngineCall = call -> {
      if (call.equals("POST /v2/messages/correlation") && completed.compareAndSet(false, true)) {
        context.completeUserTask("ControlledWork", Map.of());
        org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() ->
            assertThat(client.newProcessInstanceSearchRequest()
                .filter(filter -> filter.processDefinitionId("a2a-controlled-business")).send().join().items())
                .hasSize(1).allSatisfy(instance ->
                    assertThat(instance.getState().toString()).isEqualTo("COMPLETED")));
      }
    };
    final var response = h.cancel((String) working.get("id"));
    h.beforeEngineCall = call -> {};
    final var persisted = Harness.bareTask(h.get((String) working.get("id")));
    assertThat(completed).isTrue();
    assertThat(Harness.errorCode(response)).isEqualTo(-32002);
    assertThat(state(persisted)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(persisted)).isEqualTo("Controlled completion");
    assertThat((List<?>) persisted.get("artifacts")).hasSize(1);
  }

  @Test
  void cancellationInterruptsBusinessWorkAndCommitsOnlyOneTerminalOutcome() throws Exception {
    h.agentProcess = "a2a-controlled-business";
    final var working = task(h.sendWith("cancel-first", "{\"returnImmediately\":true}"));
    final String id = (String) working.get("id");
    final long workKey = controlledWorkKey();
    final var response = h.cancel(id);
    assertThat(response).as("cancel response; stored=%s; calls=%s", h.get(id), h.calls).containsKey("result");
    final var canceled = Harness.bareTask(response);
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    assertThat(canceled).doesNotContainKeys("artifacts");
    assertThat(((Map<?, ?>) canceled.get("status")).containsKey("message")).isFalse();
    assertThat(Harness.bareTask(h.get(id))).isEqualTo(canceled);
    final var lateCompletion = completeControlledWork(workKey);
    assertThat(lateCompletion.statusCode()).as(lateCompletion.body()).isIn(404, 409);
    assertThat(Harness.bareTask(h.get(id))).isEqualTo(canceled);
    assertThat(Harness.errorCode(h.cancel(id))).isEqualTo(-32002);
    assertThat(Harness.errorCode(h.followUp(id, "after-cancel", "Do not revive"))).isEqualTo(-32004);
    assertThat(Harness.bareTask(h.get(id))).isEqualTo(canceled);
    org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
      assertThat(client.newUserTaskSearchRequest()
          .filter(filter -> filter.elementId("ControlledWork")).send().join().items())
          .allSatisfy(userTask -> assertThat(userTask.getState().toString()).isEqualTo("CANCELED"));
      assertThat(client.newProcessInstanceSearchRequest()
          .filter(filter -> filter.processDefinitionId("a2a-controlled-business")).send().join().items())
          .hasSize(1).allSatisfy(instance -> assertThat(instance.getState().toString()).isEqualTo("COMPLETED"));
    });
  }

  @Test
  void lateActivatedBusinessJobCannotWriteAfterCancellationInterruptsTheAgent() throws Exception {
    h.agentProcess = "a2a-controlled-agent";
    final var working = task(h.sendWith("late-agent-job", "{\"returnImmediately\":true}"));
    final var jobs = client.newActivateJobsCommand().jobType("io.camunda.agenticai:aiagent-job-worker:1")
        .maxJobsToActivate(1).workerName("controlled-cancellation-regression").timeout(Duration.ofSeconds(30))
        .send().join().getJobs();
    assertThat(jobs).hasSize(1);
    final long jobKey = jobs.getFirst().getKey();
    final String id = (String) working.get("id");
    final var canceled = Harness.bareTask(h.cancel(id));
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    final var late = Harness.HTTP.send(
        HttpRequest.newBuilder(URI.create(h.rest + "/v2/jobs/" + jobKey + "/completion"))
            .timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString("{\"variables\":{\"agent\":{\"responseText\":"
                + "\"Must not become completion text\"},\"artifacts\":[{\"artifactId\":\"must-not-write\"}]}}"))
            .build(), HttpResponse.BodyHandlers.ofString());
    assertThat(late.statusCode()).as(late.body()).isEqualTo(404);
    assertThat(Harness.bareTask(h.get(id))).isEqualTo(canceled).doesNotContainKey("artifacts");
  }

  @Test
  void randomizedCancellationCompletionOrderingNeverContradictsStoredTerminalState() throws Exception {
    h.agentProcess = "a2a-controlled-business";
    final var random = new Random(20261027L);
    int canceled = 0;
    final int iterations = 24;
    for (int iteration = 0; iteration < iterations; iteration++) {
      final var working = task(h.sendWith("random-order-" + iteration, "{\"returnImmediately\":true}"));
      final String id = (String) working.get("id");
      final long workKey = controlledWorkKey();
      final var ready = new CountDownLatch(1);
      final var injected = new AtomicBoolean();
      final int cancelDelay = random.nextInt(80);
      final int completionDelay = random.nextInt(80);
      h.beforeEngineCall = call -> {
        if (call.equals("POST /v2/messages/correlation") && injected.compareAndSet(false, true)) {
          ready.countDown();
          pause(cancelDelay);
        }
      };
      final var completion = CompletableFuture.supplyAsync(() -> {
        await(ready);
        pause(completionDelay);
        try {
          return completeControlledWork(workKey);
        } catch (final Exception failure) {
          throw new CompletionException(failure);
        }
      });
      final var response = h.cancel(id);
      final var completionResponse = completion.get(15, TimeUnit.SECONDS);
      h.beforeEngineCall = call -> {};
      assertThat(injected).isTrue();
      assertThat(completionResponse.statusCode()).as(completionResponse.body()).isIn(200, 204, 404, 409);
      final var persisted = Harness.bareTask(h.get(id));
      if (response.containsKey("result")) {
        canceled++;
        assertThat(Harness.bareTask(response)).isEqualTo(persisted);
        assertThat(state(persisted)).isEqualTo("TASK_STATE_CANCELED");
        assertThat(persisted).doesNotContainKey("artifacts");
        assertThat(((Map<?, ?>) persisted.get("status")).containsKey("message")).isFalse();
      } else {
        assertThat(Harness.errorCode(response)).isEqualTo(-32002);
        assertThat(state(persisted)).isEqualTo("TASK_STATE_COMPLETED");
        assertThat(statusText(persisted)).isEqualTo("Controlled completion");
        assertThat((List<?>) persisted.get("artifacts")).hasSize(1);
      }
      assertThat(Harness.errorCode(h.cancel(id))).isEqualTo(-32002);
      assertThat(Harness.errorCode(h.followUp(id, "late-" + iteration, "Do not revive"))).isEqualTo(-32004);
      assertThat(Harness.bareTask(h.get(id))).isEqualTo(persisted);
    }
    System.out.printf("Cancellation/completion randomized ordering: seed=20261027 iterations=%d canceled=%d completed=%d%n",
        iterations, canceled, iterations - canceled);
  }

  @Test
  void cancellationDuringInputRequiredInterruptsTheFollowUpSubscription() {
    h.agentProcess = "a2a-controlled-business";
    final var waiting = task(h.send("cancel-input-required", "input-required"));
    assertThat(state(waiting)).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    final String id = (String) waiting.get("id");
    final var canceled = Harness.bareTask(h.cancel(id));
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    assertThat(canceled).doesNotContainKey("artifacts");
    assertThat(Harness.errorCode(h.followUp(id, "late-input", "Cannot resume"))).isEqualTo(-32004);
    assertThat(Harness.bareTask(h.get(id))).isEqualTo(canceled);
  }

  private long controlledWorkKey() {
    final var key = new AtomicLong();
    org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
      final var tasks = client.newUserTaskSearchRequest().filter(filter -> filter.elementId("ControlledWork"))
          .send().join().items().stream().filter(task -> task.getState().toString().equals("CREATED")).toList();
      assertThat(tasks).hasSize(1);
      key.set(tasks.getFirst().getUserTaskKey());
    });
    return key.get();
  }

  private HttpResponse<String> completeControlledWork(final long key) throws Exception {
    return Harness.HTTP.send(HttpRequest.newBuilder(URI.create(h.rest + "/v2/user-tasks/" + key + "/completion"))
        .timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString("{}")).build(), HttpResponse.BodyHandlers.ofString());
  }

  private static void pause(final int milliseconds) {
    try {
      Thread.sleep(milliseconds);
    } catch (final InterruptedException failure) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Race test interrupted", failure);
    }
  }

  private static void await(final CountDownLatch ready) {
    try {
      assertThat(ready.await(10, TimeUnit.SECONDS)).as("cancellation reached its engine correlation").isTrue();
    } catch (final InterruptedException failure) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("Race test interrupted before correlation", failure);
    }
  }

  @Test
  void missingRequiredCancellationHookFailsWithoutClaimingCancellation() throws Exception {
    h.agentProcess = "a2a-controlled-business";
    try (var input = getClass().getClassLoader().getResourceAsStream("bpmn/a2a-controlled-business.bpmn")) {
      final var model = Bpmn.readModelFromStream(input);
      for (final String id : List.of("A2ACancellation_di", "A2ACancelRequested_di", "A2ASetCanceled_di",
          "A2ACancelDone_di", "A2ACancelToState_di", "A2ACancelToEnd_di", "A2ACancellation", "A2ACancelMessage")) {
        final var element = model.getModelElementById(id);
        element.getParentElement().removeChildElement(element);
      }
      client.newDeployResourceCommand().addProcessModel(model, "missing-required-hook.bpmn").send().join();
    }
    final var working = task(h.sendWith("no-hook", "{\"returnImmediately\":true}"));
    final String id = (String) working.get("id");
    assertThat(Harness.errorCode(h.cancel(id))).isEqualTo(-32002);
    assertThat(state(Harness.bareTask(h.get(id)))).isEqualTo("TASK_STATE_WORKING");
    context.completeUserTask("ControlledWork", Map.of());
    org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
        assertThat(state(Harness.bareTask(h.get(id)))).isEqualTo("TASK_STATE_COMPLETED"));
  }

  @Test
  void invisibleCancellationOutcomeIsAnExplicitBoundedFailure() {
    h.agentProcess = "a2a-controlled-business";
    final var working = task(h.sendWith("cancel-index-expiry", "{\"returnImmediately\":true}"));
    final String id = (String) working.get("id");
    final var cancellationRequested = new AtomicBoolean();
    h.beforeEngineCall = call -> {
      if (call.equals("POST /v2/messages/correlation")) {
        cancellationRequested.set(true);
      }
    };
    h.afterEngineResponse = (call, body) ->
        cancellationRequested.get() && call.startsWith("POST /v2/variables/search") ? Map.of("items", List.of()) : body;
    final long start = System.nanoTime();
    final var response = h.cancel(id);
    h.beforeEngineCall = call -> {};
    h.afterEngineResponse = (call, body) -> body;
    assertThat(Harness.errorCode(response)).isEqualTo(-32603);
    assertThat(response.toString()).contains("DEADLINE_EXCEEDED").doesNotContain("result=");
    assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(12));
    assertThat(state(Harness.bareTask(h.get(id)))).isEqualTo("TASK_STATE_CANCELED");
  }

  @Test
  void businessOutcomeCanSelectMessageWithoutUsingRequestIds() throws Exception {
    for (final String desiredState : List.of("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_INPUT_REQUIRED")) {
      try (var input = getClass().getClassLoader().getResourceAsStream("bpmn/a2a-echo.bpmn")) {
        final var model = Bpmn.readModelFromStream(input);
        final var script = model.getModelElementsByType(ZeebeScript.class).iterator().next();
        script.setExpression("={state: \"" + desiredState + "\", text: \"Business reply\", responseMode: \"message\"}");
        client.newDeployResourceCommand().addProcessModel(model, "business-message-policy.bpmn").send().join();
      }
      final var result = Harness.result(h.send("ordinary-user-request", "Business input"));
      if (desiredState.equals("TASK_STATE_COMPLETED")) {
        assertThat(result).containsOnlyKeys("message");
        final var message = (Map<?, ?>) result.get("message");
        assertThat(message.get("parts")).isEqualTo(List.of(Map.of("text", "Business reply")));
        assertThat(message.get("role")).isEqualTo("ROLE_AGENT");
        final var persisted = Harness.bareTask(h.get((String) message.get("taskId")));
        assertThat(state(persisted)).isEqualTo("TASK_STATE_COMPLETED");
        assertThat(persisted).doesNotContainKey("responseMode");
      } else {
        assertThat(state(task(Map.of("result", result)))).isEqualTo(desiredState);
      }
    }
  }

  @Test
  void messageResponseModeCannotDiscardBusinessArtifacts() throws Exception {
    try (var input = getClass().getClassLoader().getResourceAsStream("bpmn/a2a-echo.bpmn")) {
      final var model = Bpmn.readModelFromStream(input);
      final var script = model.getModelElementsByType(ZeebeScript.class).iterator().next();
      script.setExpression("={state: \"TASK_STATE_COMPLETED\", text: \"Business reply\", "
          + "responseMode: \"message\", artifacts: [{artifactId: \"evidence\", "
          + "name: \"business-evidence\", parts: [{text: \"Retain this evidence\"}]}]}");
      client.newDeployResourceCommand().addProcessModel(model, "business-message-artifacts.bpmn").send().join();
    }
    final var completed = task(h.send("ordinary-artifact-request", "Business input"));
    assertThat(state(completed)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(completed.get("artifacts")).isEqualTo(List.of(Map.of(
        "artifactId", "evidence", "name", "business-evidence",
        "parts", List.of(Map.of("text", "Retain this evidence")))));
    assertThat(completed).doesNotContainKey("responseMode");
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

  @Test
  void literalPromptEncodingPreservesNumericJsonExpressionAndControlCharacterText() throws Exception {
    final var controls = new StringBuilder();
    for (char c = 0; c < 32; c++) {
      controls.append(c);
    }
    for (final String text : List.of("100 degrees Celsius to Fahrenheit.", "{\"value\":100}", "[1,2]",
        "true", "=1 + 1", "\"quoted\" and \\backslash\n\t", controls.toString(), "Unicode: \u00e9 \u6771\u4eac")) {
      final var result = client.newCreateInstanceCommand().bpmnProcessId("a2a-literal-prompt").latestVersion()
          .variables(Map.of("text", text)).withResult().fetchVariables("encoded").send().join();
      final String encoded = (String) result.getVariablesAsMap().get("encoded");
      assertThat(Harness.JSON.readValue(encoded, String.class)).isEqualTo(text);
    }
  }

  @Test
  void bothProfilesAndTemplatePersistOnlyAllowlistedNonsecretHeaders() throws Exception {
    final var factory = DocumentBuilderFactory.newInstance();
    factory.setNamespaceAware(true);
    final var expressions = new java.util.ArrayList<String>();
    for (final String resource : List.of("core/a2a-protocol.bpmn", "core-oauth/a2a-protocol.bpmn")) {
      try (var input = getClass().getClassLoader().getResourceAsStream(resource)) {
        final var properties = factory.newDocumentBuilder().parse(input)
            .getElementsByTagNameNS("http://camunda.org/schema/zeebe/1.0", "property");
        for (int i = 0; i < properties.getLength(); i++) {
          final var property = (org.w3c.dom.Element) properties.item(i);
          if (property.getAttribute("name").equals("resultExpression")) {
            expressions.add(property.getAttribute("value"));
          }
        }
      }
    }
    try (var input = getClass().getClassLoader().getResourceAsStream("core-templates/a2a-core-rpc.json")) {
      for (final var property : Harness.JSON.readTree(input).get("properties")) {
        if (property.path("id").asText().equals("resultExpression")) {
          expressions.add(property.get("value").asText());
        }
      }
    }
    assertThat(expressions).hasSize(3).allMatch(expressions.getFirst()::equals);
    try (var input = getClass().getClassLoader().getResourceAsStream("bpmn/a2a-literal-prompt.bpmn")) {
      final var model = Bpmn.readModelFromStream(input);
      final var script = model.getModelElementsByType(ZeebeScript.class).iterator().next();
      script.setExpression(expressions.getFirst());
      script.setResultVariable("mapped");
      client.newDeployResourceCommand().addProcessModel(model, "header-mapping-regression.bpmn").send().join();
    }
    final var headers = Map.of("content-type", "application/a2a+json", "a2a-version", "1.0",
        "x-a2a-api-key", "MUST-NOT-PERSIST", "authorization", "Bearer MUST-NOT-PERSIST",
        "cookie", "session=MUST-NOT-PERSIST", "unexpected", "MUST-NOT-PERSIST");
    final var body = Map.of("jsonrpc", "2.0", "id", "header-check", "method", "GetTask");
    final var result = client.newCreateInstanceCommand().bpmnProcessId("a2a-literal-prompt").latestVersion()
        .variables(Map.of("request", Map.of("headers", headers, "body", body)))
        .withResult().fetchVariables("mapped").send().join().getVariablesAsMap().get("mapped");
    assertThat(result).isEqualTo(Map.of("rpc", body, "hdr",
        Map.of("content-type", "application/a2a+json", "a2a-version", "1.0")));
    assertThat(result.toString()).doesNotContain("MUST-NOT-PERSIST");
  }
}
