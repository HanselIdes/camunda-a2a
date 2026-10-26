package dev.hansel.a2a.three;

import static dev.hansel.a2a.three.Harness.history;
import static dev.hansel.a2a.three.Harness.state;
import static dev.hansel.a2a.three.Harness.statusText;
import static dev.hansel.a2a.three.Harness.task;
import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.zeebe.model.bpmn.Bpmn;
import io.camunda.zeebe.model.bpmn.instance.zeebe.ZeebeScript;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"core/a2a-protocol.bpmn", "bpmn/a2a-echo.bpmn", "dmn/a2a-validate.dmn",
    "tck/fixture/a2a-tck-fixture.bpmn", "tck/fixture/a2a-classify.dmn", "bpmn/a2a-literal-prompt.bpmn"})
class CoreProtocolTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
    h.agentProcess = "a2a-echo";
  }

  @Test
  void completesAndReadsExactResultsWithoutPost88EngineApis() {
    final var completed = task(h.send("core-echo", "Core result"));
    assertThat(state(completed)).isEqualTo("TASK_STATE_COMPLETED");
    assertThat(statusText(completed)).isEqualTo("Core result");
    assertThat(h.get((String) completed.get("id")).get("result")).isEqualTo(completed);
    assertThat(h.calls).noneMatch(c -> c.contains("/cluster-variables") || c.contains("/expression/evaluation"));
  }

  @Test
  void messageIdsCannotSelectConformanceSpecificBusinessBehavior() {
    final var completed = task(h.send("tck-message-response-1", "Real echo"));
    assertThat(statusText(completed)).isEqualTo("Real echo");
    assertThat(history(completed)).hasSize(2);
  }

  @Test
  void anotherAgentsTaskCannotBeReadOrChanged() {
    h.agentProcess = Harness.FIXTURE;
    final var other = task(h.send("tck-complete-task-other", "Other agent"));
    h.agentProcess = "a2a-echo";
    final String id = (String) other.get("id");
    assertThat(h.get(id).toString()).contains("TASK_NOT_FOUND");
    assertThat(h.cancel(id).toString()).contains("TASK_NOT_FOUND");
    assertThat(h.followUp(id, "foreign", "Change task").toString()).contains("TASK_NOT_FOUND");
  }

  @Test
  void disabledPushIsRejectedBeforeCreatingBusinessWork() {
    final var response = h.sendWith("push-disabled",
        "{\"taskPushNotificationConfig\":{\"url\":\"https://example.invalid/callback\"}}");
    assertThat(response.toString()).contains("PUSH_NOTIFICATION_NOT_SUPPORTED");
    assertThat(h.calls).noneMatch(c -> c.equals("POST /v2/process-instances"));
  }

  @Test
  void taskLookupWaitsForDelayedProcessIndexVisibility() {
    final var completed = task(h.send("index-lag", "Indexed result"));
    final var misses = new AtomicInteger(2);
    h.afterEngineResponse = (call, body) ->
        call.equals("POST /v2/process-instances/search") && misses.getAndDecrement() > 0
            ? Map.of("items", List.of()) : body;
    assertThat(h.get((String) completed.get("id")).get("result")).isEqualTo(completed);
    assertThat(misses.get()).isNegative();
  }

  @Test
  void unknownTaskLookupHasABoundedExpiry() {
    final long start = System.nanoTime();
    assertThat(h.get("missing-task").toString()).contains("TASK_NOT_FOUND");
    assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(8));
    assertThat(h.calls.stream().filter(c -> c.equals("POST /v2/process-instances/search")).count())
        .isBetween(2L, 20L);
  }

  @Test
  void literalPromptEncodingPreservesNumericJsonExpressionAndControlCharacterText() throws Exception {
    final var controls = new StringBuilder();
    for (char c = 0; c < 32; c++) {
      controls.append(c);
    }
    for (final String text : List.of("100 degrees Celsius to Fahrenheit.", "{\"value\":100}", "[1,2]",
        "true", "=1 + 1", "\"quoted\" and \\backslash\n\t", controls.toString(), "Unicode: \u00e9 \u6771\u4eac")) {
      final var result = client.newCreateInstanceCommand().bpmnProcessId("a2a-literal-prompt").latestVersion()
          .variables(Map.of("text", text)).withResult().fetchVariables("encoded").send().join();
      final String encoded = (String) result.getVariablesAsMap().get("encoded");
      assertThat(Harness.JSON.readValue(encoded, String.class)).isEqualTo(text);
    }
  }

  @Test
  void bothProfilesAndTemplatePersistOnlyAllowlistedNonsecretHeaders() throws Exception {
    final var factory = DocumentBuilderFactory.newInstance();
    factory.setNamespaceAware(true);
    final var expressions = new java.util.ArrayList<String>();
    for (final String resource : List.of("core/a2a-protocol.bpmn", "core-oauth/a2a-protocol.bpmn")) {
      try (var input = getClass().getClassLoader().getResourceAsStream(resource)) {
        final var properties = factory.newDocumentBuilder().parse(input)
            .getElementsByTagNameNS("http://camunda.org/schema/zeebe/1.0", "property");
        for (int i = 0; i < properties.getLength(); i++) {
          final var property = (org.w3c.dom.Element) properties.item(i);
          if (property.getAttribute("name").equals("resultExpression")) {
            expressions.add(property.getAttribute("value"));
          }
        }
      }
    }
    try (var input = getClass().getClassLoader().getResourceAsStream("core-templates/a2a-core-rpc.json")) {
      for (final var property : Harness.JSON.readTree(input).get("properties")) {
        if (property.path("id").asText().equals("resultExpression")) {
          expressions.add(property.get("value").asText());
        }
      }
    }
    assertThat(expressions).hasSize(3).allMatch(expressions.getFirst()::equals);
    try (var input = getClass().getClassLoader().getResourceAsStream("bpmn/a2a-literal-prompt.bpmn")) {
      final var model = Bpmn.readModelFromStream(input);
      final var script = model.getModelElementsByType(ZeebeScript.class).iterator().next();
      script.setExpression(expressions.getFirst());
      script.setResultVariable("mapped");
      client.newDeployResourceCommand().addProcessModel(model, "header-mapping-regression.bpmn").send().join();
    }
    final var headers = Map.of("content-type", "application/a2a+json", "a2a-version", "1.0",
        "x-a2a-api-key", "MUST-NOT-PERSIST", "authorization", "Bearer MUST-NOT-PERSIST",
        "cookie", "session=MUST-NOT-PERSIST", "unexpected", "MUST-NOT-PERSIST");
    final var body = Map.of("jsonrpc", "2.0", "id", "header-check", "method", "GetTask");
    final var result = client.newCreateInstanceCommand().bpmnProcessId("a2a-literal-prompt").latestVersion()
        .variables(Map.of("request", Map.of("headers", headers, "body", body)))
        .withResult().fetchVariables("mapped").send().join().getVariablesAsMap().get("mapped");
    assertThat(result).isEqualTo(Map.of("rpc", body, "hdr",
        Map.of("content-type", "application/a2a+json", "a2a-version", "1.0")));
    assertThat(result.toString()).doesNotContain("MUST-NOT-PERSIST");
  }
}
