"""Generate the client-side AI Agent Task and its A2A tool loop."""
from bpmn_gen.client import form
from bpmn_gen.feel import one
from bpmn_gen.lib import Proc, q
from gen_card import feel_str


CONFIRMATION_FIELDS = (
    ("claimMerchant", "Merchant", "textfield"),
    ("claimCurrency", "Currency", "textfield"),
    ("claimFirstAmount", "First charge amount", "number"),
    ("claimSecondAmount", "Second charge amount", "number"),
    ("claimExpectedAmount", "Expected order amount", "number"),
    ("claimSyntheticOnly", "I confirm these are synthetic demonstration values", "checkbox"),
)

SAMPLE = (
    "Northwind Electronics charged USD 49.95 twice for one order. "
    "The expected charge was USD 49.95. Review this synthetic example only."
)

SYSTEM_PROMPT = (
    "You are the client-side AI agent for a synthetic A2A demonstration. "
    "The remote server agent owns the review; do not invent case facts or make financial decisions. "
    "Start by calling DiscoverAgentCard, then use SendA2AMessage for the user's request. "
    "GetA2ATask polls the task returned by the prior send. If the server requests input, "
    "call AskClientForInput with the server's exact question, then send the user's answer and "
    "confirmed syntheticClaim as a follow-up. SendA2AMessage continues the task and context from "
    "the prior send result, and takes confirmation data only from the AskClientForInput form result. "
    "Neither tool accepts model-supplied task identifiers. Never send model-inferred values or invent IDs. "
    "Never describe a request as completed unless a GetA2ATask response reports TASK_STATE_COMPLETED. "
    "Report failures and nonterminal states accurately. This example performs no real financial action."
)

CONFIRMED_CLIENT_DATA_PARTS = """
flatten(
  for records in [flatten(
    for message in clientAgent.context.conversation.messages[item.role = "tool_call_result"]
    return message.results[item.name = "AskClientForInput"]
  )]
  return if count(records) > 0 then
    if records[count(records)].content instance of context then
      if records[count(records)].content.toolCallResult instance of context then
        if records[count(records)].content.toolCallResult.syntheticClaim instance of context then
          [{data: {syntheticClaim: records[count(records)].content.toolCallResult.syntheticClaim}}]
        else []
      else if records[count(records)].content.syntheticClaim instance of context then
        [{data: {syntheticClaim: records[count(records)].content.syntheticClaim}}]
      else []
    else []
  else []
)
"""

PREVIOUS_A2A_TASK_PARAMS = """
(for records in [flatten(
  for message in clientAgent.context.conversation.messages[item.role = "tool_call_result"]
  return message.results[item.name = "SendA2AMessage"]
)] return if count(records) > 0 then
  (for content in [records[count(records)].content] return
    for response in [if content instance of context and content.toolCallResult instance of context
                     then content.toolCallResult else content] return
      for result in [if response instance of context then response.result else null] return
        if result instance of context then
          if result.task instance of context then
            {taskId: result.task.id, contextId: result.task.contextId}
          else if result.id instance of string and result.contextId instance of string then
            {taskId: result.id, contextId: result.contextId}
          else {}
        else {}
  )[1][1][1]
else {})[1]
"""


