package dev.hansel.a2a.three;

import static org.assertj.core.api.Assertions.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.TestDeployment;
import java.io.File;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = {"bpmn/a2a-agent.bpmn"})
class CardTest {
  CamundaClient client;

  /** The webhook answers the card from its response expression; the process behind it only has to end. */
  @Test
  void cardProcessEndsRightAway() {
    final var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-card").latestVersion().send().join();
    CamundaAssert.assertThat(pi).isCompleted();
  }

  /** The card is generated from the tools in a2a-agent.bpmn; this fails when the committed card has drifted. */
  @Test
  void committedCardMatchesTheCardGeneratedFromTheAgentTools() throws Exception {
    final var process = new ProcessBuilder("python3", "tools/gen_card.py", "--check")
        .directory(new File("..").getCanonicalFile()).redirectErrorStream(true).start();
    final String output = new String(process.getInputStream().readAllBytes());
    assertThat(process.waitFor()).as(output).isZero();
    assertThat(output).contains("matches the 2 agent tools");
  }
}
