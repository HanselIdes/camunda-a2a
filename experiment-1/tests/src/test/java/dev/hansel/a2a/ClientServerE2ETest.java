package dev.hansel.a2a;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.assertions.ProcessInstanceSelectors;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * Both processes on one cluster, talking A2A over HTTP: the originating process a2a-client calls the agent that
 * a2a-rpc and a2a-task implement, through the real connectors runtime (inbound webhook on one side, HTTP JSON on
 * the other). The AI Agent connector is real too; it talks to a stub OpenAI-compatible server in this JVM, so the
 * test needs no model. Person steps (answering the agent, reviewing the result) are Tasklist user tasks.
 */
class ClientServerE2ETest {
  static final ObjectMapper JSON = new ObjectMapper();
  static final List<JsonNode> LLM_REQUESTS = new CopyOnWriteArrayList<>();
  static final HttpServer LLM;

  static {
    try {
      LLM = HttpServer.create(new InetSocketAddress("0.0.0.0", 0), 0);
      LLM.createContext("/v1/chat/completions", exchange -> {
        final var request = JSON.readTree(exchange.getRequestBody().readAllBytes());
        LLM_REQUESTS.add(request);
        final boolean stream = request.path("stream").asBoolean(false);
        final byte[] body = (stream ? stubStream(request) : stubCompletion(request)).getBytes();
        exchange.getResponseHeaders().add("Content-Type", stream ? "text/event-stream" : "application/json");
        exchange.sendResponseHeaders(200, body.length);
        exchange.getResponseBody().write(body);
        exchange.close();
      });
      LLM.start();
    } catch (final Exception e) {
      throw new ExceptionInInitializerError(e);
    }
  }

  /** What the stub model does next: a tool call (name, arguments) or a plain reply. */
  record Step(String toolName, String arguments, String content) {}

  /** Deterministic behaviour: tool call first, then an answer built from the tool result, or a question. */
  static Step decide(final JsonNode request) {
    final JsonNode messages = request.get("messages");
    final JsonNode last = messages.get(messages.size() - 1);
    if ("tool".equals(last.path("role").asText())) {
      return new Step(null, null, "The tool says: " + text(last.get("content")));
    }
    String user = "";
    for (final JsonNode n : messages) {
      if ("user".equals(n.path("role").asText())) {
        user = text(n.get("content"));
      }
    }
    if (user.toLowerCase().contains("capital")) {
      return new Step("capital_of", "{\"country\":\"Japan\"}", null);
    }
    if (user.matches("(?s).*\\d.*")) {
      return new Step("convert_temperature", "{\"degrees\":100,\"unit\":\"celsius\"}", null);
    }
    return new Step(null, null, "NEED_INPUT: Which temperature should I convert, and in which unit?");
  }

