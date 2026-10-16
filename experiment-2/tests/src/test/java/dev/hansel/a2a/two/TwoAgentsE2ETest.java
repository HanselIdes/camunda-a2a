package dev.hansel.a2a.two;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * Tier 3: both agents in one process instance, talking A2A 1.0 over real HTTP through the connectors runtime. The
 * AI Agent connectors are real; they call a stub model in this JVM that plays both agents deterministically.
 *
 * <p>The case: the client sends an ambiguous request, the server asks for clarification (input-required), the
 * client answers on the same task, the server completes the task (its event sub-process ends, the instance does
 * not), and the client agent finishes with the answer.
 */
class TwoAgentsE2ETest {
  static final String TOKEN = "e2e-push-token";

  static StubModel.Step decide(final JsonNode request) {
    final String system = StubModel.systemPrompt(request);
    final String toolResult = StubModel.lastToolResult(request);
    if (system.contains("TaskAgent")) {
      // the server agent: ask once, then answer with what the client said
      if (toolResult == null) {
        return StubModel.Step.call("Server_PushNotification",
            "{\"state\":\"TASK_STATE_INPUT_REQUIRED\",\"text\":\"Which temperature, and in which unit?\"}");
      }
      if (toolResult.contains("Pushed TASK_STATE_COMPLETED")) {
        return StubModel.Step.reply("Task done.");
      }
      if (toolResult.contains("\"unit\"")) {
        // the conversion tool answered: report its value and unit to the client
        final JsonNode converted = readOrNull(toolResult);
        return StubModel.Step.call("Server_PushNotification", "{\"state\":\"TASK_STATE_COMPLETED\",\"text\":"
            + quote("100 degrees Celsius is " + converted.path("value").asText() + " degrees "
                + converted.path("unit").asText() + ".") + "}");
      }
      // the client's answer arrived: convert with the tool
      return StubModel.Step.call("Tool_ConvertTemperature",
          "{\"value\":100,\"fromUnit\":\"celsius\",\"toUnit\":\"fahrenheit\"}");
    }
    // the client agent: delegate to the remote agent, answer its question, then report its answer
    if (toolResult == null) {
      return StubModel.Step.call("Tool_AskRemoteAgent",
          "{\"text\":" + quote(StubModel.lastUser(request)) + "}");
    }
    try {
      final JsonNode task = StubModel.JSON.readTree(toolResult);
      final String state = task.path("status").path("state").asText();
      if ("TASK_STATE_INPUT_REQUIRED".equals(state)) {
        return StubModel.Step.call("Tool_AskRemoteAgent", "{\"text\":\"100 degrees Celsius to Fahrenheit\","
            + "\"taskId\":" + quote(task.path("id").asText()) + ",\"contextId\":"
            + quote(task.path("contextId").asText()) + "}");
      }
      return StubModel.Step.reply("The remote agent says: "
          + task.path("status").path("message").path("parts").get(0).path("text").asText());
    } catch (final Exception e) {
      return StubModel.Step.reply("Unexpected tool result: " + toolResult);
    }
  }

  static JsonNode readOrNull(final String json) {
    try {
      return StubModel.JSON.readTree(json);
    } catch (final Exception e) {
      return StubModel.JSON.missingNode();
    }
  }

