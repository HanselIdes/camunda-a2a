package dev.hansel.a2a;

import static io.camunda.process.test.api.CamundaAssert.assertThat;

import io.camunda.client.CamundaClient;
import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.CamundaProcessTestContext;
import io.camunda.process.test.api.TestDeployment;
import org.junit.jupiter.api.Test;

@CamundaProcessTest
@TestDeployment(resources = "bpmn/a2a-card.bpmn")
class SmokeTest {
  CamundaClient client;
  CamundaProcessTestContext context;

  @Test
  void cardProcessCompletes() {
    var pi = client.newCreateInstanceCommand().bpmnProcessId("a2a-card").latestVersion().send().join();
    assertThat(pi).isCompleted();
  }
}
