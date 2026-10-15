package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-rpc.bpmn", "bpmn/a2a-task.bpmn", "bpmn/a2a-correlate.bpmn",
    "bpmn/a2a-publish-reply.bpmn", "bpmn/a2a-push-notify.bpmn", "bpmn/a2a-fetch-task.bpmn", "dmn/a2a-validate.dmn", "dmn/a2a-classify.dmn"})
class ValidationTest {
  CamundaClient client;
  CamundaProcessTestContext context;
  Harness h;

  @BeforeEach
  void setUp() {
    h = new Harness(client, context);
  }

  @SuppressWarnings("unchecked")
  static Map<String, Object> error(final Map<String, Object> response) {
    assertThat(response).containsKeys("jsonrpc", "id", "error").doesNotContainKey("result");
    return (Map<String, Object>) response.get("error");
  }

  static String reason(final Map<String, Object> error) {
    @SuppressWarnings("unchecked")
    final var data = (List<Map<String, Object>>) error.get("data");
    assertThat(data).hasSize(1);
    assertThat(data.get(0)).containsEntry("@type", "type.googleapis.com/google.rpc.ErrorInfo")
        .containsEntry("domain", "a2a-protocol.org");
    return (String) data.get(0).get("reason");
  }

  @Test
  void unsupportedVersionIsRejected() {
    final var headers = Harness.headers();
    headers.put("a2a-version", "99.0");
    final var e = error(h.rpc(headers, Harness.request("SendMessage", "{\"message\":{}}")));
    assertThat(e.get("code")).isEqualTo(-32009);
    assertThat(reason(e)).isEqualTo("VERSION_NOT_SUPPORTED");
  }

  @Test
  void patchVersionAndMissingVersionAreAccepted() {
    for (final String v : new String[] {"1.0.2", null}) {
      final var headers = Harness.headers();
      if (v == null) {
        headers.remove("a2a-version");
      } else {
        headers.put("a2a-version", v);
      }
      final var e = error(h.rpc(headers, Harness.request("Nope", "{}")));
      assertThat(e.get("code")).as("version %s reaches routing", v).isEqualTo(-32601);
    }
  }

  @Test
  void wrongContentTypeIsRejected() {
    final var headers = Harness.headers();
    headers.put("content-type", "text/plain");
    final var e = error(h.rpc(headers, Harness.request("SendMessage", "{\"message\":{}}")));
    assertThat(e.get("code")).isEqualTo(-32005);
    assertThat(reason(e)).isEqualTo("CONTENT_TYPE_NOT_SUPPORTED");
  }

  @Test
  void unknownMethodAndInvalidRequest() {
    assertThat(error(h.rpc(Harness.headers(), Harness.request("Nope", "{}"))).get("code")).isEqualTo(-32601);
    assertThat(error(h.rpc(Harness.headers(), List.of(1))).get("code")).isEqualTo(-32600);
    assertThat(error(h.rpc(Harness.headers(), Map.of("jsonrpc", "1.0", "method", "GetTask"))).get("code"))
        .isEqualTo(-32600);
  }

  @Test
  void capabilityErrors() {
    for (final String m : new String[] {"SendStreamingMessage", "SubscribeToTask", "GetExtendedAgentCard"}) {
      final var e = error(h.rpc(Harness.headers(), Harness.request(m, "{}")));
      assertThat(e.get("code")).as(m).isEqualTo(-32004);
      assertThat(reason(e)).isEqualTo("UNSUPPORTED_OPERATION");
    }
    for (final String m : new String[] {"CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig",
        "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig"}) {
      final var e = error(h.rpc(Harness.headers(), Harness.request(m, "{\"task_id\":\"t\"}")));
      assertThat(e.get("code")).as(m).isEqualTo(-32003);
      assertThat(reason(e)).isEqualTo("PUSH_NOTIFICATION_NOT_SUPPORTED");
    }
  }

  @Test
  void invalidParams() {
    assertThat(error(h.rpc(Harness.headers(), Harness.request("SendMessage", "{}"))).get("code")).isEqualTo(-32602);
    assertThat(error(h.rpc(Harness.headers(), Harness.request("GetTask", "{}"))).get("code")).isEqualTo(-32602);
    assertThat(error(h.rpc(Harness.headers(), Harness.request("CancelTask", "{\"id\":5}"))).get("code"))
        .isEqualTo(-32602);
    final var e = error(h.rpc(Harness.headers(), Harness.request("SendMessage",
        "{\"message\":{\"messageId\":\"m\",\"role\":\"ROLE_USER\",\"parts\":[{\"raw\":\"dGNr\","
            + "\"mediaType\":\"application/x-unsupported-tck-type\"}]}}")));
    assertThat(e.get("code")).isEqualTo(-32005);
  }

  @Test
  void idIsEchoedAndListTasksReturnsEmptyPage() {
    final var req = Harness.request("ListTasks", "{\"context_id\":\"c\",\"page_size\":2}");
    req.put("id", "abc");
    final var r = h.rpc(Harness.headers(), req);
    assertThat(r).containsEntry("id", "abc");
    @SuppressWarnings("unchecked")
    final var result = (Map<String, Object>) r.get("result");
    assertThat(result).containsEntry("nextPageToken", "").containsEntry("totalSize", 0).containsEntry("pageSize", 2);
    assertThat((List<?>) result.get("tasks")).isEmpty();
  }

  @Test
  void directMessageResponse() {
    final var r = h.rpc(Harness.headers(), Harness.request("SendMessage",
        "{\"message\":{\"messageId\":\"tck-message-response-1\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"hi\"}]}}"));
    @SuppressWarnings("unchecked")
    final var message = (Map<String, Object>) ((Map<String, Object>) r.get("result")).get("message");
    assertThat(message).as(String.valueOf(r)).containsEntry("role", "ROLE_AGENT").containsKeys("messageId", "contextId", "parts");
  }
}
