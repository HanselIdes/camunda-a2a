package dev.hansel.a2a.templates;

import static io.camunda.connector.generator.dsl.http.HttpOperationProperty.Target.BODY;
import static io.camunda.connector.generator.dsl.http.HttpOperationProperty.Target.PATH;

import com.fasterxml.jackson.core.util.DefaultIndenter;
import com.fasterxml.jackson.core.util.DefaultPrettyPrinter;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import io.camunda.connector.generator.api.GeneratorConfiguration.ConnectorElementType;
import io.camunda.connector.generator.dsl.CommonProperties;
import io.camunda.connector.generator.dsl.ElementTemplate;
import io.camunda.connector.generator.dsl.ElementTemplateBuilder;
import io.camunda.connector.generator.dsl.ElementTemplateIcon;
import io.camunda.connector.generator.dsl.Engines;
import io.camunda.connector.generator.dsl.HiddenProperty;
import io.camunda.connector.generator.dsl.Property;
import io.camunda.connector.generator.dsl.PropertyBinding.MessageProperty;
import io.camunda.connector.generator.dsl.PropertyBinding.ZeebeProperty;
import io.camunda.connector.generator.dsl.PropertyBinding.ZeebeSubscriptionProperty;
import io.camunda.connector.generator.dsl.PropertyBinding.ZeebeTaskHeader;
import io.camunda.connector.generator.dsl.PropertyCondition.Equals;
import io.camunda.connector.generator.dsl.PropertyConstraints;
import io.camunda.connector.generator.dsl.PropertyGroup;
import io.camunda.connector.generator.dsl.StringProperty;
import io.camunda.connector.generator.dsl.TextProperty;
import io.camunda.connector.generator.dsl.http.HttpFeelBuilder;
import io.camunda.connector.generator.dsl.http.HttpOperation;
import io.camunda.connector.generator.dsl.http.HttpOperationProperty;
import io.camunda.connector.generator.dsl.http.HttpOutboundElementTemplateBuilder;
import io.camunda.connector.generator.dsl.http.HttpServerData;
import io.camunda.connector.generator.java.annotation.BpmnType;
import io.camunda.connector.generator.java.annotation.FeelMode;
import io.camunda.connector.generator.java.json.ElementTemplateModule;
import io.camunda.connector.http.base.model.HttpMethod;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * The A2A 1.0 element templates of experiment 3, written with the Camunda connector template generator DSL.
 *
 * <p>Outbound templates come from the HTTP DSL, so they run on the HTTP JSON connector. Inbound templates bind to
 * the HTTP webhook connector or to a plain message event. The A2A 1.0 wire format lives in the FEEL the
 * templates hide. Field layout and labels follow the out-of-the-box A2A Client templates, which speak A2A 0.3.
 */
public final class A2aTemplates {

  static final String DOCS = "https://a2a-protocol.org/latest/specification/";
  static final Engines ENGINES = new Engines("^8.9");
  static final ElementTemplateIcon ICON =
      ElementTemplateIcon.from("a2a-icon.svg", A2aTemplates.class.getClassLoader());
  static final ConnectorElementType SERVICE_TASK =
      new ConnectorElementType(java.util.Set.of(BpmnType.TASK), BpmnType.SERVICE_TASK, null, null);
  static final ConnectorElementType MESSAGE_THROW_EVENT = new ConnectorElementType(
      java.util.Set.of(BpmnType.INTERMEDIATE_THROW_EVENT), BpmnType.INTERMEDIATE_THROW_EVENT, null, null);
  static final String WEBHOOK = "io.camunda:webhook:1";
  /** Task states after which a push notification wakes the client up. */
  static final String WAKE_STATES =
      "[\"TASK_STATE_COMPLETED\", \"TASK_STATE_FAILED\", \"TASK_STATE_CANCELED\", \"TASK_STATE_REJECTED\", "
          + "\"TASK_STATE_INPUT_REQUIRED\", \"TASK_STATE_AUTH_REQUIRED\"]";

