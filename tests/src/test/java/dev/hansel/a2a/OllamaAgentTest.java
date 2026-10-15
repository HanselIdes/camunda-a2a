package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * The agent against a local Ollama model through the real connectors runtime. Run with `mvn -Pollama verify`.
 * Model output varies, so the assertions are about task state and tool use, never about wording.
 */
@Tag("ollama")
class OllamaAgentTest {
  static final String MODEL = System.getProperty("ollama.model", "qwen3-coder-30b-64k");
  static final String BASE_URL = System.getProperty("ollama.baseUrl", "http://host.docker.internal:11434/v1");

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT60S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://a2a.test")
      .withConnectorsSecret("OLLAMA_BASE_URL", BASE_URL)
      .withConnectorsSecret("OLLAMA_MODEL", MODEL);

  static final HttpClient HTTP = HttpClient.newHttpClient();

  CamundaClient client;
  CamundaProcessTestContext context;
  String base;

  @BeforeEach
  void deployAndWait() {
    final var cmd = client.newDeployResourceCommand();
    for (final String r : List.of("bpmn/a2a-card.bpmn", "bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn",
        "bpmn/a2a-correlate.bpmn", "bpmn/a2a-publish-reply.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn",
        "dmn/capitals.dmn")) {
      cmd.addResourceFromClasspath(r);
    }
    ((io.camunda.client.api.command.DeployResourceCommandStep1.DeployResourceCommandStep2) cmd).send().join();
    base = context.getConnectorsAddress().toString();
    Awaitility.await().atMost(Duration.ofSeconds(90)).pollInterval(Duration.ofSeconds(1)).until(() -> {
      try {
        return HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a-card")).GET().build(),
            HttpResponse.BodyHandlers.ofString()).statusCode() == 200;
      } catch (final Exception e) {
        return false;
      }
    });
  }

  Map<String, Object> rpc(final String method, final String paramsJson) throws Exception {
    final var response = HTTP.send(HttpRequest.newBuilder(URI.create(base + "/inbound/a2a"))
        .timeout(Duration.ofSeconds(120)).header("Content-Type", "application/json").header("A2A-Version", "1.0")
        .POST(HttpRequest.BodyPublishers.ofString("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"" + method
            + "\",\"params\":" + paramsJson + "}")).build(), HttpResponse.BodyHandlers.ofString());
    return Harness.map(response.body());
  }

  String message(final String text, final String extra) {
    return "{\"message\":{\"messageId\":\"" + UUID.randomUUID() + "\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\""
        + text + "\"}]" + extra + "}}";
  }

  /** Sends a message and polls GetTask until the task is no longer working, like a real client would. */
  Map<String, Object> ask(final String text, final String extra) throws Exception {
    Map<String, Object> task = Harness.task(rpc("SendMessage", message(text, extra)));
    final String id = (String) task.get("id");
    final long deadline = System.currentTimeMillis() + Duration.ofSeconds(180).toMillis();
    while (List.of("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING").contains(Harness.state(task))
        && System.currentTimeMillis() < deadline) {
      Thread.sleep(2000);
      task = Harness.bareTask(rpc("GetTask", "{\"id\":\"" + id + "\"}"));
    }
    return task;
  }

  @SuppressWarnings("unchecked")
  static List<String> toolsUsed(final Map<String, Object> task) {
    final var artifacts = (List<Map<String, Object>>) task.get("artifacts");
    if (artifacts == null) {
      return List.of();
    }
    final var out = new java.util.ArrayList<String>();
    for (final var a : artifacts) {
      if ("tool-trace".equals(a.get("name"))) {
        final var data = (Map<String, Object>) ((Map<String, Object>) ((List<?>) a.get("parts")).get(0)).get("data");
        for (final var call : (List<Map<String, Object>>) data.get("toolCalls")) {
          out.add((String) call.get("name"));
        }
      }
    }
    return out;
  }

  @Test
  void timeQuestionCompletesAndUsesTheTimeTool() throws Exception {
    final var task = ask("What time is it?", "");
    assertThat(Harness.state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(toolsUsed(task)).contains("get_current_time");
  }

  @Test
  void capitalQuestionUsesTheDecisionTool() throws Exception {
    final var task = ask("What is the capital of Japan?", "");
    assertThat(Harness.state(task)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(toolsUsed(task)).contains("capital_of");
  }

  @Test
  void ambiguousRequestAsksForInputAndTheFollowUpCompletes() throws Exception {
    Map<String, Object> waiting = null;
    for (int attempt = 1; attempt <= 3; attempt++) {
      final var task = ask("Please convert a temperature for me.", "");
      if ("TASK_STATE_INPUT_REQUIRED".equals(Harness.state(task))) {
        waiting = task;
        break;
      }
    }
    assertThat(waiting).as("the agent asked for input within 3 attempts").isNotNull();
    final var done = ask("100 celsius to fahrenheit", ",\"taskId\":\"" + waiting.get("id") + "\"");
    assertThat(Harness.state(done)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(toolsUsed(done)).contains("convert_temperature");
  }
}
