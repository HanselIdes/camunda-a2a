"""Generate the client-side AI Agent Sub-process and its root A2A tools."""
from bpmn_gen.client import form
from bpmn_gen.feel import one
from bpmn_gen.lib import Collab, Proc, q
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
    "The process has already fetched the remote Agent Card. "
    "ReadIntakeGuidance explains the synthetic demo's intake checklist. "
    "CheckConfirmedDetails checks whether the human has supplied confirmation; it does not reconcile charges. "
    "DraftReviewNote prepares an unsent draft for human review, not a financial decision. "
    "Use these local tools when useful; all charge arithmetic belongs to the remote server. "
    "Use SendA2AMessage to delegate the user's request to that remote agent. "
    "This tool sends the message and polls the returned task using an explicit BPMN flow. "
    "If the server requests input, "
    "call AskClientForInput with the server's exact question, then send the user's answer and "
    "confirmed syntheticClaim as a follow-up. SendA2AMessage continues the task and context from "
    "the prior send result, and takes confirmation data only from the AskClientForInput form result. "
    "An active task is continued; after a terminal task a new task uses the server-returned context ID. "
    "Neither tool accepts model-supplied task identifiers. Never send model-inferred values or invent IDs. "
    "Never describe a request as completed unless the tool result reports TASK_STATE_COMPLETED. "
    "Report failures and nonterminal states accurately. This example performs no real financial action."
)

CONFIRMED_CLIENT_DATA_PARTS = """
flatten(
  for records in [flatten(
    for message in agentContext.conversation.messages[item.role = "tool_call_result"]
    return message.results[item.name = "AskClientForInput"]
  )]
  return if count(records) > 0 then
    (for content in [records[count(records)].content[item.type = "object"][1].content]
     return for result in [if get value(content, "toolCallResult") instance of context
                           then content.toolCallResult else content]
     return if result.syntheticClaim instance of context then
       [{data: {syntheticClaim: result.syntheticClaim}}]
     else [])[1][1]
  else []
)
"""

PREVIOUS_A2A_TASK_PARAMS = """
(for records in [flatten(
  for message in agentContext.conversation.messages[item.role = "tool_call_result"]
  return message.results[item.name = "SendA2AMessage"]
)] return if count(records) > 0 then
  (for content in [records[count(records)].content[item.type = "object"][1].content] return
    for response in [if content instance of context and get value(content, "toolCallResult") instance of context
                     then content.toolCallResult else content] return
      for result in [if response instance of context then response.result else null] return
        for task in [if result instance of context and get value(result, "task") instance of context
                     then result.task else result] return
          if task.id instance of string and task.contextId instance of string then
            if task.status.state in ["TASK_STATE_COMPLETED", "TASK_STATE_CANCELED",
                                     "TASK_STATE_FAILED", "TASK_STATE_REJECTED"] then
              {contextId: task.contextId}
            else {taskId: task.id, contextId: task.contextId}
          else {}
  )[1][1][1][1]
else {})[1]
"""


CLIENT_RESULT_EXPRESSION = one("""=(for polls in [flatten(
  for message in agent.context.conversation.messages[item.role = "tool_call_result"]
  return message.results[item.name = "SendA2AMessage"]
  )] return
  for content in [if count(polls) > 0 then
    polls[count(polls)].content[item.type = "object"][1].content else null] return
  for body in [if content instance of context and get value(content, "toolCallResult") instance of context
               then content.toolCallResult else content] return
  for response in [if body instance of context then body.result else null] return
  for task in [if response instance of context then
    if get value(response, "task") instance of context then response.task else response else null] return
  for state in [if task.status.state instance of string then task.status.state else null] return
  "### Client agent response\\n\\n" +
  (if agent.responseText instance of string then agent.responseText
   else "The client agent returned no text.") +
  "\\n\\n**Last observed server task state:** " +
  (if state instance of string then state else "No server task status was observed."))[1][1][1][1][1][1]""")