  public static void main(String[] args) throws Exception {
    Path out = Path.of(args.length > 0 ? args[0] : ".");
    ObjectWriter writer =
        new ObjectMapper()
            .registerModule(new ElementTemplateModule())
            .writer(new DefaultPrettyPrinter().withObjectIndenter(new DefaultIndenter().withLinefeed("\n")));
    write(writer, out, "a2a-1.0-client", client());
    write(writer, out, "a2a-1.0-client-webhook", clientWebhook());
    write(writer, out, "a2a-1.0-server-card", serverCard());
    write(writer, out, "a2a-1.0-server-rpc", serverRpc());
    write(writer, out, "a2a-1.0-server-push", serverPush());
  }

  static void write(ObjectWriter writer, Path dir, String name, ElementTemplate template) throws Exception {
    Path file = dir.resolve(name + ".json");
    Files.writeString(file, writer.writeValueAsString(template) + "\n");
    System.out.println(file.normalize() + " " + template.properties().size() + " properties");
  }

  // A2A 1.0 Client ----------------------------------------------------------------------------------------------

  static ElementTemplate client() {
    HttpOperation fetchAgentCard =
        HttpOperation.builder()
            .id("fetchAgentCard")
            .label("Fetch Agent Card")
            .method(HttpMethod.GET)
            .pathFeelExpression(HttpFeelBuilder.string().slash().property("agentCardLocation"))
            .properties(
                HttpOperationProperty.createStringProperty(
                    "agentCardLocation", PATH, "Path of the Agent Card relative to the base URL.", true,
                    ".well-known/agent-card.json"))
            .build();
    HttpOperation sendMessage =
        HttpOperation.builder()
            .id("sendMessage")
            .label("Send message")
            .method(HttpMethod.POST)
            .pathFeelExpression(HttpFeelBuilder.string().slash().property("rpcPath"))
            .properties(
                HttpOperationProperty.createStringProperty(
                    "rpcPath", PATH,
                    "Path of the JSON-RPC interface relative to the base URL. Ignored when the JSON-RPC URL is set.",
                    false, "a2a"),
                HttpOperationProperty.createStringProperty(
                    "text", BODY, "The text of the message. Use fromAi() when this task is an AI agent tool.", true,
                    null),
                HttpOperationProperty.createStringProperty(
                    "taskId", BODY,
                    "Set it to continue an existing task, for example one in TASK_STATE_INPUT_REQUIRED.", false, null),
                HttpOperationProperty.createStringProperty(
                    "contextId", BODY, "Groups related tasks. The server assigns one when it is empty.", false, null),
                HttpOperationProperty.createStringProperty(
                    "webhookUrl", BODY,
                    "Where the remote agent pushes task updates. Pair it with an A2A 1.0 Client Webhook event. "
                        + "Leave it empty to read the result from the response only.",
                    false, null),
                HttpOperationProperty.createStringProperty(
                    "pushToken", BODY, "Sent with every push as X-A2A-Notification-Token.", false,
                    "{{secrets.A2A_PUSH_TOKEN}}"))
            .bodyFeelExpression(
                HttpFeelBuilder.preFormatted(
                    feel(
                        """
                        ={jsonrpc: "2.0", id: string(uuid()), method: "SendMessage",
                          params: {
                            message: {messageId: string(uuid()), role: "ROLE_USER", parts: [{text: text}],
                                      taskId: taskId, contextId: contextId},
                            configuration: {
                              returnImmediately: webhookUrl != null,
                              taskPushNotificationConfig: if webhookUrl != null
                                then {url: webhookUrl, token: pushToken} else null}}}""")))
            .build();

    ElementTemplate http =
        HttpOutboundElementTemplateBuilder.create()
            .id("dev.hansel.a2a.client.v1")
            .name("A2A 1.0 Client")
            .version(2)
            .icon(ICON)
            .documentationRef(DOCS)
            .description(
                "Agent-to-Agent (A2A) 1.0 client over JSON-RPC: read a remote agent's Agent Card or send it a "
                    + "message. Runs on the HTTP JSON connector.")
            .servers(new HttpServerData("", "A2A server"))
            .elementType(SERVICE_TASK)
            .operations(fetchAgentCard, sendMessage)
            .build();

    return ElementTemplateBuilder.from(http)
        .engines(ENGINES)
        .appliesTo(BpmnType.TASK)
        .elementType(BpmnType.SERVICE_TASK)
        .replaceProperty(
            hiddenInput("fetchAgentCard_$headers", "headers", "={\"A2A-Version\": \"1.0\"}",
                new Equals("operationId", "fetchAgentCard")))
        .replaceProperty(
            hiddenInput("sendMessage_$headers", "headers",
                "={\"A2A-Version\": \"1.0\", \"Content-Type\": \"application/json\"}",
                new Equals("operationId", "sendMessage")))
        .properties(
            StringProperty.builder()
                .id("rpcUrl")
                .label("JSON-RPC URL")
                .description("The JSONRPC interface URL from the Agent Card's supportedInterfaces. Overrides base "
                    + "URL and path.")
                .group("operation")
                .optional(true)
                .feel(FeelMode.optional)
                .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput("rpcUrl"))
                .condition(new Equals("operationId", "sendMessage"))
                .build(),
            HiddenProperty.builder()
                .id("ignoreNullValues")
                .value("=true")
                .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput("ignoreNullValues"))
                .build())
        // inputs are evaluated in order, so url has to come after rpcUrl
        .removeProperties(p -> "url".equals(p.getId()))
        .properties(
            HiddenProperty.builder()
                .id("url")
                .group("url")
                .value("=if operationId = \"sendMessage\" and rpcUrl != null then rpcUrl else baseUrl + operationPath")
                .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput("url"))
                .build())
        .replaceProperty(
            CommonProperties.resultExpression(
                    feel(
                        """
                        ={agentResponse: {
                          result: if response.body.result.task != null then response.body.result.task
                                  else if response.body.result.message != null then response.body.result.message
                                  else if response.body.result = null and response.body.error = null then response.body
                                  else null,
                          error: response.body.error}}"""))
                .binding(new ZeebeTaskHeader("resultExpression"))
                .description("result is the Agent Card, the Task or the Message; error is the JSON-RPC error.")
                .build())
        .build();
  }

  // A2A 1.0 Client Webhook --------------------------------------------------------------------------------------

  static ElementTemplate clientWebhook() {
    String pushTaskId =
        "(if request.body.task != null then request.body.task.id else request.body.statusUpdate.taskId)";
    String pushState =
        "(if request.body.task != null then request.body.task.status.state else request.body.statusUpdate.status.state)";
    return webhookBase()
        // the notification token is checked by the webhook's API key authentication, which resolves secrets
        // (an activation condition does not) and rejects a wrong token before anything correlates
        .removeProperties(p -> "inbound.auth.type".equals(p.getId()))
        .id("dev.hansel.a2a.client.webhook.intermediate.v1")
        .name("A2A 1.0 Client Webhook Intermediate Catch Event")
        .version(5)
        .description(
            "Receives A2A 1.0 push notifications (StreamResponse) for a task sent with the A2A 1.0 Client. "
                + "Correlates on the task ID; a push without the expected X-A2A-Notification-Token is rejected.")
        .appliesTo(BpmnType.INTERMEDIATE_CATCH_EVENT, BpmnType.INTERMEDIATE_THROW_EVENT)
        .elementType(BpmnType.INTERMEDIATE_CATCH_EVENT)
        .propertyGroups(
            group("endpoint", "Webhook", hidden("inbound.method", "post"), context(null,
                "Part of the URL: {connectors base}/inbound/{webhook ID}. Use the same URL as the client's "
                    + "webhook URL."),
                hidden("inbound.auth.type", "APIKEY"),
                StringProperty.builder()
                    .id("inbound.auth.apiKey")
                    .label("Notification token")
                    .description("The token the client sent as push notification token; every push must carry it "
                        + "as X-A2A-Notification-Token.")
                    .value("{{secrets.A2A_PUSH_TOKEN}}")
                    .binding(new ZeebeProperty("inbound.auth.apiKey"))
                    .constraints(PropertyConstraints.builder().notEmpty(true).build())
                    .build(),
                hidden("inbound.auth.apiKeyLocator", "=request.headers.`x-a2a-notification-token`")),
            group("correlation", "Correlation",
                StringProperty.builder()
                    .id("correlationKeyProcess")
                    .label("Task ID")
                    .description("The ID of the task the A2A 1.0 Client sent: the Task's id for a new task, the "
                        + "Message's taskId for a follow-up.")
                    .feel(FeelMode.required)
                    .value("=if agentResponse.result.taskId != null then agentResponse.result.taskId "
                        + "else agentResponse.result.id")
                    .binding(ZeebeSubscriptionProperty.CORRELATION_KEY)
                    .constraints(PropertyConstraints.builder().notEmpty(true).build())
                    .build(),
                hidden("correlationKeyExpression", "=" + pushTaskId),
                // a fast server can push before the client's send task has returned and the event is waiting
                CommonProperties.messageTtl().value("PT1M")
                    .description("How long a push waits for the event to start waiting. A push can arrive before "
                        + "the send task has returned.").build(),
                CommonProperties.messageNameUuid().build()),
            group("activation", "Activation",
                CommonProperties.activationCondition()
                    .value("=list contains(" + WAKE_STATES + ", " + pushState + ")")
                    .description("By default the event fires on final, input-required and auth-required states.")
                    .build()),
            output("={toolCallResult: if request.body.task != null then request.body.task else request.body}",
                "Maps the push request to process variables. The default hands the pushed Task to the AI agent as "
                    + "toolCallResult."))
        .build();
  }

  // A2A 1.0 Server: Agent Card ----------------------------------------------------------------------------------

  static ElementTemplate serverCard() {
    return webhookBase()
        .id("dev.hansel.a2a.server.card.v1")
        .name("A2A 1.0 Server: Agent Card")
        .version(5)
        .description(
            "Serves the A2A 1.0 Agent Card on GET {connectors base}/inbound/{webhook ID}. Put it on the start event "
                + "of a process that ends right away: every request starts one run of that process. A proxy maps "
                + "/.well-known/agent-card.json to the webhook, because the connectors runtime mounts webhooks "
                + "under /inbound.")
        .appliesTo(BpmnType.START_EVENT)
        .elementType(BpmnType.START_EVENT)
        .propertyGroups(
            group("endpoint", "Webhook", hidden("inbound.method", "get"),
                context("a2a-card", "Clients read the card from {connectors base}/inbound/{webhook ID}.")),
            group("card", "Agent Card",
                TextProperty.builder()
                    .id("inbound.responseExpression")
                    .label("Agent Card")
                    .description("Edit card: the agent's name, description, version and skills. Clients choose "
                        + "the agent by its skills, so list what its tools can do. The rest of the expression adds "
                        + "the JSON-RPC endpoint, from the secret A2A_PUBLIC_URL, and the capabilities, with push "
                        + "notifications switched by the secret A2A_PUSH_ENABLED; keep it unchanged.")
                    .feel(FeelMode.required)
                    .value(
                        feel(
                            """
                            ={card: {
                                name: "Task agent",
                                description: "Answers questions and asks for clarification when a request is ambiguous.",
                                version: "1.0.0",
                                skills: [{id: "answer", name: "Answer a question",
                                          description: "Answers general questions.", tags: ["qa"]}]},
                              response: {statusCode: 200,
                                headers: {"Content-Type": "application/json", "Cache-Control": "public, max-age=300"},
                                body: context merge([card, {
                                  supportedInterfaces: [{url: "{{secrets.A2A_PUBLIC_URL}}/a2a",
                                                         protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
                                  capabilities: {streaming: false,
                                                 pushNotifications: "{{secrets.A2A_PUSH_ENABLED}}" = "true",
                                                 extendedAgentCard: false},
                                  defaultInputModes: ["text/plain", "application/json"],
                                  defaultOutputModes: ["text/plain", "application/json"]}])}
                             }.response"""))
                    .binding(new ZeebeProperty("inbound.responseExpression"))
                    .build()),
            output(null, "Maps the card request to process variables. Empty by default: serving the card needs none."))
        .build();
  }

  // A2A 1.0 Server: JSON-RPC endpoint ---------------------------------------------------------------------------

  static ElementTemplate serverRpc() {
    return webhookBase(true)
        .id("dev.hansel.a2a.server.rpc.v1")
        .name("A2A 1.0 Server: JSON-RPC endpoint")
        .version(2)
        .description(
            "The A2A 1.0 JSON-RPC endpoint: POST {connectors base}/inbound/{webhook ID}. Every request starts one run "
                + "of the process, which parses, validates and answers it. The webhook waits for the run to end and "
                + "answers with the process variable rpcResponse as the JSON body. Because the run is synchronous, "
                + "it has to end within the webhook's response timeout.")
        .appliesTo(BpmnType.START_EVENT)
        .elementType(BpmnType.START_EVENT)
        .propertyGroups(
            group("endpoint", "Webhook", hidden("inbound.method", "post"),
                context("a2a", "Clients POST JSON-RPC requests to {connectors base}/inbound/{webhook ID}."),
                hidden("inbound.responseExpression",
                    "={statusCode: 200, headers: {\"Content-Type\": \"application/json\"}, "
                        + "body: correlation.variables.rpcResponse}")),
            output("={rpc: request.body, hdr: request.headers}",
                "Maps the request to process variables: rpc is the JSON-RPC request, hdr its headers. The process "
                    + "reads both, so keep them."))
        .build();
  }

  // A2A 1.0 Server: push task update ----------------------------------------------------------------------------

  static ElementTemplate serverPush() {
    HttpOperation push =
        HttpOperation.builder()
            .id("pushTaskUpdate")
            .label("Push task update")
            .method(HttpMethod.POST)
            .pathFeelExpression(HttpFeelBuilder.preFormatted("=\"\""))
            .properties(
                HttpOperationProperty.createFeelProperty(
                    "config", BODY,
                    "The client's push notification config: url, optional token and optional authentication "
                        + "(scheme and credentials).",
                    true, "=config"),
                HttpOperationProperty.createFeelProperty(
                    "payload", BODY,
                    "The StreamResponse to push, for example {task: {id: ..., contextId: ..., status: {...}}}.", true,
                    "=payload"))
            .bodyFeelExpression(HttpFeelBuilder.preFormatted("=payload"))
            .build();

    ElementTemplate http =
        HttpOutboundElementTemplateBuilder.create()
            .id("dev.hansel.a2a.server.push.v1")
            .name("A2A 1.0 Server: push task update")
            .version(4)
            .icon(ICON)
            .documentationRef(DOCS)
            .description(
                "Service task that POSTs a task update to a client's push notification URL as an A2A 1.0 "
                    + "StreamResponse, with the config's Authorization and X-A2A-Notification-Token headers. A "
                    + "delivery that still fails after its retries raises the BPMN error PUSH_FAILED. Runs on the "
                    + "HTTP JSON connector.")
            .servers(new HttpServerData("=config.url", "Push notification URL"))
            .elementType(SERVICE_TASK)
            .operation(push)
            .build();

    return ElementTemplateBuilder.from(http)
        .engines(ENGINES)
        .appliesTo(BpmnType.TASK)
        .elementType(BpmnType.SERVICE_TASK)
        // inputs are evaluated in order, so the headers have to come after config
        .removeProperties(p -> "pushTaskUpdate_$headers".equals(p.getId()))
        .properties(
            hiddenInput("pushTaskUpdate_$headers", "headers",
                feel(
                    """
                    =context(get entries({
                      "Content-Type": "application/a2a+json",
                      "Authorization": if config.authentication != null
                        then config.authentication.scheme + " " + config.authentication.credentials else null,
                      "X-A2A-Notification-Token": config.token})[item.value != null])"""),
                new Equals("operationId", "pushTaskUpdate")),
            HiddenProperty.builder().id("ignoreNullValues").value("=true")
                .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput("ignoreNullValues"))
                .build())
        .replaceProperty(
            CommonProperties.errorExpression()
                .value("=if error != null then bpmnError(\"PUSH_FAILED\", string(error.message)) else null")
                .binding(new ZeebeTaskHeader("errorExpression"))
                .build())
        .replaceProperty(
            CommonProperties.resultExpression("={a2aPushStatus: response.status}")
                .binding(new ZeebeTaskHeader("resultExpression"))
                .build())
        .build();
  }

  // helpers -----------------------------------------------------------------------------------------------------

  /** Webhook plumbing the inbound templates share: type, no HMAC, no auth, asynchronous, automatic deduplication. */
  static ElementTemplateBuilder webhookBase() {
    return webhookBase(false);
  }

  static ElementTemplateBuilder webhookBase(boolean synchronous) {
    return ElementTemplateBuilder.createInbound()
        .type(WEBHOOK)
        .version(1)
        .icon(ICON)
        .documentationRef(DOCS)
        .engines(ENGINES)
        .properties(
            hidden("inbound.shouldValidateHmac", "disabled"),
            hidden("inbound.auth.type", "NONE"),
            hidden("synchronousResponse", String.valueOf(synchronous)),
            hidden("consumeUnmatchedEvents", "true"),
            hidden("deduplicationModeManualFlag", "false"),
            hidden("deduplicationMode", "AUTO"));
  }

  /** The Output mapping group every connector shows: a result variable and a result expression. */
  static PropertyGroup output(String expression, String description) {
    var resultExpression = expression == null
        ? CommonProperties.resultExpression() : CommonProperties.resultExpression(expression);
    return group("output", "Output mapping",
        CommonProperties.resultVariable().binding(new ZeebeProperty("resultVariable")).build(),
        resultExpression.description(description).binding(new ZeebeProperty("resultExpression")).build());
  }

  static PropertyGroup group(String id, String label, Property... properties) {
    return PropertyGroup.builder()
        .id(id)
        .label(label)
        .properties(java.util.Arrays.stream(properties).map(p -> withGroup(p, id)).toList())
        .build();
  }

  static Property withGroup(Property p, String group) {
    return p.getGroup() == null ? p.toBuilder().group(group).build() : p;
  }

  static Property hidden(String name, String value) {
    return HiddenProperty.builder().id(name).value(value).binding(new ZeebeProperty(name)).build();
  }

  static Property hiddenInput(String id, String name, String value, Equals condition) {
    return HiddenProperty.builder()
        .id(id)
        .group("parameters")
        .value(value)
        .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput(name))
        .condition(condition)
        .build();
  }

  static Property context(String value, String description) {
    return StringProperty.builder()
        .id("inbound.context")
        .label("Webhook ID")
        .description(description)
        .value(value)
        .binding(new ZeebeProperty("inbound.context"))
        .constraints(PropertyConstraints.builder().notEmpty(true).build())
        .build();
  }

  /** Joins a multi-line FEEL text block into one line, the form Modeler shows in a single-line field. */
  static String feel(String multiline) {
    return String.join(" ", multiline.strip().lines().map(String::strip).toList());
  }

  private A2aTemplates() {}
}
