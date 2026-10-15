package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.TestDeployment;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

/** Table-driven tests of the three decision tables. */
@CamundaProcessTest
@TestDeployment(resources = {"dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn", "dmn/capitals.dmn"})
class DmnTest {
  CamundaClient client;

  Map<String, Object> evaluate(final String id, final Map<String, Object> variables) {
    final var response = client.newEvaluateDecisionCommand().decisionId(id).variables(variables).send().join();
    return Harness.map(response.getDecisionOutput());
  }

  // ---- a2a-classify ---------------------------------------------------------------------------
  static Stream<Arguments> classifyCases() {
    return Stream.of(
        Arguments.of("tck-input-required-1", "TASK_STATE_INPUT_REQUIRED", null, null, false, "tck"),
        Arguments.of("tck-artifact-file-url-1", "TASK_STATE_COMPLETED", null, "file-url", false, "tck"),
        Arguments.of("tck-artifact-file-1", "TASK_STATE_COMPLETED", null, "file", false, "tck"),
        Arguments.of("tck-artifact-text-1", "TASK_STATE_COMPLETED", null, "text", false, "tck"),
        Arguments.of("tck-artifact-data-1", "TASK_STATE_COMPLETED", null, "data", false, "tck"),
        Arguments.of("tck-complete-task-1", "TASK_STATE_COMPLETED", "Hello from TCK", null, false, "tck"),
        Arguments.of("tck-infer-ctx-1", "TASK_STATE_COMPLETED", null, null, true, "tck"),
        Arguments.of("tck-anything", "TASK_STATE_COMPLETED", null, null, true, "tck"),
        Arguments.of("5c1b6f0e-uuid", null, null, null, false, "agent"),
        Arguments.of("smoke-1", null, null, null, false, "agent"));
  }

  @ParameterizedTest(name = "{0}")
  @MethodSource("classifyCases")
  void classifiesMessageIds(final String messageId, final String state, final String text, final String artifact,
      final boolean echo, final String route) {
    final var out = evaluate("a2a-classify", Map.of("req", Map.of("message", Map.of("messageId", messageId))));
    assertThat(out.get("state")).isEqualTo(state);
    assertThat(out.get("statusText")).isEqualTo(text);
    assertThat(out.get("artifact")).isEqualTo(artifact);
    assertThat(out.get("echo")).isEqualTo(echo);
    assertThat(out.get("route")).isEqualTo(route);
  }

  // ---- a2a-validate ---------------------------------------------------------------------------
  static Map<String, Object> ctx(final String method, final Object... overrides) {
    final Map<String, Object> c = new LinkedHashMap<>();
    c.put("versionOk", true);
    c.put("contentTypeOk", true);
    c.put("jsonrpcOk", true);
    c.put("method", method);
    c.put("msgOk", true);
    c.put("mediaOk", true);
    c.put("idOk", true);
    c.put("pushEnabled", false);
    for (int i = 0; i < overrides.length; i += 2) {
      c.put((String) overrides[i], overrides[i + 1]);
    }
    return c;
  }