def build():
    p = Proc("a2a-client", "01 Client Agent - Ask the Server")
    p.start("QuestionAsked", "Client request received", 150, 210,
            ext='<zeebe:formDefinition formId="a2a-client-ask" />')
    p.xor("ClientAgentInputJoin", "Start or continue agent turn?", 245, 203)
    p.node("serviceTask", "ClientAgent", "Plan and coordinate with the server", 300, 188)
    p.xor("ClientHasTools", "Client agent requested tools?", 470, 203)

    tools_ext = (
        '<zeebe:adHoc activeElementsCollection="=[toolCall._meta.name]" />'
        '<zeebe:ioMapping><zeebe:input target="toolCallResult" /></zeebe:ioMapping>'
        '<zeebe:properties><zeebe:property name="io.camunda.agenticai.toolContainer" '
        'value="true" /></zeebe:properties>'
    )
    tools_inner = (
        '<bpmn:multiInstanceLoopCharacteristics isSequential="false">'
        '<bpmn:extensionElements><zeebe:loopCharacteristics '
        'inputCollection="=clientAgent.toolCalls" inputElement="toolCall" '
        'outputCollection="toolCallResults" '
        'outputElement="={id: toolCall._meta.id, name: toolCall._meta.name, '
        'content: toolCallResult}" /></bpmn:extensionElements>'
        '</bpmn:multiInstanceLoopCharacteristics>'
    )
    p.sub("ClientTools", "Client Agent - A2A Tools", 620, 72, 680, 330,
          kind="adHocSubProcess", ext=tools_ext, inner=tools_inner)
    p.node(
        "serviceTask", "DiscoverAgentCard", "Discover server agent",
        675, 125, parent="ClientTools",
        doc=("Read the public Agent Card before contacting the remote server. Use this tool first "
             "to inspect its name, JSON-RPC endpoint and advertised capabilities. Returns the card; "
             "does not send a task or expose credentials."),
    )
    p.node(
        "serviceTask", "SendA2AMessage", "Send A2A message",
        830, 125, parent="ClientTools",
        doc=("Send a new A2A 1.0 message or a follow-up to the same task. Use the user's request "
             "as text. Follow-ups use task and context IDs from the prior send result. A structured "
             "syntheticClaim is added only from the AskClientForInput form result; neither can be "
             "supplied as an AI tool argument. Returns the JSON-RPC response and task."),
    )
    p.node(
        "serviceTask", "GetA2ATask", "Poll A2A task",
        985, 125, parent="ClientTools",
        doc=("Read the current state of the task returned by the prior SendA2AMessage call. "
             "The task ID comes from that response, not an AI tool argument. Poll while work "
             "continues and use the returned state and message to decide whether to request input "
             "or report a terminal result."),
    )
    p.node(
        "userTask", "AskClientForInput", "Ask client for missing input",
        1140, 125, parent="ClientTools",
        ext=('<zeebe:userTask /><zeebe:formDefinition formId="a2a-client-answer" />'
             '<zeebe:ioMapping>'
             '<zeebe:input source=%s target="question" />'
             '<zeebe:output source=%s target="toolCallResult" />'
             '</zeebe:ioMapping>' % (
                 q('=fromAi(toolCall.question, "The exact clarification requested by the server", "string")'),
                 q('={text: followUp, syntheticClaim: {merchant: claimMerchant, currency: claimCurrency, '
                   'chargeAmounts: [claimFirstAmount, claimSecondAmount], expectedAmount: claimExpectedAmount, '
                   'syntheticOnly: claimSyntheticOnly}}'),
             )),
        doc=("Pause for the user only when the server asks for missing information. Display its "
             "exact question and return the user's text plus explicitly confirmed synthetic claim "
             "fields. Never fill these fields from model inference."),
    )

    p.script(
        "PrepareClientResult", "Prepare client result", 640, 200,
        one("""=(for polls in [flatten(
          for message in clientAgent.context.conversation.messages[item.role = "tool_call_result"]
          return message.results[item.name = "GetA2ATask"]
          )] return
          for content in [if count(polls) > 0 then polls[count(polls)].content else null] return
          for body in [if content instance of context and content.toolCallResult instance of context
                       then content.toolCallResult else content] return
          for response in [if body instance of context then body.result else null] return
          for task in [if response instance of context then
            if response.task instance of context then response.task else response else null] return
          for state in [if task.status.state instance of string then task.status.state else null] return
          "### Client agent response\\n\\n" +
          (if clientAgent.responseText instance of string then clientAgent.responseText
           else "The client agent returned no text.") +
          "\\n\\n**Last observed server task state:** " +
          (if state instance of string then state else "No GetTask status was observed."))[1][1][1][1][1][1]"""),
        "resultText",
    )
    p.node("userTask", "ReviewClientResult", "Review client agent result", 810, 188,
           ext='<zeebe:userTask /><zeebe:formDefinition formId="a2a-client-result" />')
    p.end("ClientConversationFinished", "Client conversation finished", 990, 210)

    p.flow("QuestionAsked", "ClientAgentInputJoin")
    p.flow("ClientAgentInputJoin", "ClientAgent")
    p.flow("ClientAgent", "ClientHasTools")
    p.flow("ClientHasTools", "ClientTools", "tools requested",
           cond="=not(is empty(clientAgent.toolCalls))")
    p.flow("ClientHasTools", "PrepareClientResult", "final response", default=True)
    p.flow("ClientTools", "ClientAgentInputJoin", route="over:150")
    p.flow("PrepareClientResult", "ReviewClientResult")
    p.flow("ReviewClientResult", "ClientConversationFinished")

    forms = {
        "04-client-agent-ask.form": form("a2a-client-ask", [
            {"type": "text", "text": (
                "### Ask the A2A server agent\n\n"
                "The client AI agent discovers the server's Agent Card and chooses when to send, "
                "poll, or request missing input. The example uses synthetic dispute data only."
            )},
            {"type": "textarea", "key": "question", "label": "What should the server agent review?",
             "validate": {"required": True}, "defaultValue": SAMPLE},
        ]),
        "05-client-agent-confirm.form": form("a2a-client-answer", [
            {"type": "text", "text": (
                '="### The server needs more information\\n\\n" + question'
            )},
            {"type": "textarea", "key": "followUp", "label": "Your answer or additional context",
             "validate": {"required": True}},
            *[
                {
                    "type": kind, "key": key, "label": label,
                    "validate": {"required": True, **({"min": 0} if kind == "number" else {})},
                    **({"decimalDigits": 2} if kind == "number" else {}),
                }
                for key, label, kind in CONFIRMATION_FIELDS
            ],
        ]),
        "06-client-agent-result.form": form("a2a-client-result", [
            {"type": "text", "text": "=resultText"},
        ]),
    }

    http = {
        "DiscoverAgentCard": [
            ("method", "GET"),
            ("url", "{{secrets.A2A_AGENT_CARD_URL}}"),
            ("headers", '={"A2A-Version": "1.0"}'),
            ("readTimeoutInSeconds", "20"),
            ("resultExpression", "={toolCallResult: response.body}"),
        ],
        "SendA2AMessage": [
            ("method", "POST"),
            ("url", "{{secrets.A2A_RPC_URL}}"),
            ("headers", '={"A2A-Version": "1.0", "Content-Type": "application/json", '
                        '"X-A2A-Api-Key": "{{secrets.A2A_API_KEY}}"}'),
            ("body", one("""={
              jsonrpc: "2.0", id: uuid(), method: "SendMessage",
              params: {
                message: context merge([
                  {
                  messageId: uuid(), role: "ROLE_USER",
                  parts: concatenate(
                    [{text: fromAi(toolCall.text, "The user's request or follow-up text", "string")}],
                    CONFIRMED_CLIENT_DATA_PARTS
                  )
                  },
                PREVIOUS_A2A_TASK_PARAMS
                ]),
                configuration: {returnImmediately: true}
              }
            }""".replace("CONFIRMED_CLIENT_DATA_PARTS", CONFIRMED_CLIENT_DATA_PARTS)
                 .replace("PREVIOUS_A2A_TASK_PARAMS", PREVIOUS_A2A_TASK_PARAMS))),
            ("readTimeoutInSeconds", "60"),
            ("retries", "1"),
            ("resultExpression", "={toolCallResult: response.body}"),
        ],
        "GetA2ATask": [
            ("method", "POST"),
            ("url", "{{secrets.A2A_RPC_URL}}"),
            ("headers", '={"A2A-Version": "1.0", "Content-Type": "application/json", '
                        '"X-A2A-Api-Key": "{{secrets.A2A_API_KEY}}"}'),
            ("body", one("""={
              jsonrpc: "2.0", id: uuid(), method: "GetTask",
              params: {id: get value(PREVIOUS_A2A_TASK_PARAMS, "taskId")}
            }""".replace("PREVIOUS_A2A_TASK_PARAMS", PREVIOUS_A2A_TASK_PARAMS))),
            ("readTimeoutInSeconds", "30"),
            ("retries", "1"),
            ("resultExpression", "={toolCallResult: response.body}"),
        ],
    }
    ai_task = [
        ("provider.type", "openaiCompatible"),
        ("provider.openaiCompatible.endpoint", "{{secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT}}"),
        ("provider.openaiCompatible.authentication.apiKey", "{{secrets.CAMUNDA_PROVIDED_LLM_API_KEY}}"),
        ("provider.openaiCompatible.model.model", "{{secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL}}"),
        ("data.systemPrompt.prompt", "=" + feel_str(SYSTEM_PROMPT)),
        ("data.userPrompt.prompt", "=question"),
        ("data.tools.containerElementId", "ClientTools"),
        ("data.tools.toolCallResults", "=toolCallResults"),
        ("data.context", "=clientAgent.context"),
        ("data.memory.storage.type", "in-process"),
        ("data.memory.contextWindowSize", "=20"),
        ("data.limits.maxModelCalls", "=8"),
        ("resultVariable", "clientAgent"),
        ("retries", "1"),
    ]
    return p.xml(), forms, http, ai_task