  static String quote(final String s) {
    try {
      return StubModel.JSON.writeValueAsString(s);
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  static final StubModel MODEL = new StubModel(TwoAgentsE2ETest::decide);
  static final HttpClient HTTP = HttpClient.newHttpClient();

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("A2A_CONNECTORS_URL", "http://localhost:8080")
      .withConnectorsSecret("A2A_PUSH_TOKEN", TOKEN)
      .withConnectorsSecret("CAMUNDA_PROVIDED_LLM_API_ENDPOINT", MODEL.baseUrlFromConnectors())
      .withConnectorsSecret("CAMUNDA_PROVIDED_LLM_API_KEY", "stub-key")
      .withConnectorsSecret("CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL", "stub");

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deploy() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(120));
    MODEL.requests.clear();
    client.newDeployResourceCommand().addResourceFromClasspath("bpmn/a2a-two-agents.bpmn")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-initial-request.form")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-user-feedback.form")
        .addResourceFromClasspath("forms/ai-agent-chat-human-send-email-request.form").send().join();
    for (final String path : new String[] {"/inbound/a2a-server", "/inbound/a2a-server-card",
        "/inbound/a2a-client-agent-reply"}) {
      Awaitility.await().atMost(Duration.ofSeconds(120)).pollInterval(Duration.ofSeconds(1)).until(() -> {
        try {
          return HTTP.send(HttpRequest.newBuilder(URI.create(context.getConnectorsAddress() + path)).GET().build(),
              HttpResponse.BodyHandlers.ofString()).statusCode() != 404;
        } catch (final Exception e) {
          return false;
        }
      });
    }
  }

  /** Prints what happened when an assertion fails: incidents, element states and the model's turns. */
  @org.junit.jupiter.api.AfterEach
  void dumpOnFailure(final org.junit.jupiter.api.TestInfo info) {
    client.newIncidentSearchRequest().send().join().items().forEach(i -> System.out.println(
        "E2E incident " + i.getElementId() + " " + i.getErrorType() + " " + i.getErrorMessage()));
    client.newElementInstanceSearchRequest().page(p -> p.limit(200)).send().join().items().forEach(e ->
        System.out.println("E2E element " + e.getElementId() + " " + e.getState()));
    MODEL.requests.forEach(r -> System.out.println("E2E model " + (StubModel.systemPrompt(r).contains("TaskAgent")
        ? "server" : "client") + " last=" + String.valueOf(StubModel.lastToolResult(r)).replace('\n', ' ')));
  }

  String variable(final long instance, final String name) {
    final var items = client.newVariableSearchRequest().filter(f -> f.processInstanceKey(instance).name(name)).send()
        .join().items();
    assertThat(items).as("variable " + name).isNotEmpty();
    return items.get(0).getValue();
  }

  @Test
  void ambiguousTaskIsClarifiedOverA2AAndCompletedWhileTheInstanceKeepsRunning() throws Exception {
    final long key = client.newCreateInstanceCommand().bpmnProcessId("a2a-two-agents").latestVersion()
        .variables(Map.of("inputText", "Please convert a temperature for me.")).send().join().getProcessInstanceKey();
    final var instance = ProcessInstanceSelectors.byKey(key);

    // the client read the card from its own instance's server agent
    assertThat(instance).hasCompletedElements("Client_FetchAgentCard", "Server_CardRequested", "Server_CardServed");

    // the client's answer comes back once the server completes; the client agent reports it to the person
    assertThat(instance).hasActiveElements("Client_UserFeedback");
    assertThat(variable(key, "agent")).containsIgnoringCase("212 degrees fahrenheit");

    // server side: one task, through input-required, answered on the same task, completed
    assertThat(instance).hasCompletedElement("Server_MessageReceived", 1).hasCompletedElement("Event_1553b23", 1)
        .hasCompletedElement("Server_PushNotification", 2).hasCompletedElement("Tool_ConvertTemperature", 1).hasCompletedElements("Gateway_0oexjso", "Server_End")
        .hasCompletedElement("Activity_0u82j95", 1);
    // client side: two A2A calls, two pushes received
    assertThat(instance).hasCompletedElement("Tool_AskRemoteAgent", 2).hasCompletedElement("Tool_RemoteAgentReplied", 2);
    // the task is complete, the process instance is not
    assertThat(instance).isActive();

    // the model saw the client's A2A tool with its parameters, and the server's push tool
    final var clientTools = MODEL.requests.stream().filter(r -> !StubModel.systemPrompt(r).contains("TaskAgent"))
        .findFirst().map(StubModel::toolNames).orElseThrow();
    assertThat(clientTools).contains("Tool_AskRemoteAgent", "Tool_ListUsers", "Tool_LoadUserByID");
    final var serverTools = MODEL.requests.stream().filter(r -> StubModel.systemPrompt(r).contains("TaskAgent"))
        .findFirst().map(StubModel::toolNames).orElseThrow();
    assertThat(serverTools).contains("Server_PushNotification", "Tool_ConvertTemperature");

    // a message on the completed task finds nothing waiting: the client has to start a new task
    final String agentId = variable(key, "a2aAgentId").replace("\"", "");
    final String completedTaskId = StubModel.JSON.readTree(variable(key, "agentResponse")).path("result").path("id")
        .asText();
    final var late = HTTP.send(HttpRequest.newBuilder(
            URI.create(context.getConnectorsAddress() + "/inbound/a2a-server?agent=" + agentId))
        .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(
            "{\"jsonrpc\":\"2.0\",\"id\":\"late\",\"method\":\"SendMessage\",\"params\":{\"message\":{"
                + "\"messageId\":\"late-1\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"one more\"}],"
                + "\"taskId\":\"" + completedTaskId + "\"}}}")).build(), HttpResponse.BodyHandlers.ofString());
    assertThat(late.statusCode()).isEqualTo(200);
    Thread.sleep(3000);
    assertThat(instance).hasCompletedElement("Server_MessageReceived", 1).hasCompletedElement("Event_1553b23", 1);

    // the person is satisfied: the conversation, and with it the server agent, ends
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", true));
    assertThat(instance).isCompleted().hasCompletedElements("Client_End");
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }
}
