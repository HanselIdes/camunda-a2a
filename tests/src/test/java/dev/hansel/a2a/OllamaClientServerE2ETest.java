package dev.hansel.a2a;

import static io.camunda.process.test.api.CamundaAssert.assertThat;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.List;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

/**
 * The client-to-server round trip of {@link ClientServerE2ETest} against a local Ollama model. Run with
 * `mvn -Pollama verify`. Model output varies, so the assertions are about state and tool use, never wording.
 */
@Tag("ollama")
class OllamaClientServerE2ETest {
  static final String MODEL = System.getProperty("ollama.model", "qwen3-coder-30b-64k");
  static final String BASE_URL = System.getProperty("ollama.baseUrl", "http://host.docker.internal:11434/v1");

  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withCamundaDockerImageVersion("8.10.2")
      .withConnectorsDockerImageVersion("8.10.0")
      .withConnectorsEnabled(true)
      .withConnectorsEnv("CAMUNDA_CLIENT_REQUEST_TIMEOUT", "PT120S")
      .withConnectorsSecret("ENGINE_URL", "http://camunda:8080")
      .withConnectorsSecret("A2A_PUBLIC_URL", "http://localhost:8080/inbound")
      .withConnectorsSecret("A2A_AGENT_CARD_URL", "http://localhost:8080/inbound/a2a-card")
      .withConnectorsSecret("A2A_PUSH_ENABLED", "false")
      .withConnectorsSecret("OLLAMA_BASE_URL", BASE_URL)
      .withConnectorsSecret("OLLAMA_MODEL", MODEL);

  static final HttpClient HTTP = HttpClient.newHttpClient();
  static final ObjectMapper JSON = new ObjectMapper();

  CamundaClient client;
  CamundaProcessTestContext context;

  @BeforeEach
  void deployAndWait() {
    CamundaAssert.setAssertionTimeout(Duration.ofSeconds(240));
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
            HttpResponse.BodyHandlers.ofString()).statusCode() == 200;
      } catch (final Exception e) {
        return false;
      }
    });
  }

  @Test
  void capitalQuestionGoesThroughBothProcessesAndTheModelUsesTheDecisionTool() throws Exception {
    final long clientKey = client.newCreateInstanceCommand().bpmnProcessId("a2a-client").latestVersion()
        .variables(Map.of("question", "What is the capital of Japan?")).send().join().getProcessInstanceKey();
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).hasActiveElements("ShowResult");
    final var items = client.newVariableSearchRequest().filter(f -> f.processInstanceKey(clientKey).name("reply"))
        .send().join().items();
    final var reply = JSON.readTree(items.get(0).getValue());
    assertThat(reply.path("state").asText()).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(reply.path("toolNames").toString()).contains("capital_of");
    context.completeUserTask("ShowResult");
    assertThat(ProcessInstanceSelectors.byKey(clientKey)).isCompleted();
  }
}
