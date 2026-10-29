package dev.hansel.a2a.three;

import io.camunda.client.CamundaClient;
import io.camunda.client.CredentialsProvider;
import io.camunda.process.test.api.CamundaAssert;
import io.camunda.process.test.api.CamundaProcessTestExtension;
import io.camunda.process.test.api.CamundaProcessTestRuntimeMode;
import io.camunda.process.test.api.DataDeletionMode;
import io.camunda.process.test.api.testCases.TestCase;
import io.camunda.process.test.api.testCases.TestCaseRunner;
import io.camunda.process.test.api.testCases.TestCaseSource;
import java.net.URI;
import java.time.Duration;
import java.util.Objects;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.junit.jupiter.params.ParameterizedTest;

/** Invoked by verify_client_agent.py against its disposable authenticated cluster. */
class BlueprintLiveScenarioIT {
  @RegisterExtension
  static final CamundaProcessTestExtension EXTENSION = new CamundaProcessTestExtension()
      .withRuntimeMode(CamundaProcessTestRuntimeMode.REMOTE)
      .withClockResetEnabled(false)
      .withDataDeletionMode(DataDeletionMode.NONE)
      .withRemoteCamundaMonitoringApiAddress(URI.create(required("PROOF_MONITORING_URL")))
      .withRemoteConnectorsRestApiAddress(URI.create(required("PROOF_CONNECTORS_URL")))
      .withRemoteCamundaClientBuilderFactory(() -> CamundaClient.newClientBuilder()
          .applyEnvironmentVariableOverrides(false)
          .restAddress(URI.create(required("PROOF_ENGINE_URL")))
          .preferRestOverGrpc(true)
          .credentialsProvider(CredentialsProvider.newBasicAuthCredentialsProviderBuilder()
              .applyEnvironmentOverrides(false)
              .username("proof").password(required("PROOF_ENGINE_PASSWORD")).build()));

  TestCaseRunner testCaseRunner;

  @BeforeEach
  void allowRealModelCalls() {
    CamundaAssert.setAssertionTimeout(Duration.ofMinutes(8));
  }

  @ParameterizedTest
  @TestCaseSource(directory = "/demo", fileNames = "01-client-agent.integration.test.json")
  void liveClientJourney(final TestCase testCase) {
    testCaseRunner.run(testCase);
  }

  private static String required(final String name) {
    return Objects.requireNonNull(System.getenv(name), name + " is required");
  }
}
