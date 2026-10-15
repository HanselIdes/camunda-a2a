package dev.hansel.a2a;

import static dev.hansel.a2a.Harness.bareTask;
import static dev.hansel.a2a.Harness.state;
import static dev.hansel.a2a.Harness.statusText;
import static dev.hansel.a2a.Harness.task;
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
@TestDeployment(resources = {"bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn", "bpmn/a2a-correlate.bpmn",
    "bpmn/a2a-publish-reply.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn", "dmn/capitals.dmn"})
class AgentTest {
  static final JobSelector AGENT = JobSelectors.byJobType("io.camunda.agenticai:aiagent:subprocess:2");

  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
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
  void agentAnswersAfterUsingTheTimeTool() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "What time is it?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("get_current_time"));
    toolResult("utcTime");
    finish("It is 10:00 UTC.", List.of(Map.of("name", "get_current_time", "arguments", Map.of())));

    final var task = task(response.join());
    assertThat(state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(task)).isEqualTo("It is 10:00 UTC.");
    final var artifacts = (List<Map<String, Object>>) task.get("artifacts");
    assertThat(artifacts).hasSize(1);
    assertThat(artifacts.get(0)).containsEntry("name", "tool-trace");
    assertThat(artifacts.get(0).get("parts").toString()).contains("get_current_time");
  }

  @Test
  void temperatureToolConvertsBothWays() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "100 C in F?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("convert_temperature")
        .variables(Map.of("toolCall", Map.of("degrees", 100, "unit", "celsius"))));
    assertThat(toolResult("fahrenheit").toString()).contains("212");
    finish("212 F", List.of());
    assertThat(state(task(response.join()))).isEqualTo("TASK_STATE_COMPLETED");

    final var second = CompletableFuture.supplyAsync(() -> h.send("m-2", "50 F in C?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("convert_temperature")
        .variables(Map.of("toolCall", Map.of("degrees", 50, "unit", "Fahrenheit"))));
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(
        client.newVariableSearchRequest().filter(f -> f.name("toolCallResults")).send().join().items().stream()
            .anyMatch(v -> v.getValue().contains("celsius") && v.getValue().contains("10"))).isTrue());
    finish("10 C", List.of());
    assertThat(state(task(second.join()))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void capitalToolUsesTheDecisionTable() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Capital of Japan?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("capital_of")
        .variables(Map.of("toolCall", Map.of("country", "JAPAN"))));
    toolResult("Tokyo");
    finish("Tokyo", List.of());
    assertThat(state(task(response.join()))).isEqualTo("TASK_STATE_COMPLETED");

    final var unknown = CompletableFuture.supplyAsync(() -> h.send("m-2", "Capital of Atlantis?"));
    context.completeJobOfAdHocSubProcess(AGENT, r -> r.activateElement("capital_of")
        .variables(Map.of("toolCall", Map.of("country", "Atlantis"))));
    toolResult("unknown");
    finish("I do not know.", List.of());
    assertThat(state(task(unknown.join()))).isEqualTo("TASK_STATE_COMPLETED");
  }

  @Test
  void agentCanAskForInputAndContinueAfterTheFollowUp() {
    final var first = CompletableFuture.supplyAsync(() -> h.send("m-1", "Convert a temperature"));
    finish("NEED_INPUT: Which value and unit?", List.of());
    final var waiting = task(first.join());
    assertThat(state(waiting)).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    assertThat(statusText(waiting)).isEqualTo("Which value and unit?");

    final var second = CompletableFuture.supplyAsync(() -> h.followUp((String) waiting.get("id"), "m-2", "100 celsius"));
    finish("212 F", List.of());
    final var done = task(second.join());
    assertThat(state(done)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(Harness.history(done)).hasSize(4);
  }

  @Test
  void taskAnswersGetTaskAndCancelWhileTheAgentIsWorking() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Slow question"));
    final String[] id = new String[1];
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> {
      final var tasks = client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-task"))
          .send().join().items();
      assertThat(tasks).hasSize(1);
      final var vars = client.newVariableSearchRequest().filter(f -> f.name("taskId")).send().join().items();
      assertThat(vars).isNotEmpty();
      id[0] = vars.get(0).getValue().replace("\"", "");
    });
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(
        () -> assertThat(state(bareTask(h.get(id[0])))).isEqualTo("TASK_STATE_WORKING"));
    final var canceled = bareTask(h.cancel(id[0]));
    assertThat(state(canceled)).isEqualTo("TASK_STATE_CANCELED");
    // the original SendMessage learns the final state by its probe after the reply timer
    context.increaseTime(Duration.ofSeconds(30));
    assertThat(state(task(response.join()))).isEqualTo("TASK_STATE_CANCELED");
  }

  @Test
  void sendMessageReturnsWorkingStateWhenTheAgentIsSlow() {
    final var response = CompletableFuture.supplyAsync(() -> h.send("m-1", "Slow question"));
    Awaitility.await().atMost(Duration.ofSeconds(20)).until(
        () -> client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-rpc"))
            .send().join().items().size() == 1);
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> assertThat(
        client.newVariableSearchRequest().filter(f -> f.name("pending")).send().join().items()).isNotEmpty());
    context.increaseTime(Duration.ofSeconds(30));
    final var task = task(response.join());
    assertThat(state(task)).isEqualTo("TASK_STATE_WORKING");
    // the agent later answers and the task completes, observable with GetTask
    finish("Done.", List.of());
    Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(
        () -> assertThat(state(bareTask(h.get((String) task.get("id"))))).isEqualTo("TASK_STATE_COMPLETED"));
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
