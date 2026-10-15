package dev.hansel.a2a;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.TestDeployment;
import java.io.File;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = "bpmn/a2a-card.bpmn")
class CardTest {
  CamundaClient client;

  @Test
  void cardProcessBuildsACardWithTheThreeToolsAsSkills() {
    final var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-card").latestVersion().withResult()
        .send().join();
    @SuppressWarnings("unchecked")
    final var card = (Map<String, Object>) pi.getVariablesAsMap().get("card");
    assertThat(card).containsKeys("name", "description", "version", "capabilities", "defaultInputModes",
        "defaultOutputModes", "skills");
    @SuppressWarnings("unchecked")
    final var caps = (Map<String, Object>) card.get("capabilities");
    assertThat(caps).containsEntry("streaming", false).containsEntry("pushNotifications", false)
        .containsEntry("extendedAgentCard", false);
    @SuppressWarnings("unchecked")
    final var skills = (List<Map<String, Object>>) card.get("skills");
    assertThat(skills).extracting(s -> s.get("id")).containsExactly("get_current_time", "convert_temperature", "capital_of");
    assertThat(skills).allSatisfy(s -> assertThat(s).containsKeys("id", "name", "description", "tags"));
  }

  /** The card is generated from the tools in a2a-task.bpmn; this fails when the committed card has drifted. */
  @Test
  void committedCardMatchesTheCardGeneratedFromTheAgentTools() throws Exception {
    final var process = new ProcessBuilder("python3", "tools/gen_card.py", "--check")
        .directory(new File("..").getCanonicalFile()).redirectErrorStream(true).start();
    final String output = new String(process.getInputStream().readAllBytes());
    assertThat(process.waitFor()).as(output).isZero();
    assertThat(output).contains("matches the 3 agent tools");
  }
}