def build():
    p = Proc("a2a-client", "01 Client Agent - Ask the Server")
    p.start("QuestionAsked", "Client request received", 150, 210,
            ext='<zeebe:formDefinition formId="a2a-client-ask" />')
    p.node(
        "serviceTask", "DiscoverAgentCard", "Fetch remote agent card", 230, 210,
        doc="Read the public Agent Card before entering the client agent. Returns the card, not credentials.",
    )
    p.xor("ClientJoin", "", 380, 225)
    p.sub("ClientAgent", "Client AI agent", 470, 80, 760, 510,
          kind="adHocSubProcess")
    p.node(
        "scriptTask", "ReadIntakeGuidance", "Read intake guidance", 530, 140,
        parent="ClientAgent",
        ext='<zeebe:script expression=%s resultVariable="toolCallResult" />' % q(one("""={
          syntheticDemoOnly: true,
          requiredDetails: ["merchant", "currency", "two charge amounts", "expected order amount",
                            "explicit confirmation that all values are synthetic"],
          clientResponsibilities: ["collect the user's account", "request missing confirmation",
                                   "delegate charge reconciliation", "prepare a draft for human review"],
          restrictions: ["do not infer financial fields from narrative",
                         "do not authorize refunds or decide fraud",
                         "do not treat this demonstration checklist as bank policy"]
        }""")),
        doc=("Read the local synthetic-demo intake checklist before collecting dispute details. "
             "Returns required information and the client/server responsibilities. "
             "This is demonstration guidance, not bank policy, and performs no external call."),
    )
    p.node(
        "scriptTask", "CheckConfirmedDetails", "Check confirmed details", 750, 140,
        parent="ClientAgent",
        ext=('<zeebe:ioMapping><zeebe:input source=%s target="confirmedParts" /></zeebe:ioMapping>'
             '<zeebe:script expression=%s resultVariable="toolCallResult" />' % (
                 q("=" + one(CONFIRMED_CLIENT_DATA_PARTS)),
                 q(one("""={
                   claim: if count(confirmedParts) = 1 then confirmedParts[1].data.syntheticClaim else null,
                   humanConfirmationPresent: claim instance of context,
                   syntheticOnlyConfirmed: claim.syntheticOnly = true,
                   nextStep: if claim instance of context and claim.syntheticOnly = true
                     then "Send the human-confirmed details to the remote reconciliation agent."
                     else "Ask the human to confirm the synthetic claim using AskClientForInput.",
                   notice: "Checks confirmation provenance only. The server validates and reconciles amounts."
                 }""")),
             )),
        doc=("Check whether AskClientForInput returned a human-confirmed synthetic claim. "
             "Accepts no model-provided financial fields. Returns confirmation presence and next steps, "
             "not arithmetic, eligibility or a dispute decision. Use when deciding whether to ask for details."),
    )
    p.node(
        "scriptTask", "DraftReviewNote", "Draft review note", 970, 140,
        parent="ClientAgent",
        ext=('<zeebe:ioMapping><zeebe:input source=%s target="draftText" /></zeebe:ioMapping>'
             '<zeebe:script expression=%s resultVariable="toolCallResult" />' % (
                 q('=fromAi(toolCall.summary, "Draft a concise note using only the user account and actual '
                   'remote agent results. Label missing evidence; do not invent facts or authorize action.", "string")'),
                 q('={draftOnly: true, text: draftText, '
                   'notice: "Unsent draft for human review. No refund, notification or financial action performed."}'),
             )),
        doc=("Format a draft note for the human reviewer after receiving remote reconciliation evidence. "
             "Supply a concise summary grounded in the user's account and actual tool results. "
             "Returns explicitly labeled draft text; it does not verify claims, send messages, "
             "change an account or authorize a refund."),
    )
    p.sub(
        "SendA2AMessage", "Ask remote agent", 510, 250, 680, 300, parent="ClientAgent",
        ext=('<zeebe:ioMapping>'
             '<zeebe:input source=%s target="remoteText" />'
             '<zeebe:input source=%s target="previousTask" />'
             '<zeebe:input source=%s target="confirmedParts" />'
             '<zeebe:output source="=remoteResponse" target="toolCallResult" />'
             '</zeebe:ioMapping>' % (
                 q('=fromAi(toolCall.text, "The user request or follow-up text", "string")'),
                 q("=" + one(PREVIOUS_A2A_TASK_PARAMS)),
                 q("=" + one(CONFIRMED_CLIENT_DATA_PARTS)),
             )),
        doc=("Delegate to the remote A2A agent. Sends a new message or follows up on the same task "
             "using response-derived task/context IDs. Polls two seconds apart while the task is working, "
             "then returns the actual JSON-RPC response, including input-required or failure states. "
             "Confirmed synthetic claim data comes only from the human form. "
             "Use AskClientForInput if the response requests confirmation; do not infer claim values."),
    )
    p.start("RemoteRequestStarted", "Remote request started", 535, 330, parent="SendA2AMessage")
    p.node("serviceTask", "SendRemoteMessage", "Send A2A message", 600, 308, parent="SendA2AMessage")
    p.xor("RemoteTaskAccepted", "Task returned?", 720, 323, parent="SendA2AMessage")
    p.xor("RemotePollJoin", "", 800, 323, parent="SendA2AMessage")
    p.catch_timer("WaitBeforeRemotePoll", "Wait 2 seconds", 745, 330, '="PT2S"',
                  parent="SendA2AMessage")
    p.node("serviceTask", "GetA2ATask", "Get A2A task", 825, 308, parent="SendA2AMessage")
    p.xor("RemoteTaskState", "Still working?", 1100, 323, parent="SendA2AMessage")
    p.xor("RemoteReplyJoin", "", 1100, 415, parent="SendA2AMessage")
    p.end("RemoteReplyReceived", "Remote agent replied", 1107, 450, parent="SendA2AMessage")
    p.flow("RemoteRequestStarted", "SendRemoteMessage")
    p.flow("SendRemoteMessage", "RemoteTaskAccepted")
    p.flow("RemoteTaskAccepted", "RemotePollJoin", "yes",
           cond='=remoteResponse.error = null and (remoteResponse.result.id instance of string or '
                'remoteResponse.result.task.id instance of string)')
    p.flow("RemoteTaskAccepted", "RemoteReplyJoin", "no task / error",
           default=True, route="back:30")
    p.flow("RemotePollJoin", "WaitBeforeRemotePoll")
    p.flow("WaitBeforeRemotePoll", "GetA2ATask")
    p.flow("GetA2ATask", "RemoteTaskState")
    p.flow("RemoteTaskState", "RemotePollJoin", "yes", route="over:30",
           cond='=(for task in [if remoteResponse.result.task instance of context then '
                'remoteResponse.result.task else remoteResponse.result] return '
                'remoteResponse.error = null and task.status.state in '
                '["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"])[1]')
    p.flow("RemoteTaskState", "RemoteReplyJoin", "otherwise", default=True, route="down-in")
    p.flow("RemoteReplyJoin", "RemoteReplyReceived")
    p.node(
        "userTask", "AskClientForInput", "Ask client for missing input",
        1190, 140, parent="ClientAgent",
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

    p.node("userTask", "ReviewClientResult", "User feedback", 1430, 210,
           ext='<zeebe:userTask /><zeebe:formDefinition formId="a2a-client-result" />')
    p.xor("ClientSatisfied", "User satisfied?", 1590, 225)
    p.script("PrepareClientFollowUp", "Use user feedback", 1030, 680, "=clientFeedback", "question")
    p.end("ClientConversationFinished", "Request answered", 1710, 232)

    p.flow("QuestionAsked", "DiscoverAgentCard")
    p.flow("DiscoverAgentCard", "ClientJoin")
    p.flow("ClientJoin", "ClientAgent")
    p.flow("ClientAgent", "ReviewClientResult")
    p.flow("ReviewClientResult", "ClientSatisfied")
    p.flow("ClientSatisfied", "ClientConversationFinished", "yes", cond='=clientSatisfied = "yes"')
    p.flow("ClientSatisfied", "PrepareClientFollowUp", "no - follow up", default=True, route="back:30")
    p.flow("PrepareClientFollowUp", "ClientJoin", route="back:60")

    forms = {
        "04-client-agent-ask.form": form("a2a-client-ask", [
            {"type": "text", "text": (
                "### Ask the A2A server agent\n\n"
                "The process fetches the server's Agent Card, then the client AI agent delegates "
                "through A2A templates. You can provide feedback and continue the conversation. "
                "The example uses synthetic dispute data only."
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
            {"type": "radio", "key": "clientSatisfied", "label": "Are you satisfied with this response?",
             "values": [{"label": "Yes, finish", "value": "yes"},
                        {"label": "No, send a follow-up", "value": "no"}],
             "validate": {"required": True}},
            {"type": "textarea", "key": "clientFeedback", "label": "Your follow-up",
             "conditional": {"hide": '=clientSatisfied != "no"'},
             "validate": {"required": True}},
        ]),
    }

    http = {
        "DiscoverAgentCard": [
            ("operationId", "fetchAgentCard"),
            ("url", "=camunda.secrets.A2A_AGENT_CARD_URL"),
            ("readTimeoutInSeconds", "20"),
            ("resultExpression", "={agentCard: response.body}"),
        ],
        "SendRemoteMessage": [
            ("operationId", "sendMessage"),
            ("apiKey", "=camunda.secrets.A2A_API_KEY"),
            ("url", "=camunda.secrets.A2A_RPC_URL"),
            ("message", one("""=context merge([
                  {
                  messageId: uuid(), role: "ROLE_USER",
                  parts: concatenate(
                    [{text: remoteText}], confirmedParts
                  )
                  },
                previousTask
                ])""")),
            ("readTimeoutInSeconds", "60"),
            ("retries", "1"),
            ("resultExpression", "={remoteResponse: response.body}"),
        ],
        "GetA2ATask": [
            ("operationId", "getTask"),
            ("apiKey", "=camunda.secrets.A2A_API_KEY"),
            ("url", "=camunda.secrets.A2A_RPC_URL"),
            ("taskId", '=if remoteResponse.result.task instance of context then '
                       'remoteResponse.result.task.id else remoteResponse.result.id'),
            ("readTimeoutInSeconds", "30"),
            ("retries", "1"),
            ("resultExpression", "={remoteResponse: response.body}"),
        ],
    }
    ai_subprocess = [
        ("provider.type", "openai"),
        ("provider.openai.api.type", "completions"),
        ("provider.openai.backend.type", "custom"),
        ("provider.openai.backend.custom.endpoint", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT"),
        ("provider.openai.backend.custom.authentication.type", "apiKey"),
        ("provider.openai.backend.custom.authentication.apiKey", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_API_KEY"),
        ("provider.openai.model.model", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL"),
        ("data.systemPrompt.prompt", "=" + feel_str(SYSTEM_PROMPT)),
        ("data.userPrompt.prompt", '=question + "\\n\\nRemote agent: " + agentCard.name + '
         '"\\nSkills: " + string join(agentCard.skills.name, ", ")'),
        ("agentContext", "=clientAgent.context"),
        ("data.memory.storage.type", "in-process"),
        ("data.memory.contextWindowSize", "=20"),
        ("data.limits.maxModelCalls", "=8"),
        ("data.response.format.type", "text"),
        ("data.response.includeAgentContext", "true"),
        ("retries", "1"),
    ]
    collaboration = Collab("A2AClientConversation", "A2A client conversation")
    collaboration.add(p, "A2A client agent")
    return collaboration.xml(), forms, http, ai_subprocess
