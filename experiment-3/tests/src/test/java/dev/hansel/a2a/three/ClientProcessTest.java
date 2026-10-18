package dev.hansel.a2a.three;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.assertions.JobSelectors;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * Tier 1 for the client diagram: every path through a2a-client, with connectors off. The test plays the connectors:
 * it completes the HTTP JSON jobs with what their result expressions would produce, completes the AI agent jobs with
 * the tool activations a model would choose, and correlates the message that the A2A 1.0 Client Webhook would
 * correlate, with the same name, key and variable. Assertions are about reachability and routing only.
 */
class ClientProcessTest {
  static final String CLIENT_REPLY_MESSAGE = "6fa772b1-6d46-45c4-a629-217da0f2ab61";
  static final String HTTP = "io.camunda:http-json:1";
  static final String AGENT = "Client_AI_Agent";

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension();

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deploy() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
    client.newDeployResourceCommand().addResourceFromClasspath("bpmn/a2a-client.bpmn")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-initial-request.form")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-user-feedback.form")
        .addResourceFromClasspath("forms/ai-agent-chat-human-send-email-request.form").send().join();
    // every HTTP JSON job completes with what its result expression would have produced
    context.mockJobWorker(HTTP).withHandler((jobClient, job) -> {
      final Map<String, Object> vars = switch (job.getElementId()) {
        case "Client_FetchAgentCard" -> Map.of("remoteAgentCard", Map.of("result", Map.of("name", "Task agent",
            "supportedInterfaces", List.of(Map.of("url", "http://agent/a2a", "protocolBinding", "JSONRPC",
                "protocolVersion", "1.0")))));
        case "Tool_AskRemoteAgent" -> Map.of("agentResponse", Map.of("result", Map.of("id", "client-task",
            "status", Map.of("state", "TASK_STATE_SUBMITTED"))));
        default -> Map.of("toolCallResult", "ok");
      };
      jobClient.newCompleteCommand(job).variables(vars).send().join();
    });
  }

  long startConversation() {
    return client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("inputText", "Convert a temperature for me")).send().join().getProcessInstanceKey();
  }

  /** Correlates like the inbound connector does, once the subscription is open (the search API lags the engine). */
  void correlate(final String name, final String key, final Map<String, Object> variables) {
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> assertThat(
        client.newMessageSubscriptionSearchRequest().filter(f -> f.messageName(name).correlationKey(key)).send()
            .join().items()).isNotEmpty());
    client.newPublishMessageCommand().messageName(name).correlationKey(key).timeToLive(Duration.ofSeconds(30))
        .variables(variables).send().join();
  }

  /** One step of the AI agent: activate one tool with the toolCall a model would send. */
  void agentCalls(final String tool, final Map<String, Object> toolCall) {
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId(AGENT),
        r -> r.activateElement(tool).variables(Map.of("toolCall", toolCall, "toolCallResult", "")));
  }

  /** The AI agent's final step: no more tools, the agent is done. */
  void agentFinishes(final String responseText) {
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId(AGENT),
        Map.of("agent", Map.of("responseText", responseText)), r -> r.completionConditionFulfilled(true));
  }

  @Test
  void conversationUsesEveryToolAsksTheRemoteAgentAndLoopsUntilTheUserIsSatisfied() {
    final long key = startConversation();
    final var instance = ProcessInstanceSelectors.byKey(key);
    assertThat(instance).hasCompletedElements("Client_Start", "Client_FetchAgentCard");

    agentCalls("Tool_ListUsers", Map.of());
    assertThat(instance).hasCompletedElements("Tool_ListUsers");
    agentCalls("Tool_LoadUserByID", Map.of("id", 1));
    assertThat(instance).hasCompletedElements("Tool_LoadUserByID");
    agentCalls("Tool_AskHumanToSendEmail", Map.of("instructions", "send it", "recipient_name", "Ann",
        "recipient_email", "ann@example.com", "email_subject", "Hi", "email_body", "Hello"));
    context.completeUserTask("Tool_AskHumanToSendEmail", Map.of("emailOk", true, "operatorFeedback", "sent"));
    assertThat(instance).hasCompletedElements("Tool_AskHumanToSendEmail");

    // the remote agent answers by push: the webhook event waits on the task ID of the send response
    agentCalls("Tool_AskRemoteAgent", Map.of("text", "Convert 100 degrees"));
    assertThat(instance).hasCompletedElements("Tool_AskRemoteAgent").hasActiveElements("Tool_RemoteAgentReplied");
    correlate(CLIENT_REPLY_MESSAGE, "client-task", Map.of("toolCallResult", Map.of("id", "client-task")));
    assertThat(instance).hasCompletedElements("Tool_RemoteAgentReplied");

    // not satisfied once (loop back with the follow-up), then satisfied
    agentFinishes("100 C is 212 F");
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", false, "followUpInput", "And 0 C?"));
    assertThat(instance).hasCompletedElement("Client_JoinGateway", 2);
    agentFinishes("0 C is 32 F");
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", true));
    assertThat(instance).isCompleted().hasCompletedElements("Client_End");
  }

  @Test
  void theClientReadsTheCardOnceAndPutsItIntoTheAgentsPrompt() {
    final long key = startConversation();
    assertThat(ProcessInstanceSelectors.byKey(key)).hasCompletedElement("Client_FetchAgentCard", 1);
    agentFinishes("hi");
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", true));
    assertThat(ProcessInstanceSelectors.byKey(key)).isCompleted().hasCompletedElement("Client_FetchAgentCard", 1);
  }
}