  static Stream<Arguments> validateCases() {
    return Stream.of(
        Arguments.of(ctx("SendMessage", "versionOk", false), "error", -32009, "VERSION_NOT_SUPPORTED"),
        Arguments.of(ctx("SendMessage", "contentTypeOk", false), "error", -32005, "CONTENT_TYPE_NOT_SUPPORTED"),
        Arguments.of(ctx(null, "jsonrpcOk", false), "error", -32600, null),
        Arguments.of(ctx("SendStreamingMessage"), "error", -32004, "UNSUPPORTED_OPERATION"),
        Arguments.of(ctx("SubscribeToTask"), "error", -32004, "UNSUPPORTED_OPERATION"),
        Arguments.of(ctx("GetExtendedAgentCard"), "error", -32004, "UNSUPPORTED_OPERATION"),
        Arguments.of(ctx("CreateTaskPushNotificationConfig"), "error", -32003, "PUSH_NOTIFICATION_NOT_SUPPORTED"),
        Arguments.of(ctx("GetTaskPushNotificationConfig"), "error", -32003, "PUSH_NOTIFICATION_NOT_SUPPORTED"),
        Arguments.of(ctx("ListTaskPushNotificationConfigs"), "error", -32003, "PUSH_NOTIFICATION_NOT_SUPPORTED"),
        Arguments.of(ctx("DeleteTaskPushNotificationConfig"), "error", -32003, "PUSH_NOTIFICATION_NOT_SUPPORTED"),
        Arguments.of(ctx("Nope"), "error", -32601, null),
        Arguments.of(ctx("SendMessage", "msgOk", false), "error", -32602, null),
        Arguments.of(ctx("SendMessage", "mediaOk", false), "error", -32005, "CONTENT_TYPE_NOT_SUPPORTED"),
        Arguments.of(ctx("GetTask", "idOk", false), "error", -32602, null),
        Arguments.of(ctx("CancelTask", "idOk", false), "error", -32602, null),
        Arguments.of(ctx("CreateTaskPushNotificationConfig", "pushEnabled", true), "CreateTaskPushNotificationConfig", null, null),
        Arguments.of(ctx("GetTaskPushNotificationConfig", "pushEnabled", true), "GetTaskPushNotificationConfig", null, null),
        Arguments.of(ctx("ListTaskPushNotificationConfigs", "pushEnabled", true), "ListTaskPushNotificationConfigs", null, null),
        Arguments.of(ctx("DeleteTaskPushNotificationConfig", "pushEnabled", true), "DeleteTaskPushNotificationConfig", null, null),
        Arguments.of(ctx("DeleteTaskPushNotificationConfig", "pushEnabled", true, "idOk", false), "error", -32602, null),
        Arguments.of(ctx("SendMessage"), "SendMessage", null, null),
        Arguments.of(ctx("GetTask"), "GetTask", null, null),
        Arguments.of(ctx("CancelTask"), "CancelTask", null, null),
        Arguments.of(ctx("ListTasks", "idOk", false), "ListTasks", null, null));
  }

  @ParameterizedTest
  @MethodSource("validateCases")
  void validatesRequests(final Map<String, Object> ctx, final String route, final Integer code, final String reason) {
    final var out = evaluate("a2a-validate", Map.of("ctx", ctx));
    assertThat(out.get("route")).isEqualTo(route);
    if (code == null) {
      assertThat(out.get("code")).isNull();
    } else {
      assertThat(((Number) out.get("code")).intValue()).isEqualTo(code);
      assertThat(out.get("message")).isInstanceOf(String.class);
    }
    assertThat(out.get("reason")).isEqualTo(reason);
  }

  @ParameterizedTest
  @MethodSource("firstRuleWins")
  void earlierRulesWinWhenSeveralThingsAreWrong(final Map<String, Object> ctx, final int code) {
    final var out = evaluate("a2a-validate", Map.of("ctx", ctx));
    assertThat(((Number) out.get("code")).intValue()).isEqualTo(code);
  }

  static Stream<Arguments> firstRuleWins() {
    return Stream.of(
        Arguments.of(ctx("Nope", "versionOk", false, "contentTypeOk", false), -32009),
        Arguments.of(ctx("Nope", "contentTypeOk", false), -32005),
        Arguments.of(ctx("SendMessage", "msgOk", false, "mediaOk", false), -32602));
  }

  // ---- capitals -------------------------------------------------------------------------------
  @ParameterizedTest
  @org.junit.jupiter.params.provider.CsvSource({"France,Paris", "JAPAN,Tokyo", "germany,Berlin", "Atlantis,unknown"})
  void looksUpCapitals(final String country, final String capital) {
    final var response = client.newEvaluateDecisionCommand().decisionId("capitals")
        .variables(Map.of("country", country)).send().join();
    assertThat(response.getDecisionOutput()).isEqualTo("\"" + capital + "\"");
  }
}
