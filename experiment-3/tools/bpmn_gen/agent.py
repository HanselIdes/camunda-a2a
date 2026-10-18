"""The agent of bpmn/a2a-agent.bpmn: an AI Agent ad-hoc sub-process with two basic tools.

The tools are the single source of the Agent Card skills (see tools/gen_card.py): each tool's name,
documentation, `a2a:tags` and `a2a:examples` properties and fromAi() parameters become a skill.
"""
from lib import q
from feel import one

AGENT = "io.camunda.connectors.agenticai.ai-agent-subprocess.v2"
AGENT_PROMPT = (
    '="You are TaskAgent, a remote agent that A2A clients send tasks to. Answer each task from these sources, in '
    'this order:\n\n'
    '1. Your own tools. Use every tool that fits the task. Never invent a tool.\n'
    '2. The client. If the task is ambiguous, or you need information or work that your tools cannot give, start '
    'your reply with the exact marker NEED_INPUT: followed by your question, and call no tool.\n'
    '3. Your own knowledge, as a best-effort answer that you mark as such.\n\n'
    'Reply in plain text."')
USER_PROMPT = ('=string join(for part in req.message.parts return if part.text != null then part.text else "", " ")')
HTTP = "io.camunda.connectors.HttpJson.v2"


def tool_ext(tags, examples, io="", script=""):
    props = ('<zeebe:properties><zeebe:property name="a2a:tags" value=%s />'
             '<zeebe:property name="a2a:examples" value=%s /></zeebe:properties>' % (q(tags), q(examples)))
    return props + io + script


def add_tools(p, host, x, y):
    """The agent's tools, inside the ad-hoc sub-process `host`, left to right from (x, y)."""
    conv = one("""={
      celsius: if fromUnit = "fahrenheit" then (value - 32) * 5 / 9 else if fromUnit = "kelvin" then value - 273.15 else value,
      converted: if toUnit = "fahrenheit" then celsius * 9 / 5 + 32 else if toUnit = "kelvin" then celsius + 273.15 else celsius,
      result: {value: decimal(converted, 2), unit: toUnit}}.result""")
    p.node("scriptTask", "convert_temperature", "Convert temperature", x, y, parent=host,
           doc="Converts a temperature between celsius, fahrenheit and kelvin. Returns the converted value and its "
               "unit. Use it for every temperature conversion instead of calculating yourself.",
           ext=tool_ext(
               "temperature,conversion", "Convert 100 celsius to fahrenheit|What is 50 fahrenheit in kelvin?",
               io='<zeebe:ioMapping><zeebe:input source=%s target="value" /><zeebe:input source=%s target="fromUnit" />'
                  '<zeebe:input source=%s target="toUnit" /></zeebe:ioMapping>'
                  % (q('=fromAi(toolCall.value, "The temperature to convert", "number")'),
                     q('=fromAi(toolCall.fromUnit, "The unit of the value", "string", '
                       '{enum: ["celsius", "fahrenheit", "kelvin"]})'),
                     q('=fromAi(toolCall.toUnit, "The unit to convert to", "string", '
                       '{enum: ["celsius", "fahrenheit", "kelvin"]})')),
               script='<zeebe:script expression=%s resultVariable="toolCallResult" />' % q(conv)))
    p.node("serviceTask", "list_tech_devices", "Get list of all Tech Stuff", x + 150, y, parent=host,
           doc="Lists the devices (phones, laptops, tablets and similar) in a public sample catalog "
               "(api.restful-api.dev). The catalog is demo data, not a real inventory.",
           # an HTTP JSON template replaces zeebe:properties, so build.py adds them again after applying it
           ext="")


def agent_outcome(o):
    """The outcome of an agent turn as {state, text, artifacts}, read from the AI Agent result `o.agent`.
    A reply that starts with NEED_INPUT: is a question to the client; the tool calls become a tool-trace artifact."""
    reply = ('(if %s.agent.responseText instance of string then trim(%s.agent.responseText) '
             'else "The agent produced no answer.")' % (o, o))
    trace = one("""(for calls in [flatten(for m in %s.agent.context.conversation.messages[item.role = "assistant" and item.toolCalls != null]
            return for tc in m.toolCalls return {name: tc.name, arguments: tc.arguments})] return
        if count(calls) = 0 then null else
        {artifactId: uuid(), name: "tool-trace", parts: [{data: {toolCalls: calls}}]})[1]""" % o)
    return one("""(for r in [%s] return for ask in [starts with(r, "NEED_INPUT:")] return
        for t in [if ask then trim(substring(r, 12)) else r] return for a in [%s] return
        {state: if ask then "TASK_STATE_INPUT_REQUIRED" else "TASK_STATE_COMPLETED", text: t, replaceAnswer: true,
         artifacts: concatenate([{artifactId: uuid(), name: if ask then "question" else "answer", parts: [{text: t}]}],
           if a = null then [] else [a])})[1][1][1][1]""" % (reply, trace))


def agent_settings():
    return [
        ("provider.type", "openai"), ("provider.openai.api.type", "completions"),
        ("provider.openai.backend.type", "custom"),
        ("provider.openai.backend.custom.endpoint", "{{secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT}}"),
        ("provider.openai.backend.custom.authentication.type", "apiKey"),
        ("provider.openai.backend.custom.authentication.apiKey", "{{secrets.CAMUNDA_PROVIDED_LLM_API_KEY}}"),
        ("provider.openai.model.model", "{{secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL}}"),
        ("provider.openai.timeouts.timeout", "PT180S"),
        ("provider.openai.api.completions.temperature", "=0"),
        ("data.systemPrompt.prompt", AGENT_PROMPT), ("data.userPrompt.prompt", USER_PROMPT),
        # the agent keeps its context across the follow-up turns of a task: the first run has no agent yet
        ("agentContext", "=agent.context"),
        ("data.limits.maxModelCalls", "=8"),
        ("data.response.format.type", "text"),
        ("data.response.includeAgentContext", "true"),
        ("errorExpression",
         '=if error != null then bpmnError("AGENT_FAILED", string(error.message)) else null'),
        ("retries", "1"),
    ]


TECH_PROPS = ("devices,catalog", "Which tech devices are in the catalog?|List the phones you know")


def tech_devices_settings():
    return [("method", "GET"), ("url", "https://api.restful-api.dev/objects"), ("resultExpression", "={toolCallResult: response.body}"),
            ("retries", "1")]
