package dev.hansel.a2a.three;

import io.camunda.process.test.api.CamundaProcessTest;
import io.camunda.process.test.api.TestDeployment;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import org.junit.jupiter.params.ParameterizedTest;

@CamundaProcessTest
@TestDeployment(resources = {
    "core/02-a2a-server.bpmn",
    "demo/03-server-agent-card-dispute.bpmn",
    "demo/07-server-request-validation.dmn"
})
class BlueprintScenariosTest {
  TestCaseRunner testCaseRunner;

  @ParameterizedTest
  @TestCaseSource(directory = "/core", fileNames = "02-a2a-server.test.json")
  void serverRoutes(final TestCase testCase) {
    testCaseRunner.run(testCase);
  }

  @ParameterizedTest
  @TestCaseSource(directory = "/demo", fileNames = "03-server-agent-card-dispute.test.json")
  void reconciliationTool(final TestCase testCase) {
    testCaseRunner.run(testCase);
  }
}
