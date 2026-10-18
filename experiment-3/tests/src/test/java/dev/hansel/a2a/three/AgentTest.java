package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.bareTask;
import static dev.hansel.a2a.three.Harness.state;
import static dev.hansel.a2a.three.Harness.statusText;
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

/**
 * The agent path with the model mocked out: the AI Agent sub-process job is completed by the test, which also
 * activates the tools, so the tools and the way their results reach the task are proven without an LLM.
 */
@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-protocol.bpmn", "bpmn/a2a-agent.bpmn", "dmn/a2a-validate.dmn"})
class AgentTest {
  static final JobSelector AGENT = JobSelectors.byJobType("io.camunda.agenticai:aiagent:subprocess:2");

  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
    h.agentProcess = "a2a-agent";
  }

  static Map<String, Object> agentResult(final String text, final List<Map<String, Object>> toolCalls) {
    final var messages = new java.util.ArrayList<Map<String, Object>>();
    messages.add(Map.of("role", "user", "content", List.of(Map.of("type", "text", "text", "hi"))));
    if (!toolCalls.isEmpty()) {
      messages.add(Map.of("role", "assistant", "toolCalls", toolCalls));
    }
    messages.add(Map.of("role", "assistant", "content", List.of(Map.of("type", "text", "text", text))));
    return Map.of("agent", Map.of("responseText", text,
        "context", Map.of("conversation", Map.of("type", "in-process", "messages", messages))));
  }

  void finish(final String text, final List<Map<String, Object>> toolCalls) {
    context.completeJobOfAdHocSubProcess(AGENT, agentResult(text, toolCalls),
        r -> r.completionConditionFulfilled(true).cancelRemainingInstances(true));
  }

  Object toolResult(final String contains) {
    final var holder = new Object[1];
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> {
      final var items = client.newVariableSearchRequest().filter(f -> f.name("toolCallResults")).send().join().items();
      assertThat(items).isNotEmpty();
      final String value = items.get(items.size() - 1).getValue();
      assertThat(value).contains(contains);
      holder[0] = value;
    });
    return holder[0];
  }

  @Test
  void agentAnswersAfterUsingTheTemperatureTool() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "100 C in F?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("convert_temperature")
        .variables(Map.of("toolCall", Map.of("value", 100, "fromUnit", "celsius", "toUnit", "fahrenheit"))));
    assertThat(toolResult("fahrenheit").toString()).contains("212");
    finish("100 C is 212 F.", List.of(Map.of("name", "convert_temperature", "arguments", Map.of())));

    final var task = task(response.join());
    assertThat(state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(task)).isEqualTo("100 C is 212 F.");
    final var artifacts = (List<Map<String, Object>>) task.get("artifacts");
    assertThat(artifacts).extracting(a -> a.get("name")).containsExactly("answer", "tool-trace");
    assertThat(artifacts.get(0).get("parts").toString()).contains("100 C is 212 F.");
    assertThat(artifacts.get(1).get("parts").toString()).contains("convert_temperature");
  }

  @Test
  void temperatureToolConvertsBetweenTheThreeUnits() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "50 F in K?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("convert_temperature")
        .variables(Map.of("toolCall", Map.of("value", 50, "fromUnit", "fahrenheit", "toUnit", "kelvin"))));
    assertThat(toolResult("kelvin").toString()).contains("283.15");
    finish("283.15 K", List.of());
    assertThat(state(task(response.join()))).isEqualTo("TASK_STATE_COMPLETED");

    final var second = CompletableFuture.supplyAsync(() -> h.send("m-2", "0 K in C?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("convert_temperature")
        .variables(Map.of("toolCall", Map.of("value", 0, "fromUnit", "kelvin", "toUnit", "celsius"))));
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(
        client.newVariableSearchRequest().filter(f -> f.name("toolCallResults")).send().join().items().stream()
            .anyMatch(v -> v.getValue().contains("celsius") && v.getValue().contains("-273.15"))).isTrue());
    finish("-273.15 C", List.of());
    assertThat(state(task(second.join()))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void techStuffToolReturnsTheCatalogToTheAgent() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Which phones do you know?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("list_tech_devices"));
    toolResult("Apple iPhone");
    finish("The catalog lists an iPhone and a Galaxy Z Fold2.", List.of());
    assertThat(state(task(response.join()))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void agentCanAskForInputAndContinueAfterTheFollowUp() {
    final var first = CompletableFuture.supplyAsync(() -> h.send("m-1", "Convert a temperature"));
    finish("NEED_INPUT: Which value and unit?", List.of());
    final var waiting = task(first.join());
    assertThat(state(waiting)).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    assertThat(statusText(waiting)).isEqualTo("Which value and unit?");
    assertThat(((List<Map<String, Object>>) waiting.get("artifacts")).get(0)).containsEntry("name", "question");

    final var second = CompletableFuture.supplyAsync(() -> h.followUp((String) waiting.get("id"), "m-2", "100 celsius"));
    finish("212 F", List.of());
    final var done = task(second.join());
    assertThat(state(done)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(Harness.history(done)).hasSize(4);
  }

  /** The id of the one running agent task, read from the task variable of its process instance. */
  String runningTaskId() {
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
    return id[0];
  }

  /** Waits for an open request in real time: moving the engine clock would also expire the request itself. */
  <T> T join(final CompletableFuture<T> future) throws Exception {
    return future.get(60, java.util.concurrent.TimeUnit.SECONDS);
  }

  @Test
  void taskAnswersGetTaskAndCancelWhileTheAgentIsWorking() throws Exception {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Slow question"));
    final String id = runningTaskId();
    assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_WORKING");
    final var canceled = bareTask(h.cancel(id));
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    // the blocking SendMessage waits for a settled state, and canceled is one
    assertThat(state(task(join(response)))).isEqualTo("TASK_STATE_CANCELED");
    assertThat(client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-agent")
        .state(io.camunda.client.api.search.enums.ProcessInstanceState.ACTIVE)).send().join().items()).isEmpty();
  }

  @Test
  void sendMessageReturnsWorkingStateWhenTheAgentIsSlow() throws Exception {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Slow question"));
    final String id = runningTaskId();
    // the endpoint stops waiting after its last read and returns the task as it is
    final var task = task(join(response));
    assertThat(task.get("id")).isEqualTo(id);
    assertThat(state(task)).isEqualTo("TASK_STATE_WORKING");
    // the agent later answers and the task completes, observable with GetTask
    finish("Done.", List.of());
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(
        () -> assertThat(state(bareTask(h.get(id)))).isEqualTo("TASK_STATE_COMPLETED"));
  }

  @Test
  void agentFailureFailsTheTask() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Anything"));
    context.throwBpmnErrorFromJob(AGENT, "AGENT_FAILED");
    final var task = task(response.join());
    assertThat(state(task)).isEqualTo("TASK_STATE_FAILED");
    assertThat(statusText(task)).contains("could not complete");
    // a failed task is terminal
    assertThat(Harness.errorCode(h.cancel((String) task.get("id")))).isEqualTo(-32002);
  }
}