  static String stubCompletion(final JsonNode request) {
    try {
      final var step = decide(request);
      final var message = JSON.createObjectNode().put("role", "assistant");
      if (step.toolName() != null) {
        message.putNull("content");
        message.set("tool_calls", toolCall(step.toolName(), step.arguments()));
      } else {
        message.put("content", step.content());
      }
      final var out = JSON.createObjectNode().put("id", "stub-" + System.nanoTime()).put("object", "chat.completion")
          .put("created", 1L).put("model", "stub");
      out.putArray("choices").addObject().put("index", 0)
          .put("finish_reason", step.toolName() != null ? "tool_calls" : "stop").set("message", message);
      out.putObject("usage").put("prompt_tokens", 1).put("completion_tokens", 1).put("total_tokens", 2);
      return JSON.writeValueAsString(out);
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  /** The AI Agent connector asks for a stream, so the stub answers with server-sent chunks. */
  static String stubStream(final JsonNode request) {
    try {
      final var step = decide(request);
      final String id = "stub-" + System.nanoTime();
      final var delta = JSON.createObjectNode().put("role", "assistant");
      if (step.toolName() != null) {
        final var calls = toolCall(step.toolName(), step.arguments());
        ((com.fasterxml.jackson.databind.node.ObjectNode) calls.get(0)).put("index", 0);
        delta.set("tool_calls", calls);
      } else {
        delta.put("content", step.content());
      }
      final var sb = new StringBuilder();
      sb.append(chunk(id, delta, null)).append(chunk(id, JSON.createObjectNode(),
          step.toolName() != null ? "tool_calls" : "stop"));
      final var usage = JSON.createObjectNode().put("id", id).put("object", "chat.completion.chunk").put("created", 1L).put("model", "stub");
      usage.putArray("choices");
      usage.putObject("usage").put("prompt_tokens", 1).put("completion_tokens", 1).put("total_tokens", 2);
      sb.append("data: ").append(JSON.writeValueAsString(usage)).append("\n\n").append("data: [DONE]\n\n");
      return sb.toString();
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  static String chunk(final String id, final JsonNode delta, final String finish) throws Exception {
    final var out = JSON.createObjectNode().put("id", id).put("object", "chat.completion.chunk").put("created", 1L).put("model", "stub");
    final var choice = out.putArray("choices").addObject().put("index", 0);
    choice.set("delta", delta);
    if (finish == null) {
      choice.putNull("finish_reason");
    } else {
      choice.put("finish_reason", finish);
    }
    return "data: " + JSON.writeValueAsString(out) + "\n\n";
  }

  static com.fasterxml.jackson.databind.node.ArrayNode toolCall(final String name, final String arguments) {
    final var calls = JSON.createArrayNode();
    final var call = calls.addObject().put("id", "call_" + System.nanoTime()).put("type", "function");
    call.putObject("function").put("name", name).put("arguments", arguments);
    return calls;
  }

  static String text(final JsonNode content) {
    if (content == null || content.isNull()) {
      return "";
    }
    if (content.isTextual()) {
      return content.asText();
    }
    final var sb = new StringBuilder();
    content.forEach(part -> sb.append(part.path("text").asText()));
    return sb.toString();
  }

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      // the client runs inside the connectors container, so it reaches the agent on the container's own port
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://localhost:8080/inbound")
      .withConnectorsSecret("A2A_AGENT_CARD_URL", "http://localhost:8080/inbound/a2a-card")
      .withConnectorsSecret("A2A_PUSH_ENABLED", "false")
      .withConnectorsSecret("OLLAMA_BASE_URL", "http://host.docker.internal:" + LLM.getAddress().getPort() + "/v1")
      .withConnectorsSecret("OLLAMA_MODEL", "stub");

  static final HttpClient HTTP = HttpClient.newHttpClient();

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deployAndWait() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(120));
    LLM_REQUESTS.clear();
    final var cmd = client.newDeployResourceCommand();
    for (final String r : List.of("bpmn/a2a-card.bpmn", "bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn",
        "bpmn/a2a-correlate.bpmn", "bpmn/a2a-publish-reply.bpmn", "bpmn/a2a-push-notify.bpmn",
        "bpmn/a2a-fetch-task.bpmn", "bpmn/a2a-client.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn",
        "dmn/capitals.dmn", "forms/a2a-client-ask.form", "forms/a2a-client-answer.form",
        "forms/a2a-client-result.form")) {
      cmd.addResourceFromClasspath(r);
    }
    ((io.camunda.client.api.command.DeployResourceCommandStep1.DeployResourceCommandStep2) cmd).send().join();
    final String base = context.getConnectorsAddress().toString();
    Awaitility.await().atMost(Duration.ofSeconds(240)).pollInterval(Duration.ofSeconds(1)).until(() -> {
      try {
        return HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a-card")).GET().build(),
            HttpResponse.BodyHandlers.ofString()).statusCode() == 200
            && HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a")).GET().build(),
                HttpResponse.BodyHandlers.ofString()).statusCode() == 405;
      } catch (final Exception e) {
        return false;
      }
    });
  }

