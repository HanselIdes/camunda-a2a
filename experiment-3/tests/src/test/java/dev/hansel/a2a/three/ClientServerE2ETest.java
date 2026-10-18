package dev.hansel.a2a.three;

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
 * Tier 3: the client diagram talks to the server diagram over real HTTP on one cluster, through the connectors
 * runtime. The AI Agent connectors are real; they call a stub model in this JVM that plays both agents
 * deterministically.
 *
 * <p>The case: the client sends an ambiguous request, the server asks for clarification (input-required), the
 * client answers on the same task, the server completes the task, and the client agent finishes with the answer.
 * The two agents run in two separate process definitions; the only thing they share is the A2A protocol.
 */
class ClientServerE2ETest {
  static final String TOKEN = "e2e-push-token";

  static StubModel.Step decide(final JsonNode request) {
    final String system = StubModel.systemPrompt(request);
    final String toolResult = StubModel.lastToolResult(request);
    if (system.contains("TaskAgent")) {
      // the server agent: ask once, then convert with its tool and report the result
      if (toolResult != null) {
        final JsonNode converted = readOrNull(toolResult);
        return StubModel.Step.reply("100 degrees Celsius is " + converted.path("value").asText() + " degrees "
            + converted.path("unit").asText() + ".");
      }
      if (StubModel.lastUser(request).contains("Celsius")) {
        return StubModel.Step.call("convert_temperature",
            "{\"value\":100,\"fromUnit\":\"celsius\",\"toUnit\":\"fahrenheit\"}");
      }
      return StubModel.Step.reply("NEED_INPUT: Which temperature, and in which unit?");
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

  static final StubModel MODEL = new StubModel(ClientServerE2ETest::decide);
  static final HttpClient HTTP = HttpClient.newHttpClient();

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      .withConnectorsSecret("A2A_AGENT_PROCESS", "a2a-agent")
      .withConnectorsSecret("A2A_CONNECTORS_URL", "http://localhost:8080")
      .withConnectorsSecret("A2A_SERVER_URL", "http://localhost:8080/inbound")
      .withConnectorsSecret("A2A_AGENT_CARD_PATH", "a2a-card")
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://localhost:8080/inbound")
      .withConnectorsSecret("A2A_PUSH_ENABLED", "true")
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
    client.newDeployResourceCommand().addResourceFromClasspath("bpmn/a2a-agent.bpmn")
        .addResourceFromClasspath("bpmn/a2a-protocol.bpmn").addResourceFromClasspath("dmn/a2a-validate.dmn")
        .addResourceFromClasspath("bpmn/a2a-client.bpmn")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-initial-request.form")
        .addResourceFromClasspath("forms/ai-agent-chat-mcp-resources-user-feedback.form")
        .addResourceFromClasspath("forms/ai-agent-chat-human-send-email-request.form").send().join();
    for (final String path : new String[] {"/inbound/a2a", "/inbound/a2a-card"}) {
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
  void dumpOnFailure() {
    client.newIncidentSearchRequest().send().join().items().forEach(i -> System.out.println(
        "E2E incident " + i.getElementId() + " " + i.getErrorType() + " " + i.getErrorMessage()));
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
  void ambiguousTaskIsClarifiedOverA2AAndCompletedWhileTheClientKeepsRunning() throws Exception {
    final long key = client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("inputText", "Please convert a temperature for me.")).send().join().getProcessInstanceKey();
    final var instance = ProcessInstanceSelectors.byKey(key);

    // the client read the card from the server's webhook, in its own process definition
    assertThat(instance).hasCompletedElements("Client_FetchAgentCard");
    // the client's answer comes back once the server completes; the client agent reports it to the person
    assertThat(instance).hasActiveElements("Client_UserFeedback");
    assertThat(variable(key, "agent")).containsIgnoringCase("212 degrees fahrenheit");
    // two A2A calls, two pushes received
    assertThat(instance).hasCompletedElement("Tool_AskRemoteAgent", 2).hasCompletedElement("Tool_RemoteAgentReplied", 2);

    // the server side: one task instance, through input-required, answered on the same task, completed
    final var serverRuns = client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-agent"))
        .send().join().items();
    assertThat(serverRuns).as("one run of a2a-agent for the one task").hasSize(1);

    // the model saw the client's A2A tool, and the client agent knows the remote skills from the Agent Card
    final var clientTools = MODEL.requests.stream().filter(r -> !StubModel.systemPrompt(r).contains("TaskAgent"))
        .findFirst().map(StubModel::toolNames).orElseThrow();
    assertThat(clientTools).contains("Tool_AskRemoteAgent", "Tool_ListUsers", "Tool_LoadUserByID");
    final String clientSystem = MODEL.requests.stream().map(StubModel::systemPrompt)
        .filter(p -> !p.contains("TaskAgent")).findFirst().orElseThrow();
    assertThat(clientSystem).contains("convert_temperature", "list_tech_devices");
    // the server agent has its two tools and keeps its conversation across the follow-up
    final var serverRequests = MODEL.requests.stream().filter(r -> StubModel.systemPrompt(r).contains("TaskAgent"))
        .toList();
    assertThat(StubModel.toolNames(serverRequests.get(0))).containsExactlyInAnyOrder("convert_temperature",
        "list_tech_devices");
    final String secondTurn = serverRequests.get(1).get("messages").toString();
    assertThat(secondTurn).as("the follow-up turn still holds the first question").contains("Which temperature");

    // the person is satisfied: the conversation ends
    context.completeUserTask("Client_UserFeedback", Map.of("userSatisfied", true));
    assertThat(instance).isCompleted().hasCompletedElements("Client_End");
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }
}
