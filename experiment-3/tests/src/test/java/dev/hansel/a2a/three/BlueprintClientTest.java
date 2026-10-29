package dev.hansel.a2a.three;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.assertions.JobSelectors;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.awaitility.Awaitility;

@CamundaProcessTest
@TestDeployment(resources = {
    "demo/01-client-agent.bpmn",
    "demo/04-client-agent-ask.form",
    "demo/05-client-agent-confirm.form",
    "demo/06-client-agent-result.form"
})
class BlueprintClientTest {
  CamundaClient client;
  CamundaProcessTestContext context;

  Map<String, Object> remoteHistory(final Map<String, Object> response, final Map<String, Object> task) {
    return Map.of("conversation", Map.of("messages", List.of(Map.of(
        "role", "tool_call_result", "results", List.of(Map.of(
            "name", "SendA2AMessage", "content", List.of(Map.of(
                "type", "object", "content", Map.of("toolCallResult",
                    Map.of("response", response, "task", task))))))))));
  }

  void callRemote(final Map<String, Object> history) {
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId("ClientAgent"),
        result -> result.activateElement("SendA2AMessage").variables(Map.of(
            "agentContext", history, "toolCall", Map.of("text", "Review synthetic data"))));
  }

  @Test
  void pollingRecoveryKeepsTheWorkingTaskWithoutResendingMessages() {
    final long key = client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("question", "Review synthetic data")).send().join().getProcessInstanceKey();
    final var instance = ProcessInstanceSelectors.byKey(key);
    context.completeJob(JobSelectors.byElementId("DiscoverAgentCard"), Map.of("agentCard", Map.of(
        "name", "Synthetic agent", "skills", List.of(Map.of("name", "Review")))));
    final Map<String, Object> working = Map.of("id", "accepted-task", "contextId", "retained-context",
        "status", Map.of("state", "TASK_STATE_WORKING"));
    final Map<String, Object> error = Map.of("error", Map.of(
        "code", -32603, "message", "Temporary polling failure"));
    callRemote(Map.of("conversation", Map.of("messages", List.of())));
    assertThat(instance).hasActiveElements("SendRemoteMessage");
    context.completeJob(JobSelectors.byElementId("SendRemoteMessage"),
        Map.of("remoteResponse", Map.of("result", working), "acceptedTask", working));
    for (int attempt = 1; attempt <= 2; attempt++) {
      assertThat(instance).hasActiveElements("WaitBeforeRemotePoll");
      context.increaseTime(Duration.ofSeconds(3));
      context.completeJob(JobSelectors.byElementId("GetA2ATask"),
          Map.of("remoteResponse", error, "acceptedTask", working));
      assertThat(instance).hasCompletedElement("SendA2AMessage", attempt)
          .hasCompletedElement("SendRemoteMessage", 1)
          .hasCompletedElement("GetA2ATask", attempt).hasNoActiveIncidents();
      callRemote(remoteHistory(error, working));
    }
    assertThat(instance).hasActiveElements("WaitBeforeRemotePoll")
        .hasCompletedElement("SendRemoteMessage", 1);
    context.increaseTime(Duration.ofSeconds(3));
    final Map<String, Object> completed = Map.of("id", "accepted-task", "contextId", "retained-context",
        "status", Map.of("state", "TASK_STATE_COMPLETED"));
    context.completeJob(JobSelectors.byElementId("GetA2ATask"),
        Map.of("remoteResponse", Map.of("result", completed), "acceptedTask", completed));
    assertThat(instance).hasCompletedElement("SendA2AMessage", 3)
        .hasCompletedElement("SendRemoteMessage", 1).hasCompletedElement("GetA2ATask", 3);
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId("ClientAgent"),
        Map.of("agent", Map.of("responseText", "Completed",
            "context", remoteHistory(Map.of("result", completed), completed))),
        result -> result.completionConditionFulfilled(true));
    context.completeUserTask("ReviewClientResult", Map.of("clientSatisfied", "yes"));
    assertThat(instance).isCompleted();
  }

  void assertBudgets(final long key, final Integer... expected) {
    Awaitility.await().untilAsserted(() -> {
      final var values = client.newVariableSearchRequest()
          .filter(filter -> filter.processInstanceKey(key).name("data")).send().join().items();
      final var ceilings = new java.util.ArrayList<Integer>();
      for (final var value : values) {
        ceilings.add(new ObjectMapper().readTree(value.getValue()).at("/limits/maxModelCalls").asInt());
      }
      assertThat(ceilings).containsExactlyInAnyOrder(expected);
    });
  }

  @Test
  void feedbackRetainsContextAndReentersTheAgentBeforeAcceptance() {
    final long key = client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("question", "Review synthetic data")).send().join().getProcessInstanceKey();
    final var instance = ProcessInstanceSelectors.byKey(key);
    context.completeJob(JobSelectors.byElementId("DiscoverAgentCard"), Map.of("agentCard", Map.of(
        "name", "Synthetic agent", "skills", List.of(Map.of("name", "Review")))));
    assertThat(instance).hasCompletedElements("DiscoverAgentCard");
    assertThat(instance).hasNoActiveIncidents().hasActiveElements("ClientAgent");
    assertBudgets(key, 8);
    final Map<String, Object> priorContext = Map.of(
        "metrics", Map.of("modelCalls", 8),
        "conversation", Map.of("messages", List.of(Map.of("role", "user", "content", "Original request"))));
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId("ClientAgent"),
        Map.of("agent", Map.of("responseText", "First answer", "context", priorContext)),
        result -> result.completionConditionFulfilled(true));
    context.completeUserTask("ReviewClientResult",
        Map.of("clientSatisfied", "no", "clientFeedback", "Please clarify the result"));
    assertThat(instance).hasCompletedElement("ClientJoin", 2)
        .hasCompletedElement("DiscoverAgentCard", 1)
        .hasVariable("question", "Please clarify the result")
        .hasVariable("clientAgent", Map.of("responseText", "First answer", "context", priorContext));
    assertBudgets(key, 8, 16);
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId("ClientAgent"),
        Map.of("agent", Map.of("responseText", "Clarified answer", "context", priorContext)),
        result -> result.completionConditionFulfilled(true));
    context.completeUserTask("ReviewClientResult", Map.of("clientSatisfied", "yes"));
    assertThat(instance).isCompleted().hasCompletedElement("ClientAgent", 2)
        .hasCompletedElement("ReviewClientResult", 2);
  }
}
