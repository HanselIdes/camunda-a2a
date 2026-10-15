"""The agent path of the a2a-task process: an AI Agent ad-hoc sub-process with three basic tools.

The tools are the single source of the Agent Card skills (see tools/gen_card.py): each tool's name,
documentation, `a2a:tags` and `a2a:examples` properties and fromAi() parameters become a skill.
"""
from lib import q
from feel import one, TS

AGENT = "io.camunda.connectors.agenticai.ai-agent-subprocess.v2"
AGENT_PROMPT = (
    '="You are a helpful assistant exposed through the A2A protocol. Answer the user concisely in plain text. '
    'Use the available tools whenever they help. If you cannot answer without more information from the user, '
    'start your reply with the exact marker NEED_INPUT: followed by your question, and call no tool."')
USER_PROMPT = ('=string join(for part in req.message.parts return if part.text != null then part.text else "", " ")')


def tool_ext(tags, examples, io="", script=""):
    props = ('<zeebe:properties><zeebe:property name="a2a:tags" value=%s />'
             '<zeebe:property name="a2a:examples" value=%s /></zeebe:properties>' % (q(tags), q(examples)))
    return props + io + script


def add_agent(p, A):
    """Adds the agent elements to process p inside scope A and returns nothing; flows are added by the caller."""
    p.xor("ModeGw", "Scripted or agent?", 1350, 275, parent=A)
    p.sub("AgentTools", "Agent with tools", 1420, 420, 720, 300, kind="adHocSubProcess", parent=A)
    p.node("scriptTask", "get_current_time", "Get current time", 1450, 500, parent="AgentTools",
           doc="Returns the current date and time in UTC. Use it whenever the user asks what time or date "
               "it is. Takes no arguments.",
           ext=tool_ext("time,clock,date", "What time is it?|What is today's date?",
                        script='<zeebe:script expression=%s resultVariable="toolCallResult" />'
                        % q('={utcTime: substring(string(now()), 1, 19) + "Z"}')))
    conv = one("""=if lower case(unit) = "celsius" then {value: round half up(degrees * 9 / 5 + 32, 1), unit: "fahrenheit"}
                  else {value: round half up((degrees - 32) * 5 / 9, 1), unit: "celsius"}""")
    p.node("scriptTask", "convert_temperature", "Convert temperature", 1600, 500, parent="AgentTools",
           doc="Converts a temperature between Celsius and Fahrenheit. Use it when the user gives a temperature "
               "and wants it in the other unit. Arguments: the numeric value and the unit it is given in.",
           ext=tool_ext(
               "temperature,conversion", "Convert 100 celsius to fahrenheit|What is 50 fahrenheit in celsius?",
               io='<zeebe:ioMapping><zeebe:input source=%s target="degrees" /><zeebe:input source=%s target="unit" />'
                  '</zeebe:ioMapping>'
                  % (q('=fromAi(toolCall.degrees, "The temperature value to convert", "number")'),
                     q('=fromAi(toolCall.unit, "The unit of the given value: celsius or fahrenheit", "string")')),
               script='<zeebe:script expression=%s resultVariable="toolCallResult" />' % q(conv)))
    p.node("businessRuleTask", "capital_of", "Look up capital city", 1750, 500, parent="AgentTools",
           doc="Looks up the capital city of a country. Use it when the user asks for the capital of a country. "
               "Argument: the country name in English.",
           ext=tool_ext(
               "geography,capital", "What is the capital of France?|Capital of Japan?",
               io='<zeebe:ioMapping><zeebe:input source=%s target="country" /></zeebe:ioMapping>'
                  % q('=fromAi(toolCall.country, "The country name in English", "string")'),
               script='<zeebe:calledDecision decisionId="capitals" resultVariable="toolCallResult" />'))
    p.error_codes = {"AgentFailed": "AGENT_FAILED"}
    p.boundary_error("AgentError", "Agent failed", "AgentTools", "AgentFailed", 2100, 702, parent=A)

    trace = one("""(for calls in [flatten(for m in agent.context.conversation.messages[item.role = "assistant" and item.toolCalls != null]
            return for tc in m.toolCalls return {name: tc.name, arguments: tc.arguments})] return
        if count(calls) = 0 then null else
        {artifactId: uuid(), name: "tool-trace", parts: [{data: {toolCalls: calls}}]})[1]""")
    reply = "(if agent.responseText instance of string then trim(agent.responseText) else \"The agent produced no answer.\")"
    text = one("""if starts with(%s, "NEED_INPUT:") then trim(substring(%s, 12)) else %s""" % (reply, reply, reply))
    state = one("""if starts with(%s, "NEED_INPUT:") then "TASK_STATE_INPUT_REQUIRED"
        else "TASK_STATE_COMPLETED" """ % reply)
    p.script("ApplyAgentResponse", "Apply agent response", 2200, 500, one("""=
      (for t in [%s] return for a in [%s] return for m in [{messageId: uuid(), contextId: task.contextId,
          taskId: task.id, role: "ROLE_AGENT", parts: [{text: t}]}] return
        {id: task.id, contextId: task.contextId,
         status: {state: %s, message: m, timestamp: %s},
         artifacts: if a = null then task.artifacts else append(task.artifacts[item.name != "tool-trace"], a),
         history: append(task.history, m)})[1][1][1]""" % (text, trace, state, TS)), "task", parent=A)
    p.script("MarkAgentFailed", "Mark task failed", 2200, 640, one("""=
      (for m in [{messageId: uuid(), contextId: task.contextId, taskId: task.id, role: "ROLE_AGENT",
          parts: [{text: "The agent could not complete the request."}]}] return
        {id: task.id, contextId: task.contextId,
         status: {state: "TASK_STATE_FAILED", message: m, timestamp: %s},
         artifacts: task.artifacts, history: append(task.history, m)})[1]""" % TS), "task", parent=A)
    p.xor("WorkDone", "Work done", 1590, 275, parent=A)


def agent_settings():
    return [
        ("provider.type", "openai"), ("provider.openai.api.type", "completions"),
        ("provider.openai.backend.type", "custom"),
        ("provider.openai.backend.custom.endpoint", "{{secrets.OLLAMA_BASE_URL}}"),
        ("provider.openai.model.model", "{{secrets.OLLAMA_MODEL}}"),
        ("provider.openai.timeouts.timeout", "PT180S"),
        ("provider.openai.api.completions.temperature", "=0"),
        ("data.systemPrompt.prompt", AGENT_PROMPT), ("data.userPrompt.prompt", USER_PROMPT),
        ("data.limits.maxModelCalls", "=8"),
        ("data.response.format.type", "text"),
        ("data.response.includeAgentContext", "true"),
        ("errorExpression",
         '=if error != null then bpmnError("AGENT_FAILED", string(error.message)) else null'),
        ("retries", "0"),
    ]
