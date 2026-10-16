package dev.hansel.a2a.two;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.assertions.ElementSelectors;
import io.camunda.process.test.api.assertions.JobSelectors;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * Tier 1: every path through a2a-two-agents, with connectors off. The test plays the connectors: it completes the
 * HTTP JSON jobs with what their result expressions would produce, completes the AI agent jobs with the tool
 * activations a model would choose, and correlates the messages the A2A 1.0 inbound templates would correlate,
 * with the same names, keys and variables. Assertions are about reachability and routing only.
 */
class TwoAgentsProcessTest {
  static final String CARD_MESSAGE = "1e7e267d-03e4-4cf4-bc25-5347f8a7f5b2";
  static final String CLIENT_REPLY_MESSAGE = "6fa772b1-6d46-45c4-a629-217da0f2ab61";
  static final String TASK_MESSAGE = "a2a-task-received";
  static final String FOLLOW_UP_MESSAGE = "a2a-task-follow-up";
  static final String HTTP = "io.camunda:http-json:1";

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension();

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deploy() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(30));
    client.newDeployResourceCommand().addResourceFromClasspath("bpmn/a2a-two-agents.bpmn")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-initial-request.form")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-user-feedback.form")
        .addResourceFromClasspath("forms/ai-agent-chat-human-send-email-request.form").send().join();
    // every HTTP JSON job completes with what its result expression would have produced
    context.mockJobWorker(HTTP).withHandler((jobClient, job) -> {
      final Map<String, Object> vars = switch (job.getElementId()) {
        case "Client_FetchAgentCard" -> Map.of("remoteAgentCard", Map.of("result", Map.of("name", "Task agent",
            "supportedInterfaces", java.util.List.of(Map.of("url", "http://agent/a2a-server?agent=x",
                "protocolBinding", "JSONRPC", "protocolVersion", "1.0")))));
        case "Tool_AskRemoteAgent" -> Map.of("agentResponse", Map.of("result", Map.of("id", "client-task",
            "status", Map.of("state", "TASK_STATE_SUBMITTED"))));
        case "Server_PushNotification" -> Map.of("a2aPushStatus", 200);
        default -> Map.of("toolCallResult", "ok");
      };
      jobClient.newCompleteCommand(job).variables(vars).send().join();
    });
  }

  long startConversation() {
    return client.newCreateInstanceCommand().bpmnProcessId("a2a-two-agents").latestVersion()
        .variables(Map.of("inputText", "Convert a temperature for me")).send().join().getProcessInstanceKey();
  }

  String agentId(final long instance) {
    final var id = new String[1];
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
      final var items = client.newVariableSearchRequest()
          .filter(f -> f.processInstanceKey(instance).name("a2aAgentId")).send().join().items();
      assertThat(items).hasSize(1);
      id[0] = items.get(0).getValue().replace("\"", "");
    });
    return id[0];
  }

  /** Correlates like an inbound connector does, once the subscription is open (the search API lags the engine). */
  void correlate(final String name, final String key, final Map<String, Object> variables) {
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> assertThat(
        client.newMessageSubscriptionSearchRequest().filter(f -> f.messageName(name).correlationKey(key)).send()
            .join().items()).isNotEmpty());
    client.newPublishMessageCommand().messageName(name).correlationKey(key).timeToLive(Duration.ofSeconds(30))
        .variables(variables).send().join();
  }

  /** One step of an AI agent: activate one tool with the toolCall a model would send. */
  void agentCalls(final String agent, final String tool, final Map<String, Object> toolCall) {
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId(agent),
        r -> r.activateElement(tool).variables(Map.of("toolCall", toolCall, "toolCallResult", "")));
  }

  /** The AI agent's final step: no more tools, the agent is done. */
  void agentFinishes(final String agent, final String responseText) {
    context.completeJobOfAdHocSubProcess(JobSelectors.byElementId(agent),
        Map.of("agent", Map.of("responseText", responseText)), r -> r.completionConditionFulfilled(true));
  }

  /** What A2A 1.0 Server: SendMessage (new task) correlates for a SendMessage without taskId. */
  void sendNewTask(final String agentId, final String taskId, final String text) {
    final Map<String, Object> vars = new HashMap<>();
    vars.put("taskId", taskId);
    vars.put("contextId", "ctx-" + taskId);
    vars.put("messageText", text);
    vars.put("pushNotification", Map.of("url", "http://client/reply", "token", "t"));
    vars.put("taskState", "TASK_STATE_SUBMITTED");
    correlate(TASK_MESSAGE, agentId, vars);
  }

  /** What A2A 1.0 Server: SendMessage (follow-up) correlates for a SendMessage with this taskId. */
  void sendFollowUp(final String taskId, final String text) {
    correlate(FOLLOW_UP_MESSAGE, taskId, Map.of("toolCallResult", text, "messageText", text,
            "pushNotification", Map.of("url", "http://client/reply", "token", "t2")));
  }

  void serverPushes(final String state, final String text) {
    agentCalls("Activity_10vg0yz", "Server_PushNotification", Map.of("state", state, "text", text));
  }

  @Test
  void conversationUsesEveryClientToolAsksTwiceAndTheServerTaskGoesThroughInputRequired() {
    final long key = startConversation();
    final var instance = ProcessInstanceSelectors.byKey(key);
    assertThat(instance).hasCompletedElements("Client_Start", "Client_FetchAgentCard");
    final String agentId = agentId(key);

    // the client reads the card: GET Agent Card fires in the same instance
    correlate(CARD_MESSAGE, agentId, Map.of());
    assertThat(instance).hasCompletedElements("Server_CardRequested", "Server_CardServed");

    // client agent: each tool once
    agentCalls("Client_AI_Agent", "Tool_ListUsers", Map.of());
    assertThat(instance).hasCompletedElements("Tool_ListUsers");
    agentCalls("Client_AI_Agent", "Tool_LoadUserByID", Map.of("id", 1));
    assertThat(instance).hasCompletedElements("Tool_LoadUserByID");
    agentCalls("Client_AI_Agent", "Tool_AskHumanToSendEmail", Map.of("instructions", "send it",
        "recipient_name", "Ann", "recipient_email", "ann@example.com", "email_subject", "Hi", "email_body", "Hello"));
    context.completeUserTask("Tool_AskHumanToSendEmail", Map.of("emailOk", true, "operatorFeedback", "sent"));
    assertThat(instance).hasCompletedElements("Tool_AskHumanToSendEmail");
    agentCalls("Client_AI_Agent", "Tool_AskRemoteAgent", Map.of("text", "Convert 100 degrees"));
    assertThat(instance).hasCompletedElements("Tool_AskRemoteAgent").hasActiveElements("Tool_RemoteAgentReplied");

    // the SendMessage arrives at the server: A2A task fires, the server agent asks a clarifying question
    sendNewTask(agentId, "task-1", "Convert 100 degrees");
    agentCalls("Activity_10vg0yz", "Activity_0x3prgn", Map.of());
    assertThat(instance).hasCompletedElements("Server_MessageReceived", "Activity_0x3prgn");
    serverPushes("TASK_STATE_INPUT_REQUIRED", "Celsius or Fahrenheit?");
    assertThat(instance).hasCompletedElements("Server_PushNotification").hasActiveElements("Event_1553b23");

    // the push reaches the client, the client answers on the same task
    correlate(CLIENT_REPLY_MESSAGE, "client-task", Map.of("toolCallResult", Map.of("id", "task-1")));
    assertThat(instance).hasCompletedElements("Tool_RemoteAgentReplied");
    sendFollowUp("task-1", "Celsius");
    assertThat(instance).hasCompletedElements("Event_1553b23");

    // the server agent converts with its tool: the script task returns value and unit
    agentCalls("Activity_10vg0yz", "Tool_ConvertTemperature",
        Map.of("value", 212, "fromUnit", "fahrenheit", "toUnit", "celsius"));
    assertThat(instance).hasCompletedElements("Tool_ConvertTemperature");
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> assertThat(
        client.newVariableSearchRequest().filter(f -> f.processInstanceKey(key).name("toolCallResult")).send().join()
            .items()).extracting(v -> v.getValue()).contains("{\"value\":100,\"unit\":\"celsius\"}"));

    // the server agent finishes the task; its event sub-process ends, the instance does not
    serverPushes("TASK_STATE_COMPLETED", "100 C is 212 F");
    assertThat(instance).hasCompletedElements("Event_08iu22r");
    agentFinishes("Activity_10vg0yz", "done");
    assertThat(instance).isActive().hasCompletedElements("Gateway_0oexjso", "Server_End");

    // client: not satisfied once (loop back), then satisfied
    agentFinishes("Client_AI_Agent", "100 C is 212 F");
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", false, "followUpInput", "And 0 C?"));
    assertThat(instance).hasCompletedElement("Client_JoinGateway", 2);
    agentFinishes("Client_AI_Agent", "0 C is 32 F");
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", true));
    assertThat(instance).isCompleted().hasCompletedElements("Client_End");
  }

  @Test
  void failedCanceledAndUnknownTasksEndTheirEventSubProcessAtTheMatchingEndEvent() {
    final long key = startConversation();
    final var instance = ProcessInstanceSelectors.byKey(key);
    final String agentId = agentId(key);

    sendNewTask(agentId, "task-failed", "x");
    serverPushes("TASK_STATE_FAILED", "cannot help");
    agentFinishes("Activity_10vg0yz", "failed");
    assertThat(instance).hasCompletedElements("Event_1l0zugo");

    sendNewTask(agentId, "task-canceled", "y");
    serverPushes("TASK_STATE_CANCELED", "canceled");
    agentFinishes("Activity_10vg0yz", "canceled");
    assertThat(instance).hasCompletedElements("Event_00drhwt");

    // the agent never pushes: taskState stays TASK_STATE_SUBMITTED, which the gateway treats as unknown
    sendNewTask(agentId, "task-silent", "z");
    agentFinishes("Activity_10vg0yz", "silent");
    assertThat(instance).hasCompletedElements("Event_0qrssbs");

    // three tasks ended, the conversation is still running
    assertThat(instance).isActive().hasCompletedElement("Activity_0u82j95", 3);
  }

  @Test
  void twoTasksInTheSameInstanceKeepTheirOwnTaskVariables() {
    final long key = startConversation();
    final var instance = ProcessInstanceSelectors.byKey(key);
    final String agentId = agentId(key);

    sendNewTask(agentId, "task-a", "first");
    serverPushes("TASK_STATE_INPUT_REQUIRED", "question a");
    assertThat(instance).hasActiveElement("Event_1553b23", 1);
    sendNewTask(agentId, "task-b", "second");
    serverPushes("TASK_STATE_INPUT_REQUIRED", "question b");
    assertThat(instance).hasActiveElement("Event_1553b23", 2).hasActiveElement("Activity_0u82j95", 2);

    // each A2A task event sub-process holds its own taskId and state; nothing leaked to the process scope
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
      final var runs = client.newElementInstanceSearchRequest()
          .filter(f -> f.processInstanceKey(key).elementId("Activity_0u82j95")).send().join().items().stream()
          .map(e -> e.getElementInstanceKey()).toList();
      assertThat(runs).hasSize(2);
      final var taskIds = client.newVariableSearchRequest().filter(f -> f.processInstanceKey(key).name("taskId"))
          .send().join().items();
      assertThat(taskIds).filteredOn(v -> runs.contains(v.getScopeKey())).extracting(v -> v.getValue())
          .containsExactlyInAnyOrder("\"task-a\"", "\"task-b\"");
      assertThat(taskIds).extracting(v -> v.getScopeKey()).doesNotContain(key);
    });

    // the follow-up for task-b reaches task-b only
    sendFollowUp("task-b", "answer b");
    assertThat(instance).hasActiveElement("Event_1553b23", 1).hasCompletedElement("Event_1553b23", 1);
  }
}