  long startClient(final String question) {
    return client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("question", question)).send().join().getProcessInstanceKey();
  }

  JsonNode variable(final long instance, final String name) {
    final var items = client.newVariableSearchRequest().filter(f -> f.processInstanceKey(instance).name(name)).send()
        .join().items();
    assertThat(items).as("variable " + name).hasSize(1);
    try {
      return JSON.readTree(items.get(0).getValue());
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  /** The long-lived server instance that holds the A2A task, found through the tag the handler gave it. */
  long serverTaskInstance(final String taskId) {
    final var found = new ArrayList<Long>();
    Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
      found.clear();
      client.newProcessInstanceSearchRequest()
          .filter(f -> f.processDefinitionId("a2a-task").tags(Set.of("a2a", "task-" + taskId))).send().join().items()
          .forEach(i -> found.add(i.getProcessInstanceKey()));
      assertThat(found).hasSize(1);
    });
    return found.get(0);
  }

  @Test
  void capitalQuestionTravelsFromTheClientProcessToTheAgentAndBack() {
    final long clientKey = startClient("What is the capital of Japan?");

    // the client process reads the card, sends the question and shows the agent's answer to a person
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).hasActiveElements("ShowResult");
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).hasCompletedElementsInOrder("QuestionAsked", "DiscoverAgent",
        "BuildMessage", "SendMessage", "ReadReply", "BuildResult");

    final var reply = variable(clientKey, "reply");
    assertThat(reply.path("state").asText()).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(reply.path("toolNames").toString()).isEqualTo("[\"capital_of\"]");
    assertThat(variable(clientKey, "agentName").asText()).isEqualTo("camunda-a2a");
    final String resultText = variable(clientKey, "resultText").asText();
    assertThat(resultText).contains("Tokyo").contains("capital_of").contains(reply.path("taskId").asText());

    // the same token continued on the server: handler instance, then the task instance running the agent
    final long serverKey = serverTaskInstance(reply.path("taskId").asText());
    assertThat(ProcessInstanceSelectors.byKey(serverKey)).isActive().hasCompletedElementsInOrder("MarkWorking",
        "capital_of", "ApplyAgentResponse");
    assertThat(client.newProcessInstanceSearchRequest().filter(f -> f.processDefinitionId("a2a-rpc")).send().join()
        .items()).isNotEmpty().allSatisfy(i -> assertThat(i.getState().name()).isEqualTo("COMPLETED"));

    // the real AI Agent connector called the model with the agent's three tools and then with the tool result
    assertThat(LLM_REQUESTS).hasSize(2);
    final var toolNames = new ArrayList<String>();
    LLM_REQUESTS.get(0).get("tools").forEach(t -> toolNames.add(t.path("function").path("name").asText()));
    assertThat(toolNames).containsExactlyInAnyOrder("get_current_time", "convert_temperature", "capital_of");

    context.completeUserTask("ShowResult");
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).isCompleted().hasCompletedElements("ConversationFinished");
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }

  @Test
  void inputRequiredQuestionIsRelayedToAPersonAndTheAnswerContinuesTheSameServerTask() {
    final long clientKey = startClient("Please convert a temperature for me.");

    // the agent asks for more; the client turns that into a Tasklist task
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).hasActiveElements("AnswerAgent");
    final var asked = variable(clientKey, "reply");
    assertThat(asked.path("state").asText()).isEqualTo("TASK_STATE_INPUT_REQUIRED");
    assertThat(asked.path("text").asText()).contains("Which temperature");
    final String taskId = asked.path("taskId").asText();
    final long serverKey = serverTaskInstance(taskId);
    assertThat(ProcessInstanceSelectors.byKey(serverKey)).hasActiveElements("FollowUpArrives");

    // the person answers; the client sends it as a follow-up on the same A2A task
    context.completeUserTask("AnswerAgent", Map.of("followUp", "100 celsius to fahrenheit"));
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).hasActiveElements("ShowResult");
    final var done = variable(clientKey, "reply");
    assertThat(done.path("state").asText()).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(done.path("taskId").asText()).isEqualTo(taskId);
    assertThat(done.path("toolNames").toString()).isEqualTo("[\"convert_temperature\"]");
    assertThat(variable(clientKey, "resultText").asText()).contains("212");
    assertThat(ProcessInstanceSelectors.byKey(serverKey)).isActive().hasCompletedElements("convert_temperature");

    context.completeUserTask("ShowResult");
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).isCompleted();
    assertThat(client.newIncidentSearchRequest().send().join().items()).isEmpty();
  }
}
