"""The originating process: an A2A client built from the same OOTB parts as the server.

It starts from a Tasklist start form, reads the Agent Card, sends the question with the HTTP JSON connector
(JSON-RPC SendMessage), polls GetTask while the remote task works, hands INPUT_REQUIRED questions to a person in
Tasklist and sends the answer as a follow-up on the same task, and finally shows the result in a user task.
"""
import json
import os

from lib import Proc

HTTP = "io.camunda.connectors.HttpJson.v2"
HEADERS = '={"A2A-Version": "1.0", "Content-Type": "application/json"}'
MAX_REPLIES = 100  # about three minutes of polling at two seconds


def form(fid, components):
    comps = []
    for i, c in enumerate(components):
        comps.append(dict(c, id="Field_%s_%d" % (fid.replace("-", "_"), i), layout={"row": "Row_%d" % i, "columns": None}))
    return json.dumps({"components": comps, "type": "default", "id": fid, "executionPlatform": "Camunda Cloud",
                       "executionPlatformVersion": "8.8.0", "exporter": {"name": "camunda-a2a", "version": "1"},
                       "schemaVersion": 18}, indent=2) + "\n"


def client(root, write, apply, one):
    os.makedirs(os.path.join(root, "forms"), exist_ok=True)
    write("forms/a2a-client-ask.form", form("a2a-client-ask", [
        {"type": "text", "text": "### Ask the A2A agent\n\nThe question goes to the agent through the A2A protocol "
                                 "(JSON-RPC SendMessage). The agent is a BPMN process on this same cluster."},
        {"type": "textarea", "key": "question", "label": "Question", "validate": {"required": True},
         "defaultValue": "What is the capital of Japan?"}]))
    write("forms/a2a-client-answer.form", form("a2a-client-answer", [
        {"type": "text", "text": "=\"### \" + agentName + \" needs more information\\n\\n\" + reply.text"},
        {"type": "textarea", "key": "followUp", "label": "Your answer", "validate": {"required": True}}]))
    write("forms/a2a-client-result.form", form("a2a-client-result", [{"type": "text", "text": "=resultText"}]))

    p = Proc("a2a-client", "A2A client: ask the agent")
    Y = 232
    p.start("QuestionAsked", "Question asked", 150, Y, ext='<zeebe:formDefinition formId="a2a-client-ask" />')
    p.node("serviceTask", "DiscoverAgent", "Read the Agent Card", 230, Y - 22)
    p.xor("MessageJoin", "Message to send", 390, Y - 7)
    p.script("BuildMessage", "Build message", 480, Y - 22, one("""=
        context merge([{messageId: uuid(), role: "ROLE_USER",
                        parts: [{text: if followUp != null then followUp else question}]},
                       if reply != null and reply.taskId != null then {taskId: reply.taskId, contextId: reply.contextId} else {}])"""),
             "outgoing")
    p.node("serviceTask", "SendMessage", "Send message to the agent", 630, Y - 22)
    p.xor("ReadJoin", "Reply received", 790, Y - 7)
    p.script("ReadReply", "Read the agent's reply", 880, Y - 22, one("""=
        (for r in [rpc.result] return
         for t in [if r.task != null then r.task else if r.id != null then r else null] return
         for m in [if t != null then t.status.message else r.message] return
         {state: if rpc.error != null then "RPC_ERROR" else if t != null then t.status.state else "MESSAGE",
          taskId: t.id,
          contextId: if t != null then t.contextId else m.contextId,
          text: if rpc.error != null then string(rpc.error.message)
                else string join(for part in m.parts return if part.text != null then part.text else "", " "),
          toolNames: if t.artifacts = null then [] else
                     flatten(for tr in t.artifacts[item.name = "tool-trace"] return for c in tr.parts[1].data.toolCalls return c.name),
          replies: (if reply != null then reply.replies else 0) + 1})[1][1][1]"""), "reply")
    p.xor("ReplyState", "Task state?", 1040, Y - 7)
    p.node("userTask", "AnswerAgent", "Answer the agent's question", 1140, 50,
           ext='<zeebe:userTask /><zeebe:formDefinition formId="a2a-client-answer" />')
    p.catch_timer("WaitBeforePoll", "Wait before polling", 1157, 372, '="PT2S"')
    p.node("serviceTask", "GetTask", "Ask for the task state", 1250, 350)
    p.script("BuildResult", "Build result text", 1140, Y - 22, one("""=
        "### " + (if reply.state = "TASK_STATE_COMPLETED" or reply.state = "MESSAGE" then "Answer from " + agentName
                  else if reply.state = "TASK_STATE_WORKING" or reply.state = "TASK_STATE_SUBMITTED"
                       then agentName + " did not finish in time"
                  else agentName + " did not complete the request")
        + "\\n\\n" + reply.text
        + (if count(reply.toolNames) > 0 then "\\n\\n**Tools the agent used:** " + string join(reply.toolNames, ", ") else "")
        + "\\n\\n" + (if reply.taskId != null then "A2A task `" + reply.taskId + "`, context `" + reply.contextId + "`, " else "")
        + "final state " + reply.state"""), "resultText")
    p.node("userTask", "ShowResult", "Review the result", 1290, Y - 22,
           ext='<zeebe:userTask /><zeebe:formDefinition formId="a2a-client-result" />')
    p.end("ConversationFinished", "Conversation finished", 1440, Y)

    p.flow("QuestionAsked", "DiscoverAgent")
    p.flow("DiscoverAgent", "MessageJoin")
    p.flow("MessageJoin", "BuildMessage")
    p.flow("BuildMessage", "SendMessage")
    p.flow("SendMessage", "ReadJoin")
    p.flow("ReadJoin", "ReadReply")
    p.flow("ReadReply", "ReplyState")
    p.flow("ReplyState", "AnswerAgent", "input required", route="up-in",
           cond='=reply.state = "TASK_STATE_INPUT_REQUIRED"')
    p.flow("ReplyState", "WaitBeforePoll", "still working", route="down-in",
           cond='=(reply.state = "TASK_STATE_WORKING" or reply.state = "TASK_STATE_SUBMITTED") and reply.replies < %d'
                % MAX_REPLIES)
    p.flow("ReplyState", "BuildResult", "otherwise", default=True)
    p.flow("AnswerAgent", "MessageJoin", route="over:40")
    p.flow("WaitBeforePoll", "GetTask")
    p.flow("GetTask", "ReadJoin", route="back:60")
    p.flow("BuildResult", "ShowResult")
    p.flow("ShowResult", "ConversationFinished")
    path = "bpmn/a2a-client.bpmn"
    write(path, p.xml())

    apply(path, HTTP, "DiscoverAgent", [
        ("method", "GET"), ("url", "{{secrets.A2A_AGENT_CARD_URL}}"),
        ("resultExpression", one("""={agentName: response.body.name,
            agentUrl: (response.body.supportedInterfaces[item.protocolBinding = "JSONRPC"])[1].url,
            skillNames: for s in response.body.skills return s.name}"""))])
    apply(path, HTTP, "SendMessage", [
        ("method", "POST"), ("url", "=agentUrl"), ("headers", HEADERS),
        ("body", '={jsonrpc: "2.0", id: uuid(), method: "SendMessage", params: {message: outgoing}}'),
        ("readTimeoutInSeconds", "120"), ("retries", "1"), ("resultExpression", "={rpc: response.body}")])
    apply(path, HTTP, "GetTask", [
        ("method", "POST"), ("url", "=agentUrl"), ("headers", HEADERS),
        ("body", '={jsonrpc: "2.0", id: uuid(), method: "GetTask", params: {id: reply.taskId}}'),
        ("readTimeoutInSeconds", "60"), ("retries", "1"), ("resultExpression", "={rpc: response.body}")])
