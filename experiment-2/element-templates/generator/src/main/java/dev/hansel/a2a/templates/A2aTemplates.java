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
 * The A2A 1.0 element templates of experiment 2, written with the Camunda connector template generator DSL.
 *
 * <p>Outbound templates come from the HTTP DSL, so they run on the HTTP JSON connector. Inbound templates bind to
 * the HTTP webhook connector or to a plain message event. The A2A 1.0 wire format lives in the FEEL the
 * templates hide. Field layout and labels follow the out-of-the-box A2A Client templates, which speak A2A 0.3.
 */
public final class A2aTemplates {

  static final String DOCS = "https://a2a-protocol.org/latest/specification/";
  static final Engines ENGINES = new Engines("^8.10");
  static final ElementTemplateIcon ICON =
      ElementTemplateIcon.from("a2a-icon.svg", A2aTemplates.class.getClassLoader());
  static final ConnectorElementType SERVICE_TASK =
      new ConnectorElementType(java.util.Set.of(BpmnType.TASK), BpmnType.SERVICE_TASK, null, null);
  static final ConnectorElementType MESSAGE_THROW_EVENT = new ConnectorElementType(
      java.util.Set.of(BpmnType.INTERMEDIATE_THROW_EVENT), BpmnType.INTERMEDIATE_THROW_EVENT, null, null);
  static final String WEBHOOK = "io.camunda:webhook:1";
  /** The query parameter that carries the agent ID; it finds the process instance the server agent lives in. */
  static final String AGENT_PARAM = "request.params.agent";

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
    write(writer, out, "a2a-1.0-server-send-message", serverSendMessage().get(0));
    write(writer, out, "a2a-1.0-server-send-message-follow-up", serverSendMessage().get(1));
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
            .version(1)
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
        .version(3)
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
        .version(3)
        .description(
            "Serves the A2A 1.0 Agent Card on GET {connectors base}/inbound/{webhook ID}?agent={agent ID}. The agent "
                + "query parameter finds the process instance the agent lives in; use it on an event sub-process "
                + "start. The card's JSON-RPC URL carries the same agent ID.")
        .appliesTo(BpmnType.START_EVENT)
        .elementType(BpmnType.MESSAGE_START_EVENT)
        .propertyGroups(
            group("endpoint", "Webhook", hidden("inbound.method", "get"),
                context("a2a-server-card", "Clients read the card from {connectors base}/inbound/{webhook ID}?agent={agent ID}.")),
            group("correlation", "Agent instance", hidden("correlationRequired", "required"),
                hidden("correlationKeyExpression", "=" + AGENT_PARAM), agentIdProperty(),
                CommonProperties.messageNameUuid().group("correlation").build()),
            group("card", "Agent Card",
                TextProperty.builder()
                    .id("inbound.responseExpression")
                    .label("Agent Card")
                    .description("Edit card: the agent's name, description, version and skills. Clients choose "
                        + "the agent by its skills, so list what its tools can do. The rest of the expression adds "
                        + "the SendMessage endpoint and capabilities; keep it unchanged.")
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
                              response: {statusCode: 200, headers: {"Content-Type": "application/json"},
                                body: context merge([card, {
                                  supportedInterfaces: [{url: "{{secrets.A2A_CONNECTORS_URL}}/inbound/a2a-server?agent="
                                                           + request.params.agent,
                                                         protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
                                  capabilities: {streaming: false, pushNotifications: true, extendedAgentCard: false},
                                  defaultInputModes: ["text/plain"], defaultOutputModes: ["text/plain"]}])}
                             }.response"""))
                    .binding(new ZeebeProperty("inbound.responseExpression"))
                    .build()),
            output(null, "Maps the card request to process variables. Empty by default: serving the card needs none."))
        .build();
  }

  // A2A 1.0 Server: SendMessage ---------------------------------------------------------------------------------

  /** A FEEL JSON-RPC error for an A2A error code, with the google.rpc.ErrorInfo detail A2A 1.0 requires. */
  static String a2aError(final int code, final String message, final String reason) {
    return "{code: " + code + ", message: \"" + message + "\", data: [{\"@type\": "
        + "\"type.googleapis.com/google.rpc.ErrorInfo\", reason: \"" + reason + "\", domain: \"a2a-protocol.org\"}]}";
  }

  static List<ElementTemplate> serverSendMessage() {
    String msg = "request.body.params.message";
    String taskId = "(if " + msg + ".taskId != null then " + msg + ".taskId else " + msg + ".messageId)";
    String contextId = "(if " + msg + ".contextId != null then " + msg + ".contextId else " + taskId + ")";
    String pushConfig = "request.body.params.configuration.taskPushNotificationConfig";
    String method = "request.body.method";
    String version = "get value(request.headers, \"a2a-version\")";
    String contentType = "get value(request.headers, \"content-type\")";
    // a missing or empty A2A-Version header means 1.0; any 1.x is accepted
    String versionOk = "(if " + version + " instance of string then (" + version + " = \"\" or " + version
        + " = \"1\" or starts with(" + version + ", \"1.\")) else true)";
    String contentTypeOk = "(" + contentType + " instance of string and (starts with(lower case(" + contentType
        + "), \"application/json\") or starts with(lower case(" + contentType + "), \"application/a2a+json\")))";
    String jsonRpcOk = "(request.body.jsonrpc instance of string and request.body.jsonrpc = \"2.0\" and " + method
        + " instance of string)";
    String messageOk = "(" + msg + " instance of context and " + msg + ".messageId instance of string and " + msg
        + ".role instance of string and " + msg + ".parts instance of list and count(" + msg + ".parts) > 0)";
    String textOnly = "(" + msg + ".parts instance of list and (every part in " + msg + ".parts satisfies part "
        + "instance of context and part.text instance of string and (part.mediaType = null or part.mediaType = "
        + "\"text/plain\")))";
    // the agent runs every task in the background and answers by push notification only
    String backgroundWithPush =
        "request.body.params.configuration.returnImmediately = true and " + pushConfig + ".url != null";
    String valid = versionOk + " and " + contentTypeOk + " and " + jsonRpcOk + " and " + method
        + " = \"SendMessage\" and " + messageOk + " and " + textOnly + " and " + backgroundWithPush;
    // The webhook answers before it correlates, so it cannot know whether a task still waits for a follow-up.
    // A follow-up therefore gets a Message that states only what is known, not a Task with a guessed state.
    String response =
        "={statusCode: 200, headers: {\"Content-Type\": \"application/json\"}, body: "
            + "{jsonrpc: \"2.0\", id: request.body.id, result: if " + msg + ".taskId = null "
            + "then {task: {id: " + taskId + ", contextId: " + contextId + ", "
            + "status: {state: \"TASK_STATE_SUBMITTED\", timestamp: "
            + "substring(string(date and time(now(), \"UTC\")), 1, 19) + \"Z\"}}} "
            + "else {message: {messageId: \"reply-\" + " + msg + ".messageId, role: \"ROLE_AGENT\", "
            + "taskId: " + msg + ".taskId, contextId: " + contextId + ", parts: [{text: \"Message received for task \" + "
            + msg + ".taskId + \". If this task is waiting for input, its next update arrives as a push notification. "
            + "If the task is closed, nothing receives this message and no update will follow: start a new task.\"}]}}"
            + "}}";
    // the verification expression runs before activation, so it can answer requests that activate nothing
    String rejectInvalid =
        "=if " + valid + " then null "
            + "else {statusCode: 200, headers: {\"Content-Type\": \"application/json\"}, body: "
            + "{jsonrpc: \"2.0\", id: request.body.id, error: "
            + "if not(" + versionOk + ") then "
            + a2aError(-32009, "Unsupported A2A-Version: this agent speaks A2A 1.0", "VERSION_NOT_SUPPORTED")
            + " else if not(" + contentTypeOk + ") then "
            + a2aError(-32005, "Content-Type must be application/json", "CONTENT_TYPE_NOT_SUPPORTED")
            + " else if not(" + jsonRpcOk + ") then {code: -32600, message: \"Invalid Request\"}"
            + " else if list contains([\"SendStreamingMessage\", \"SubscribeToTask\"], " + method + ") then "
            + a2aError(-32004, "Unsupported operation: streaming is not supported", "UNSUPPORTED_OPERATION")
            + " else if " + method + " = \"GetExtendedAgentCard\" then "
            + a2aError(-32004, "Unsupported operation: the extended agent card is not supported",
                "UNSUPPORTED_OPERATION")
            // spec methods this agent cannot serve, because it keeps no task store: not "Method not found"
            + " else if list contains([\"GetTask\", \"CancelTask\", \"ListTasks\", "
            + "\"CreateTaskPushNotificationConfig\", \"GetTaskPushNotificationConfig\", "
            + "\"ListTaskPushNotificationConfigs\", \"DeleteTaskPushNotificationConfig\"], " + method + ") then "
            + a2aError(-32004, "Unsupported operation: this agent keeps no task store. Task updates arrive only as "
                + "push notifications to the configuration of the SendMessage that started the task.",
                "UNSUPPORTED_OPERATION")
            + " else if " + method + " != \"SendMessage\" then {code: -32601, message: \"Method not found\"}"
            + " else if not(" + messageOk + ") then {code: -32602, message: \"Invalid params: message with "
            + "messageId, role and a non-empty parts list is required\"}"
            + " else if not(" + textOnly + ") then "
            + a2aError(-32005, "Content type not supported: this agent accepts text/plain text parts only",
                "CONTENT_TYPE_NOT_SUPPORTED")
            + " else "
            + a2aError(-32004, "Unsupported operation: this agent runs tasks in the background and answers by push "
                + "notification only. Set configuration.returnImmediately to true and "
                + "configuration.taskPushNotificationConfig.url.", "UNSUPPORTED_OPERATION")
            + "}}";
    String messageText = "string join(for part in " + msg + ".parts return part.text, \" \")";
    // Both elements must carry the same connector properties (method, context, response) so the runtime puts
    // them behind one endpoint; activation condition, correlation and result are per element.
    Property[] endpoint = {
      hidden("inbound.method", "post"),
      context("a2a-server", "The JSON-RPC endpoint is {connectors base}/inbound/{webhook ID}?agent={agent ID}. "
          + "Use the same webhook ID on the follow-up event."),
      hidden("inbound.verificationExpression", rejectInvalid),
      hidden("inbound.responseExpression", response)
    };

    ElementTemplate newTask =
        webhookBase()
            .id("dev.hansel.a2a.server.send-message.v1")
            .name("A2A 1.0 Server: SendMessage (new task)")
            .version(5)
            .description(
                "A2A 1.0 JSON-RPC SendMessage without a taskId: a new task. The agent query parameter finds the "
                    + "process instance the agent lives in; use it on a non-interrupting event sub-process start. "
                    + "The response is the Task in TASK_STATE_SUBMITTED.")
            .appliesTo(BpmnType.START_EVENT)
            .elementType(BpmnType.MESSAGE_START_EVENT)
            .propertyGroups(
                group("endpoint", "Webhook", endpoint),
                group("correlation", "Agent instance",
                    hidden("activationCondition", "=" + valid + " and " + msg + ".taskId = null"),
                    hidden("correlationRequired", "required"), hidden("correlationKeyExpression", "=" + AGENT_PARAM),
                    hidden("messageIdExpression", "=" + msg + ".messageId"), agentIdProperty(),
                    CommonProperties.messageNameUuid().group("correlation").build()),
                output("={taskId: " + taskId + ", contextId: " + contextId + ", messageText: " + messageText
                        + ", pushNotification: " + pushConfig + ", taskState: \"TASK_STATE_SUBMITTED\"}",
                    "Maps the SendMessage request to process variables. The push event and the follow-up event of "
                        + "this task read taskId, contextId and pushNotification; keep them."))
            .build();

    ElementTemplate followUp =
        webhookBase()
            .id("dev.hansel.a2a.server.send-message.follow-up.v1")
            .name("A2A 1.0 Server: SendMessage (follow-up)")
            .version(5)
            .description(
                "A2A 1.0 JSON-RPC SendMessage with a taskId: the client's answer to a task in "
                    + "TASK_STATE_INPUT_REQUIRED, which becomes toolCallResult. Correlates on the taskId, so it reaches only a task that is waiting. "
                    + "The response is a Message that confirms receipt only, because the webhook answers before it "
                    + "knows whether the task still waits. "
                    + "A task that is already final has nothing waiting; the client must start a new task.")
            .appliesTo(BpmnType.INTERMEDIATE_CATCH_EVENT)
            .elementType(BpmnType.INTERMEDIATE_CATCH_EVENT)
            .propertyGroups(
                group("endpoint", "Webhook", endpoint),
                group("correlation", "Task",
                    hidden("activationCondition", "=" + valid + " and " + msg + ".taskId != null"),
                    hidden("correlationKeyExpression", "=" + msg + ".taskId"),
                    hidden("messageIdExpression", "=" + msg + ".messageId"),
                    StringProperty.builder()
                        .id("correlationKeyProcess")
                        .label("Task ID")
                        .feel(FeelMode.required)
                        .value("=taskId")
                        .binding(ZeebeSubscriptionProperty.CORRELATION_KEY)
                        .constraints(PropertyConstraints.builder().notEmpty(true).build())
                        .build(),
                    CommonProperties.messageNameUuid().group("correlation").build()),
                output("={toolCallResult: " + messageText + ", messageText: " + messageText + ", pushNotification: "
                        + pushConfig + "}",
                    "Maps the follow-up request to process variables. The default hands the client's answer to the AI "
                        + "agent as toolCallResult and keeps the client's latest push notification config."))
            .build();
    return List.of(newTask, followUp);
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
                HttpOperationProperty.createStringProperty(
                    "state", BODY,
                    "TASK_STATE_COMPLETED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_FAILED, TASK_STATE_CANCELED, "
                        + "TASK_STATE_REJECTED or TASK_STATE_WORKING. Use fromAi() to let the agent choose.",
                    true, "TASK_STATE_COMPLETED"),
                HttpOperationProperty.createStringProperty(
                    "text", BODY, "The agent's answer or question. Use fromAi() inside an AI agent.", true, null),
                HttpOperationProperty.createFeelProperty("taskId", BODY, "The A2A task ID.", true, "=taskId"),
                HttpOperationProperty.createFeelProperty("contextId", BODY, "The A2A context ID.", true, "=contextId"))
            .bodyFeelExpression(
                HttpFeelBuilder.preFormatted(
                    feel(
                        """
                        ={task: {id: taskId, contextId: contextId,
                          status: {state: state,
                                   message: {messageId: string(uuid()), role: "ROLE_AGENT", parts: [{text: text}],
                                             taskId: taskId, contextId: contextId}}}}""")))
            .build();

    ElementTemplate http =
        HttpOutboundElementTemplateBuilder.create()
            .id("dev.hansel.a2a.server.push.v1")
            .name("A2A 1.0 Server: push task update")
            .version(2)
            .icon(ICON)
            .documentationRef(DOCS)
            .description(
                "Message throw event that POSTs the task's current state to the client's push notification URL as "
                    + "an A2A 1.0 StreamResponse, with the X-A2A-Notification-Token header. Runs on the HTTP JSON "
                    + "connector.")
            .servers(new HttpServerData("=pushNotification.url", "Push notification URL"))
            .elementType(MESSAGE_THROW_EVENT)
            .operation(push)
            .build();

    return ElementTemplateBuilder.from(http)
        .engines(ENGINES)
        .appliesTo(BpmnType.INTERMEDIATE_THROW_EVENT)
        .elementType(BpmnType.INTERMEDIATE_THROW_EVENT)
        .properties(
            StringProperty.builder()
                .id("pushToken")
                .label("Notification token")
                .group("server")
                .feel(FeelMode.required)
                .value("=pushNotification.token")
                .binding(new io.camunda.connector.generator.dsl.PropertyBinding.ZeebeInput("pushToken"))
                .build())
        // inputs are evaluated in order, so the headers have to come after pushToken
        .removeProperties(p -> "pushTaskUpdate_$headers".equals(p.getId()))
        .properties(
            hiddenInput("pushTaskUpdate_$headers", "headers",
                // A2A 1.0 names application/a2a+json, but the HTTP webhook connector only parses application/json
                // into request.body, and the A2A 1.0 Client Webhook needs the parsed task to correlate
                "={\"Content-Type\": \"application/json\", \"X-A2A-Notification-Token\": pushToken}",
                new Equals("operationId", "pushTaskUpdate")))
        .replaceProperty(
            CommonProperties.resultExpression("={a2aPushStatus: response.status}")
                .binding(new ZeebeTaskHeader("resultExpression"))
                .build())
        .build();
  }

  // helpers -----------------------------------------------------------------------------------------------------

  /** Webhook plumbing the inbound templates share: type, no HMAC, no auth, asynchronous, automatic deduplication. */
  static ElementTemplateBuilder webhookBase() {
    return ElementTemplateBuilder.createInbound()
        .type(WEBHOOK)
        .version(1)
        .icon(ICON)
        .documentationRef(DOCS)
        .engines(ENGINES)
        .properties(
            hidden("inbound.shouldValidateHmac", "disabled"),
            hidden("inbound.auth.type", "NONE"),
            hidden("synchronousResponse", "false"),
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

  /** The process-side correlation key: the agent ID the instance hands out in its Agent Card URL. */
  static Property agentIdProperty() {
    return StringProperty.builder()
        .id("correlationKeyProcess")
        .label("Agent ID")
        .description("The ID this process instance's agent is reached by, the value of the agent query parameter.")
        .feel(FeelMode.required)
        .value("=a2aAgentId")
        .binding(ZeebeSubscriptionProperty.CORRELATION_KEY)
        .constraints(PropertyConstraints.builder().notEmpty(true).build())
        .build();
  }

  /** Joins a multi-line FEEL text block into one line, the form Modeler shows in a single-line field. */
  static String feel(String multiline) {
    return String.join(" ", multiline.strip().lines().map(String::strip).toList());
  }

  private A2aTemplates() {}
}
