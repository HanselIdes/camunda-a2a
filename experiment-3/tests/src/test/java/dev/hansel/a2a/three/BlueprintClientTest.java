package dev.hansel.a2a.three;

import static io.camunda.process.test.api.CamundaAssert.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.assertions.JobSelectors;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

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

  @Test
  void feedbackRetainsContextAndReentersTheAgentBeforeAcceptance() {
    final long key = client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("question", "Review synthetic data")).send().join().getProcessInstanceKey();
    final var instance = ProcessInstanceSelectors.byKey(key);
    context.completeJob(JobSelectors.byElementId("DiscoverAgentCard"), Map.of("agentCard", Map.of(
        "name", "Synthetic agent", "skills", List.of(Map.of("name", "Review")))));
    assertThat(instance).hasCompletedElements("DiscoverAgentCard");
    assertThat(instance).hasNoActiveIncidents().hasActiveElements("ClientAgent");
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
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId("ClientAgent"),
        Map.of("agent", Map.of("responseText", "Clarified answer", "context", priorContext)),
        result -> result.completionConditionFulfilled(true));
    context.completeUserTask("ReviewClientResult", Map.of("clientSatisfied", "yes"));
    assertThat(instance).isCompleted().hasCompletedElement("ClientAgent", 2)
        .hasCompletedElement("ReviewClientResult", 2);
  }
}
