#!/usr/bin/env python3
"""Generates bpmn/*.bpmn and dmn/*.dmn, then applies connector element templates with c8ctl.

Run from the repo root:  python3 tools/bpmn_gen/build.py
The BPMN and DMN files are the source of truth once generated; this script documents how they
were produced and regenerates them, so edit either the script or the files, not both.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import Proc, q  # noqa: E402
import dmn  # noqa: E402
import feel  # noqa: E402
from agent import AGENT, add_agent, agent_settings  # noqa: E402
from feel import one, nn, TS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HTTP = "io.camunda.connectors.HttpJson.v2"
HOOK = "io.camunda.connectors.webhook.WebhookConnector.v1"


def write(path, content):
    with open(os.path.join(ROOT, path), "w") as f:
        f.write(content)


def apply(path, template, element, sets):
    cmd = ["c8ctl", "element-template", "apply", "-i", template, element, os.path.join(ROOT, path)]
    for k, v in sets:
        cmd += ["--set", "%s=%s" % (k, v)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit("template apply failed for %s/%s" % (path, element))


def http(path, element, url, body, error=None, method="POST"):
    sets = [("method", method), ("url", '="{{secrets.ENGINE_URL}}%s"' % url),
            ("body", body), ("ignoreNullValues", "true"), ("resultExpression", "={}")]
    if error:
        sets.append(("errorExpression", error))
    apply(path, HTTP, element, sets)


# ---------------------------------------------------------------------------------------------
def publish_reply():
    p = Proc("a2a-publish-reply", "A2A publish reply")
    p.start("ReplyReady", "Reply ready", 150, 102)
    p.node("serviceTask", "PublishReply", "Publish reply", 250, 80)
    p.end("ReplyPublished", "Reply published", 420, 102)
    p.flow("ReplyReady", "PublishReply")
    p.flow("PublishReply", "ReplyPublished")
    path = "bpmn/a2a-publish-reply.bpmn"
    write(path, p.xml())
    http(path, "PublishReply", "/v2/messages/publication",
         one('={name: "a2a-reply", correlationKey: corrId, timeToLive: 15000, '
             'variables: {replyResult: replyResult, replyError: replyError}}'))


def card_runtime():
    """A second card whose skills are read from the deployed definition of a2a-task when the card is requested."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_card
    p = Proc("a2a-card-runtime", "A2A Agent Card from the deployed agent")
    p.start("RuntimeCardRequested", "Runtime Agent Card requested", 150, 102)
    p.node("serviceTask", "FindAgentDefinition", "Find agent definition", 250, 80)
    p.node("serviceTask", "ReadAgentDefinition", "Read agent definition XML", 410, 80)
    p.script("BuildRuntimeCard", "Build Agent Card from XML", 570, 80,
             gen_card.card_expression([], skills_expr=feel.runtime_skills()), "card")
    p.end("RuntimeCardReady", "Agent Card ready", 730, 102)
    p.flow("RuntimeCardRequested", "FindAgentDefinition")
    p.flow("FindAgentDefinition", "ReadAgentDefinition")
    p.flow("ReadAgentDefinition", "BuildRuntimeCard")
    p.flow("BuildRuntimeCard", "RuntimeCardReady")
    path = "bpmn/a2a-card-runtime.bpmn"
    write(path, p.xml())
    http(path, "FindAgentDefinition", "/v2/process-definitions/search",
         '={filter: {processDefinitionId: "a2a-task", isLatestVersion: true}}')
    apply(path, HTTP, "FindAgentDefinition", [
        ("resultExpression", '={definitionKey: string(response.body.items[1].processDefinitionKey)}')])
    http(path, "ReadAgentDefinition", "/v2/process-definitions/", "=null", method="GET")
    apply(path, HTTP, "ReadAgentDefinition", [
        ("url", '="{{secrets.ENGINE_URL}}/v2/process-definitions/" + definitionKey + "/xml"'),
        ("documentReturnFormat.choice", "TEXT"), ("resultExpression", "={xml: response.body}")])
    apply(path, HOOK, "RuntimeCardRequested", [
        ("inbound.context", "a2a-card-runtime"), ("inbound.method", "get"), ("synchronousResponse", "true"),
        ("resultExpression", "={}"),
        ("inbound.responseExpression", one("""={statusCode: 200, headers: {"Content-Type": "application/json"},
          body: context merge([correlation.variables.card, {supportedInterfaces: [{url: "{{secrets.A2A_PUBLIC_URL}}/a2a",
          protocolBinding: "JSONRPC", protocolVersion: "1.0"}]}])}"""))])


def push_notify():
    p = Proc("a2a-push-notify", "A2A push notification delivery")
    p.error_codes = {"PushFailed": "PUSH_FAILED"}
    p.start("NotificationRequested", "Push delivery requested", 150, 182)
    mi = ('<bpmn:multiInstanceLoopCharacteristics><bpmn:extensionElements>'
          '<zeebe:loopCharacteristics inputCollection="=configs" inputElement="config" />'
          '</bpmn:extensionElements></bpmn:multiInstanceLoopCharacteristics>')
    p.sub("DeliverEach", "Deliver to each destination", 250, 60, 520, 260, inner=mi)
    p.start("DeliveryStarted", "Delivery started", 290, 182, parent="DeliverEach")
    p.node("serviceTask", "DeliverNotification", "Deliver notification", 370, 160, parent="DeliverEach")
    p.end("NotificationDelivered", "Notification delivered", 530, 182, parent="DeliverEach")
    p.boundary_error("DeliveryFailed", "Delivery failed", "DeliverNotification", "PushFailed", 402, 222, parent="DeliverEach")
    p.end("DeliveryGivenUp", "Delivery given up", 530, 262, parent="DeliverEach")
    p.end("DeliveriesAttempted", "Deliveries attempted", 860, 182)
    p.flow("NotificationRequested", "DeliverEach")
    p.flow("DeliveryStarted", "DeliverNotification")
    p.flow("DeliverNotification", "NotificationDelivered")
    p.flow("DeliveryFailed", "DeliveryGivenUp")
    p.flow("DeliverEach", "DeliveriesAttempted")
    path = "bpmn/a2a-push-notify.bpmn"
    write(path, p.xml())
    apply(path, HTTP, "DeliverNotification", [
        ("method", "POST"), ("url", "=config.url"),
        ("headers", one("""=context(get entries({"Content-Type": "application/a2a+json",
          "Authorization": if config.authentication != null then config.authentication.scheme + " " + config.authentication.credentials else null,
          "X-A2A-Notification-Token": config.token})[item.value != null])""")),
        ("body", "=payload"), ("ignoreNullValues", "true"), ("retries", "2"),
        ("errorExpression", '=if error != null then bpmnError("PUSH_FAILED", string(error.message)) else null')])


def fetch_task():
    p = Proc("a2a-fetch-task", "A2A fetch one task")
    p.msg("Msg_fetch_reply", "a2a-reply", "=corrId")
    p.start("FetchRequested", "Fetch requested", 150, 182)
    p.script("PrepareFetch", "Prepare fetch", 230, 160, "=uuid()", "corrId")
    p.call("CorrelateGet", "Ask the task for its state", 380, 160, "a2a-correlate",
           inputs=[("=\"a2a-get\"", "messageName"), ("=taskId", "taskId"),
                   ("={getReq: {corrId: corrId, wrap: \"bare\", historyLength: historyLength}}", "payload"), ("=2", "tries")],
           outputs=[("=correlated", "correlated")])
    p.xor("TaskReachable", "Task answered?", 540, 175)
    p.node("eventBasedGateway", "AwaitView", "Await view or timeout", 640, 175)
    p.catch_msg("ViewReceived", "View received", 750, 112, "Msg_fetch_reply")
    p.catch_timer("ViewTimeout", "View timed out", 750, 252, '="PT10S"')
    p.script("TakeView", "Take view", 840, 90, "=replyResult", "taskView")
    p.end("ViewFetched", "View fetched", 1000, 112)
    p.end("TaskGone", "Task is gone", 750, 342)
    p.end("NoAnswer", "No answer", 840, 252)
    p.flow("FetchRequested", "PrepareFetch")
    p.flow("PrepareFetch", "CorrelateGet")
    p.flow("CorrelateGet", "TaskReachable")
    p.flow("TaskReachable", "AwaitView", "yes", cond="=correlated = true")
    p.flow("TaskReachable", "TaskGone", "no", default=True, route="down-in")
    p.flow("AwaitView", "ViewReceived", route="up-in")
    p.flow("AwaitView", "ViewTimeout", route="down-in")
    p.flow("ViewReceived", "TakeView")
    p.flow("TakeView", "ViewFetched")
    p.flow("ViewTimeout", "NoAnswer")
    write("bpmn/a2a-fetch-task.bpmn", p.xml())


def correlate():
    p = Proc("a2a-correlate", "A2A correlate message to task")
    p.error_codes = {"NotFound": "NOT_FOUND"}
    p.start("CorrelateRequested", "Correlation requested", 150, 102)
    p.script("ResetAttempts", "Reset attempts", 230, 80, "=0", "attempt")
    p.xor("TryJoin", "Try correlation", 360, 95)
    p.node("serviceTask", "CorrelateMessage", "Correlate message", 460, 80)
    p.script("MarkCorrelated", "Mark correlated", 620, 80, "=true", "correlated")
    p.end("Correlated", "Correlated", 780, 102)
    p.boundary_error("NoSubscription", "No subscription yet", "CorrelateMessage", "NotFound", 492, 142)
    p.script("CountAttempt", "Count attempt", 460, 230, "=attempt + 1", "attempt")
    p.xor("AttemptsLeft", "Attempts left?", 620, 245)
    p.catch_timer("WaitBeforeRetry", "Wait before retry", 720, 252, '="PT0.3S"')
    p.script("MarkNotCorrelated", "Mark not correlated", 595, 350, "=false", "correlated")
    p.end("NotCorrelated", "Not correlated", 780, 372)
    p.flow("CorrelateRequested", "ResetAttempts")
    p.flow("ResetAttempts", "TryJoin")
    p.flow("TryJoin", "CorrelateMessage")
    p.flow("CorrelateMessage", "MarkCorrelated")
    p.flow("MarkCorrelated", "Correlated")
    p.flow("NoSubscription", "CountAttempt")
    p.flow("CountAttempt", "AttemptsLeft")
    p.flow("AttemptsLeft", "WaitBeforeRetry", "yes", cond="=attempt < tries")
    p.flow("AttemptsLeft", "MarkNotCorrelated", "no", default=True, route="down-in")
    p.flow("WaitBeforeRetry", "TryJoin", route="over:70")
    p.flow("MarkNotCorrelated", "NotCorrelated")
    path = "bpmn/a2a-correlate.bpmn"
    write(path, p.xml())
    http(path, "CorrelateMessage", "/v2/messages/correlation",
         "={name: messageName, correlationKey: taskId, variables: payload}",
         error='=if string(error.code) = "404" then bpmnError("NOT_FOUND", "no message subscription") else null')


# ---------------------------------------------------------------------------------------------
def handler():
    p = Proc("a2a-rpc", "A2A JSON-RPC handler")
    p.msg("Msg_reply", "a2a-reply", "=lookup.corrId")
    p.start("RpcReceived", "A2A request received", 150, 282)
    p.script("ParseRequest", "Parse request", 230, 260, "=" + feel.CTX, "ctx")
    p.rule("ValidateRequest", "Validate request", 390, 260, "a2a-validate", "verdict")
    p.xor("RouteRequest", "Route request", 550, 275)
    # error / list / direct message
    p.script("BuildValidationError", "Build validation error", 680, 20,
             "=" + feel.error_response("verdict"), "rpcResponse")
    p.end("ValidationErrorReady", "Error response ready", 840, 42)
    p.script("PrepareList", "Prepare task list", 680, 140, "=" + feel.list_request(), "listReq")
    p.node("serviceTask", "SearchTasks", "Search task instances", 830, 140)
    p.xor("AnyTasks", "Any tasks found?", 990, 155)
    p.call("FetchTasks", "Fetch each task", 1090, 140, "a2a-fetch-task",
           inputs=[("=taskIdItem", "taskId"), ("=ctx.hl", "historyLength")],
           outputs=[("=if is defined(taskView) then taskView else null", "taskView")])
    p.nodes["FetchTasks"].inner = ('<bpmn:multiInstanceLoopCharacteristics><bpmn:extensionElements>'
                                   '<zeebe:loopCharacteristics inputCollection="=taskIds" inputElement="taskIdItem" '
                                   'outputCollection="taskViews" outputElement="=if is defined(taskView) then taskView else null" />'
                                   '</bpmn:extensionElements></bpmn:multiInstanceLoopCharacteristics>')
    p.xor("ListJoin", "Tasks collected", 1250, 155)
    p.script("BuildTaskList", "Build task list", 1340, 140, "=" + feel.list_response(), "rpcResponse")
    p.end("TaskListReady", "Task list ready", 1500, 162)
    p.script("BuildDirectMessage", "Build direct message response", 680, 260,
             one('''={jsonrpc: "2.0", id: ctx.id, result: {message: {messageId: uuid(),
              contextId: if ctx.contextId != null then ctx.contextId else uuid(), role: "ROLE_AGENT",
              parts: [{text: "Direct message response"}]}}}'''), "rpcResponse")
    p.end("DirectMessageReady", "Message response ready", 840, 282)
    # new task
    p.script("PrepareNewTask", "Prepare new task", 680, 380,
             one("""=(for cid in [if ctx.contextId != null then ctx.contextId else uuid()] return
              for s in [replace(cid, "[^A-Za-z0-9_:.-]", "_")] return
              {corrId: uuid(), phase: "main", taskId: uuid(), contextId: cid, wrap: "task",
               ctxTag: "ctx-" + (if string length(s) > 90 then substring(s, 1, 90) else s)})[1][1]"""), "lookup")
    p.node("serviceTask", "CreateTask", "Create task instance", 830, 380)
    # follow-up / get / cancel
    p.script("PrepareLookup", "Prepare lookup", 680, 500, one("""=
      (for c in [uuid()] return
       if ctx.method = "GetTask" then {corrId: c, phase: "main", msgName: "a2a-get", taskId: ctx.ref, tries: 3,
          payload: {getReq: nn_get}}
       else if ctx.method = "CancelTask" then {corrId: c, phase: "main", msgName: "a2a-cancel", taskId: ctx.ref, tries: 3,
          payload: {cancelReq: {corrId: c, wrap: "bare"}}}
       else if list contains(ctx.pushMethods, ctx.method) then {corrId: c, phase: "main", msgName: "a2a-push",
          taskId: ctx.ref, tries: 3, payload: {pushReq: nn_push}}
       else {corrId: c, phase: "main", msgName: "a2a-send", taskId: ctx.taskId, tries: 3,
          payload: {sendReq: nn_send}})[1]""".replace(
        "nn_get", nn('{corrId: c, wrap: "bare", historyLength: ctx.hl}')).replace(
        "nn_send", nn('{corrId: c, wrap: "task", message: ctx.m, historyLength: ctx.hl}')).replace(
        "nn_push", nn('{corrId: c, wrap: "bare", op: ctx.method, configId: ctx.p.id, config: ctx.pushCfg, pageSize: ctx.pageSize}'))), "lookup")
    p.xor("CorrelateJoin", "Correlate", 790, 515)
    p.call("CorrelateToTask", "Correlate message to task", 880, 500, "a2a-correlate",
           inputs=[("=lookup.msgName", "messageName"), ("=lookup.taskId", "taskId"),
                   ("=lookup.payload", "payload"), ("=lookup.tries", "tries")],
           outputs=[("=correlated", "correlated")])
    p.xor("WasCorrelated", "Task answered?", 1040, 515)
    p.xor("ProbeFollowUp", "Probe a follow-up?", 1140, 515)
    p.script("PrepareFollowUpProbe", "Prepare follow-up probe", 1240, 440, one("""=
      (for c in [uuid()] return {corrId: c, phase: "followProbe", msgName: "a2a-get", taskId: lookup.taskId, tries: 2,
        payload: {getReq: {corrId: c, wrap: "task"}}})[1]"""), "lookup")
    p.script("BuildNotFound", "Build task not found error", 1240, 600,
             "=" + feel.resp_from(feel.err(-32001, "Task not found", "TASK_NOT_FOUND")), "rpcResponse")
    p.end("NotFoundReady", "Not found response ready", 1400, 622)
    # waiting for the task's reply
    p.xor("WaitJoin", "Await reply", 1450, 395)
    p.node("eventBasedGateway", "AwaitReply", "Await reply or timeout", 1550, 395)
    p.catch_msg("ReplyReceived", "Reply received", 1660, 282, "Msg_reply")
    p.catch_timer("ReplyTimeout", "Reply timed out", 1660, 502,
                  '=if lookup.phase = "timeoutProbe" then "PT8S" else "PT25S"')
    p.xor("IsFollowUpProbe", "Follow-up probe?", 1760, 275)
    p.script("BuildNotWaiting", "Build not waiting error", 1860, 190,
             "=" + feel.resp_from(feel.err(-32004, "Task is not waiting for input", "UNSUPPORTED_OPERATION")),
             "rpcResponse")
    p.end("NotWaitingReady", "Not waiting response ready", 2020, 212)
    p.script("BuildResponse", "Build response", 1860, 320, one(
        '''=if is defined(replyError) and replyError != null then %s else {jsonrpc: "2.0", id: ctx.id, result: replyResult}'''
        % feel.error_response("replyError")), "rpcResponse")
    p.end("ResponseReady", "Response ready", 2020, 342)
    p.xor("AlreadyProbed", "Already probed?", 1760, 495)
    p.script("BuildTimeoutError", "Build timeout error", 1860, 420,
             "=" + feel.resp_from(feel.err(-32603, "Internal error: the task did not answer in time")),
             "rpcResponse")
    p.end("TimeoutReady", "Timeout response ready", 2020, 442)
    p.script("PrepareTimeoutProbe", "Prepare timeout probe", 1860, 560, one("""=
      (for c in [uuid()] return {corrId: c, phase: "timeoutProbe", msgName: "a2a-get", taskId: lookup.taskId, tries: 2,
        payload: {getReq: {corrId: c, wrap: if ctx.method = "SendMessage" then "task" else "bare"}}})[1]"""), "lookup")
    # flows
    p.flow("RpcReceived", "ParseRequest")
    p.flow("ParseRequest", "ValidateRequest")
    p.flow("ValidateRequest", "RouteRequest")
    p.flow("RouteRequest", "BuildValidationError", "invalid", cond='=verdict.route = "error"', route="up-in")
    p.flow("RouteRequest", "PrepareList", "list", cond='=verdict.route = "ListTasks"', route="up-in")
    p.flow("PrepareList", "SearchTasks")
    p.flow("SearchTasks", "AnyTasks")
    p.flow("AnyTasks", "FetchTasks", "tasks", cond="=count(taskIds) > 0")
    p.flow("AnyTasks", "ListJoin", "none", default=True, route="over:50")
    p.flow("FetchTasks", "ListJoin")
    p.flow("ListJoin", "BuildTaskList")
    p.flow("RouteRequest", "BuildDirectMessage", "direct message",
           cond='=verdict.route = "SendMessage" and ctx.messageId != null and starts with(ctx.messageId, "tck-message-response")')
    p.flow("RouteRequest", "PrepareNewTask", "new task",
           cond='=verdict.route = "SendMessage" and ctx.taskId = null and not(starts with(ctx.messageId, "tck-message-response"))', route="down-in")
    p.flow("RouteRequest", "PrepareLookup", "follow-up, get, cancel", default=True, route="down-in")
    p.flow("BuildValidationError", "ValidationErrorReady")
    p.flow("BuildTaskList", "TaskListReady")
    p.flow("BuildDirectMessage", "DirectMessageReady")
    p.flow("PrepareNewTask", "CreateTask")
    p.flow("CreateTask", "WaitJoin")
    p.flow("PrepareLookup", "CorrelateJoin")
    p.flow("CorrelateJoin", "CorrelateToTask")
    p.flow("CorrelateToTask", "WasCorrelated")
    p.flow("WasCorrelated", "WaitJoin", "yes", cond="=correlated = true", route="up-in")
    p.flow("WasCorrelated", "ProbeFollowUp", "no", default=True)
    p.flow("ProbeFollowUp", "PrepareFollowUpProbe", "yes",
           cond='=ctx.method = "SendMessage" and lookup.phase = "main"', route="up-in")
    p.flow("ProbeFollowUp", "BuildNotFound", "no", default=True, route="down-in")
    p.flow("PrepareFollowUpProbe", "CorrelateJoin", route="back:200")
    p.flow("BuildNotFound", "NotFoundReady")
    p.flow("WaitJoin", "AwaitReply")
    p.flow("AwaitReply", "ReplyReceived", route="up-in")
    p.flow("AwaitReply", "ReplyTimeout", route="down-in")
    p.flow("ReplyReceived", "IsFollowUpProbe")
    p.flow("IsFollowUpProbe", "BuildNotWaiting", "yes", cond='=lookup.phase = "followProbe"', route="up-in")
    p.flow("IsFollowUpProbe", "BuildResponse", "no", default=True, route="down-in")
    p.flow("BuildNotWaiting", "NotWaitingReady")
    p.flow("BuildResponse", "ResponseReady")
    p.flow("ReplyTimeout", "AlreadyProbed")
    p.flow("AlreadyProbed", "BuildTimeoutError", "yes", cond='=lookup.phase = "timeoutProbe"', route="up-in")
    p.flow("AlreadyProbed", "PrepareTimeoutProbe", "no", default=True, route="down-in")
    p.flow("BuildTimeoutError", "TimeoutReady")
    p.flow("PrepareTimeoutProbe", "CorrelateJoin", route="back:320")
    # Read the push switch. Webhook result expressions do not resolve secrets, but outbound connector jobs do, so a
    # push method first asks the engine to evaluate a FEEL string that contains the secret.
    for n in p.nodes.values():
        if n.x >= 230:
            n.x += 280
    p.xor("IsPushMethod", "Push method?", 240, 275)
    p.node("serviceTask", "ReadPushSetting", "Read push setting", 330, 150)
    p.xor("PushSettingKnown", "Push setting known", 440, 275)
    p.flow("RpcReceived", "IsPushMethod")
    p.remove_flow("RpcReceived", "ParseRequest")
    p.flow("IsPushMethod", "ReadPushSetting", "push method", route="up-in", cond=one(
        '''=rpc instance of context and rpc.method instance of string and list contains(["CreateTaskPushNotificationConfig",
        "GetTaskPushNotificationConfig", "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig"], rpc.method)'''))
    p.flow("IsPushMethod", "PushSettingKnown", "other", default=True)
    p.flow("ReadPushSetting", "PushSettingKnown", route="down-in")
    p.flow("PushSettingKnown", "ParseRequest")
    path = "bpmn/a2a-rpc.bpmn"
    write(path, p.xml())
    http(path, "ReadPushSetting", "/v2/expression/evaluation",
         '={expression: "=\\"{{secrets.A2A_PUSH_ENABLED}}\\""}')
    http(path, "SearchTasks", "/v2/process-instances/search", one("""={filter: {processDefinitionId: "a2a-task",
        state: "ACTIVE", tags: if listReq.ctxTag != null then ["a2a", listReq.ctxTag] else ["a2a"]},
        sort: [{field: "startDate", order: "DESC"}], page: {limit: 100}}"""))
    apply(path, HTTP, "SearchTasks", [("resultExpression", one("""={taskIds: for i in response.body.items return
        (for t in i.tags[starts with(item, "task-")] return substring(t, 6))[1]}"""))])
    apply(path, HTTP, "ReadPushSetting", [("resultExpression", '={pushEnabled: response.body.result = "true"}')])
    apply(path, HOOK, "RpcReceived", [
        ("inbound.context", "a2a"), ("inbound.method", "post"), ("synchronousResponse", "true"),
        ("resultExpression", "={rpc: request.body, hdr: request.headers}"),
        ("inbound.responseExpression",
         '={statusCode: 200, headers: {"Content-Type": "application/json"}, body: correlation.variables.rpcResponse}')])
    tags = '["a2a", "task-" + lookup.taskId, lookup.ctxTag]'
    http(path, "CreateTask", "/v2/process-instances", one("""={processDefinitionId: "a2a-task",
        variables: {taskId: lookup.taskId, contextId: lookup.contextId,
        req: {corrId: lookup.corrId, blocking: ctx.blocking, hl: ctx.hl,
          message: ctx.m, wrap: "task", pushConfig: ctx.taskPush}}, tags: %s}""" % tags))


def card_proc():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_card
    skills = gen_card.skills_from_bpmn()
    feel_quote = gen_card.feel_str
    p = Proc("a2a-card", "A2A Agent Card")
    p.start("CardRequested", "Agent Card requested", 150, 102)
    p.script("BuildCard", "Build Agent Card", 250, 80,
             gen_card.card_expression(skills), "card")
    p.end("CardReady", "Agent Card ready", 420, 102)
    p.flow("CardRequested", "BuildCard")
    p.flow("BuildCard", "CardReady")
    path = "bpmn/a2a-card.bpmn"
    write(path, p.xml())
    apply(path, HOOK, "CardRequested", [
        ("inbound.context", "a2a-card"), ("inbound.method", "get"), ("synchronousResponse", "true"),
        ("resultExpression", "={}"),
        ("inbound.responseExpression", one("""={statusCode: 200, headers: {"Content-Type": "application/json",
          "Cache-Control": "public, max-age=300", "ETag": %s, "Last-Modified": "%s"},
          body: context merge([correlation.variables.card, {supportedInterfaces: [{url: "{{secrets.A2A_PUBLIC_URL}}/a2a",
          protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
          capabilities: {streaming: false, pushNotifications: "{{secrets.A2A_PUSH_ENABLED}}" = "true",
          extendedAgentCard: false}}])}""" % (
              feel_quote(gen_card.card_etag(skills)), gen_card.CARD_LAST_MODIFIED)))])


# ---------------------------------------------------------------------------------------------
CLASSIFY_IN = [("Message id", "req.message.messageId", "string")]


def decisions():
    prefix = lambda s: 'starts with(?, "%s")' % s  # noqa: E731
    rules = [
        ("TCK: stay input-required", [prefix("tck-input-required")],
         ['"TASK_STATE_INPUT_REQUIRED"', "null", "null", "false", '"tck"']),
        ("TCK: file artifact by url", [prefix("tck-artifact-file-url")],
         ['"TASK_STATE_COMPLETED"', "null", '"file-url"', "false", '"tck"']),
        ("TCK: file artifact", [prefix("tck-artifact-file")],
         ['"TASK_STATE_COMPLETED"', "null", '"file"', "false", '"tck"']),
        ("TCK: text artifact", [prefix("tck-artifact-text")],
         ['"TASK_STATE_COMPLETED"', "null", '"text"', "false", '"tck"']),
        ("TCK: data artifact", [prefix("tck-artifact-data")],
         ['"TASK_STATE_COMPLETED"', "null", '"data"', "false", '"tck"']),
        ("TCK: complete the task", [prefix("tck-complete-task")],
         ['"TASK_STATE_COMPLETED"', '"Hello from TCK"', "null", "false", '"tck"']),
        ("TCK: any other tck- id echoes and completes", [prefix("tck-")],
         ['"TASK_STATE_COMPLETED"', "null", "null", "true", '"tck"']),
        ("Everything else goes to the agent", ["-"],
         ["null", "null", "null", "false", '"agent"']),
    ]
    write("dmn/a2a-classify.dmn", dmn.table(
        "a2a-classify", "Classify A2A message", CLASSIFY_IN,
        [("state", "State", "string"), ("statusText", "Status text", "string"),
         ("artifact", "Artifact", "string"), ("echo", "Echo", "boolean"), ("route", "Route", "string")],
        rules))

    caps = [("france", "Paris"), ("germany", "Berlin"), ("japan", "Tokyo"), ("italy", "Rome"), ("spain", "Madrid"),
            ("canada", "Ottawa"), ("brazil", "Brasilia"), ("australia", "Canberra"), ("egypt", "Cairo"),
            ("india", "New Delhi"), ("sweden", "Stockholm"), ("norway", "Oslo")]
    write("dmn/capitals.dmn", dmn.table(
        "capitals", "Capital city of a country", [("Country", "lower case(country)", "string")],
        [("capital", "Capital", "string")],
        [("", ['"%s"' % c], ['"%s"' % cap]) for c, cap in caps] +
        [("Unknown country", ["-"], ['"unknown"'])]))

    t, f = "true", "false"
    streaming = '"SendStreamingMessage","SubscribeToTask"'
    push = ('"CreateTaskPushNotificationConfig","GetTaskPushNotificationConfig",'
            '"ListTaskPushNotificationConfigs","DeleteTaskPushNotificationConfig"')
    known = '"SendMessage","GetTask","ListTasks","CancelTask",' + push
    cols = ["-"] * 8

    def row(desc, over, out):
        ins = list(cols)
        for i, v in over.items():
            ins[i] = v
        return (desc, ins, out)
    vrules = [
        row("Unsupported A2A-Version", {0: f},
            ['"error"', "-32009", '"VERSION_NOT_SUPPORTED"', '"Unsupported A2A-Version"']),
        row("Content-Type is not application/json", {1: f},
            ['"error"', "-32005", '"CONTENT_TYPE_NOT_SUPPORTED"', '"Content-Type must be application/json"']),
        row("Not a JSON-RPC 2.0 request", {2: f}, ['"error"', "-32600", "null", '"Invalid Request"']),
        row("Streaming is not supported", {3: streaming},
            ['"error"', "-32004", '"UNSUPPORTED_OPERATION"', '"Streaming is not supported"']),
        row("Extended agent card is not supported", {3: '"GetExtendedAgentCard"'},
            ['"error"', "-32004", '"UNSUPPORTED_OPERATION"', '"Extended agent card is not supported"']),
        row("Push notifications are not supported", {3: push, 7: f},
            ['"error"', "-32003", '"PUSH_NOTIFICATION_NOT_SUPPORTED"', '"Push notifications are not supported"']),
        row("Unknown method", {3: "not(%s)" % known}, ['"error"', "-32601", "null", '"Method not found"']),
        row("SendMessage without a valid message", {3: '"SendMessage"', 4: f},
            ['"error"', "-32602", "null", '"Invalid params: message with messageId, role and parts is required"']),
        row("SendMessage with an unsupported part media type", {3: '"SendMessage"', 5: f},
            ['"error"', "-32005", '"CONTENT_TYPE_NOT_SUPPORTED"', '"Unsupported media type in message part"']),
        row("A task id is required", {3: '"GetTask","CancelTask",' + push, 6: f},
            ['"error"', "-32602", "null", '"Invalid params: id is required"']),
        row("Valid request", {}, ["ctx.method", "null", "null", "null"]),
    ]
    write("dmn/a2a-validate.dmn", dmn.table(
        "a2a-validate", "Validate A2A request",
        [("A2A-Version accepted", "ctx.versionOk", "boolean"),
         ("Content-Type accepted", "ctx.contentTypeOk", "boolean"),
         ("JSON-RPC 2.0 request", "ctx.jsonrpcOk", "boolean"),
         ("Method", "ctx.method", "string"),
         ("Message valid", "ctx.msgOk", "boolean"),
         ("Media types supported", "ctx.mediaOk", "boolean"),
         ("Task id present", "ctx.idOk", "boolean"),
         ("Push notifications enabled", "ctx.pushEnabled", "boolean")],
        [("route", "Route", "string"), ("code", "Error code", "number"),
         ("reason", "Error reason", "string"), ("message", "Error message", "string")],
        vrules))


# ---------------------------------------------------------------------------------------------
def task():
    p = Proc("a2a-task", "A2A task")
    p.msg("Msg_get", "a2a-get", "=taskId")
    p.msg("Msg_cancel", "a2a-cancel", "=taskId")
    p.msg("Msg_send", "a2a-send", "=taskId")
    pub = lambda corr, res, errv: [("=" + corr, "corrId"), ("=" + res, "replyResult"), ("=" + errv, "replyError")]  # noqa: E731

    p.start("TaskSubmitted", "Task submitted", 150, 282)
    p.script("CreateTaskState", "Create task", 230, 260, one("""=
      {id: taskId, contextId: contextId, status: {state: "TASK_STATE_SUBMITTED", timestamp: %s}, artifacts: [],
       history: [put(put(req.message, "taskId", taskId), "contextId", contextId)]}""" % TS), "task")
    p.script("InitPushConfigs", "Store push notification config", 360, 260, one("""=
      if req.pushConfig = null then [] else [put(put(req.pushConfig, "taskId", taskId), "id",
        if req.pushConfig.id != null then req.pushConfig.id else uuid())]"""), "pushConfigs")
    p.script("SetPending", "Set reply pending", 490, 260, "=req.blocking", "pending")
    p.xor("ReturnImmediately", "Return immediately?", 620, 275)
    p.script("BuildInitialReply", "Build initial reply", 700, 120, "=" + feel.wrapped("req.hl", '"task"'), "initialReply")
    p.call("PublishInitialReply", "Publish initial reply", 840, 120, "a2a-publish-reply",
           inputs=pub("req.corrId", "initialReply", "null"))
    p.xor("InitDone", "Task initialised", 970, 275)

    # --- Active scope ------------------------------------------------------------------------
    A = "Active"
    p.sub(A, "Process task", 1010, 20, 2260, 1100)
    p.start("MessageAccepted", "Message accepted", 1050, 282, parent=A)
    p.xor("ClassifyJoin", "Classify next message", 1120, 275, parent=A)
    p.rule("ClassifyMessage", "Classify message", 1210, 260, "a2a-classify", "sc", parent=A)
    msg = one("""if sc.statusText != null then {messageId: uuid(), contextId: task.contextId, taskId: task.id,
        role: "ROLE_AGENT", parts: [{text: sc.statusText}]}
      else if sc.echo then {messageId: uuid(), contextId: task.contextId, taskId: task.id, role: "ROLE_AGENT",
        parts: [{text: "Unhandled messageId prefix: " + req.message.messageId}]} else null""")
    art = one("""if sc.artifact = null then null else {artifactId: uuid(), name: "output", parts:
        if sc.artifact = "text" then [{text: "Generated text content"}]
        else if sc.artifact = "file" then [{raw: "dGNr", mediaType: "text/plain", filename: "output.txt"}]
        else if sc.artifact = "file-url" then [{url: "https://example.com/output.txt", mediaType: "text/plain", filename: "output.txt"}]
        else [{data: {key: "value", count: 42}}]}""")
    p.script("ApplyScenario", "Apply scenario", 1440, 260, one("""=
      (for m in [%s] return for a in [%s] return
        {id: task.id, contextId: task.contextId,
         status: %s,
         artifacts: if a = null then task.artifacts else append(task.artifacts, a),
         history: if m != null then append(task.history, m) else task.history})[1][1]"""
        % (msg, art, nn('{state: sc.state, message: m, timestamp: %s}' % TS))), "task", parent=A)
    p.xor("IsPending", "Reply pending?", 1690, 275, parent=A)
    p.script("BuildReply", "Build reply", 1780, 140, "=" + feel.wrapped("req.hl", '"task"'), "workReply", parent=A)
    p.call("PublishReply", "Publish reply", 1920, 140, "a2a-publish-reply",
           inputs=pub("req.corrId", "workReply", "null"), parent=A)
    p.script("MarkReplied", "Mark replied", 2060, 140, "=false", "pending", parent=A)
    p.xor("ReplyHandled", "Reply handled", 2200, 275, parent=A)
    p.xor("InputRequired", "Input required?", 2290, 275, parent=A)
    p.end("WorkFinished", "Work finished", 2410, 282, parent=A)
    p.xor("FollowJoin", "Await follow-up", 2350, 435, parent=A)
    p.catch_msg("FollowUpArrives", "Follow-up arrives", 2430, 442, "Msg_send", parent=A,
                ext='<zeebe:ioMapping><zeebe:output source="=sendReq" target="followReq" /></zeebe:ioMapping>')
    p.xor("ContextMatches", "Context matches?", 2530, 435, parent=A)
    p.script("BuildContextMismatch", "Build context mismatch error", 2630, 560, "=" + feel.err(-32602,
             "contextId does not match the task"), "mismatchError", parent=A)
    p.call("PublishMismatch", "Publish mismatch error", 2790, 560, "a2a-publish-reply",
           inputs=pub("followReq.corrId", "null", "mismatchError"), parent=A)
    p.script("RecordUserMessage", "Record user message", 2640, 380, one("""=
      {id: task.id, contextId: task.contextId,
       status: {state: "TASK_STATE_WORKING", timestamp: %s}, artifacts: task.artifacts,
       history: append(task.history, put(put(followReq.message, "taskId", task.id), "contextId", task.contextId))}""" % TS),
             "task", parent=A)
    p.script("SetRequest", "Set current request", 2780, 380,
             "={corrId: followReq.corrId, blocking: true, hl: followReq.historyLength, message: followReq.message, wrap: \"task\"}",
             "req", parent=A)
    p.script("SetPendingAgain", "Set reply pending again", 2920, 380, "=true", "pending", parent=A)
    add_agent(p, A)
    # event sub-process: GetTask while active
    G = "ActiveGet"
    p.sub(G, "Answer GetTask", 1050, 800, 560, 220, parent=A, attrs='triggeredByEvent="true"')
    p.msg_start("GetWhileActive", "GetTask while active", 1090, 882, "Msg_get", False, parent=G)
    p.script("BuildActiveView", "Build task view", 1170, 860, "=" + feel.wrapped("getReq.historyLength", "getReq.wrap"),
             "getView", parent=G)
    p.call("PublishActiveView", "Publish task view", 1330, 860, "a2a-publish-reply",
           inputs=pub("getReq.corrId", "getView", "null"), parent=G)
    p.end("ActiveViewPublished", "View published", 1490, 882, parent=G)
    p.flow("GetWhileActive", "BuildActiveView")
    p.flow("BuildActiveView", "PublishActiveView")
    p.flow("PublishActiveView", "ActiveViewPublished")
    # event sub-process: CancelTask while active
    C = "ActiveCancel"
    p.sub(C, "Cancel task", 1690, 800, 760, 220, parent=A, attrs='triggeredByEvent="true"')
    p.msg_start("CancelWhileActive", "CancelTask while active", 1730, 882, "Msg_cancel", True, parent=C)
    p.script("MarkCanceled", "Mark canceled", 1810, 860, one("""=
      {id: task.id, contextId: task.contextId, status: {state: "TASK_STATE_CANCELED", timestamp: %s},
       artifacts: task.artifacts, history: task.history}""" % TS), "task", parent=C)
    p.script("BuildCancelView", "Build canceled task view", 1970, 860, "=" + feel.wrapped("null", "cancelReq.wrap"),
             "cancelView", parent=C)
    p.call("PublishCancelView", "Publish canceled task", 2130, 860, "a2a-publish-reply",
           inputs=pub("cancelReq.corrId", "cancelView", "null"), parent=C)
    p.end("CancelPublished", "Cancel published", 2290, 882, parent=C)
    p.flow("CancelWhileActive", "MarkCanceled")
    p.flow("MarkCanceled", "BuildCancelView")
    p.flow("BuildCancelView", "PublishCancelView")
    p.flow("PublishCancelView", "CancelPublished")

    p.flow("MessageAccepted", "ClassifyJoin")
    p.flow("ClassifyJoin", "ClassifyMessage")
    p.flow("ClassifyMessage", "ModeGw")
    p.flow("ModeGw", "ApplyScenario", "scripted", default=True)
    p.flow("ModeGw", "MarkWorking", "agent", cond='=sc.route = "agent"', route="down-in")
    p.flow("MarkWorking", "AgentTools", route="down-in")
    p.flow("ApplyScenario", "WorkDone")
    p.flow("AgentTools", "ApplyAgentResponse")
    p.flow("AgentError", "MarkAgentFailed")
    p.flow("ApplyAgentResponse", "WorkDone", route="back:150")
    p.flow("MarkAgentFailed", "WorkDone", route="back:230")
    p.flow("WorkDone", "IsPending")
    p.flow("IsPending", "BuildReply", "yes", cond="=pending = true", route="up-in")
    p.flow("IsPending", "ReplyHandled", "no", default=True)
    p.flow("BuildReply", "PublishReply")
    p.flow("PublishReply", "MarkReplied")
    p.flow("MarkReplied", "ReplyHandled", route="down-in")
    p.flow("ReplyHandled", "InputRequired")
    p.flow("InputRequired", "WorkFinished", "no", default=True)
    p.flow("InputRequired", "FollowJoin", "yes", cond='=task.status.state = "TASK_STATE_INPUT_REQUIRED"',
           route="down-in")
    p.flow("FollowJoin", "FollowUpArrives")
    p.flow("FollowUpArrives", "ContextMatches")
    p.flow("ContextMatches", "RecordUserMessage", "yes",
           cond="=followReq.message.contextId = null or followReq.message.contextId = task.contextId", route="up-in")
    p.flow("ContextMatches", "BuildContextMismatch", "no", default=True, route="down-in")
    p.flow("BuildContextMismatch", "PublishMismatch")
    p.flow("PublishMismatch", "FollowJoin", route="back:40")
    p.flow("RecordUserMessage", "SetRequest")
    p.flow("SetRequest", "SetPendingAgain")
    p.flow("SetPendingAgain", "ClassifyJoin", route="back:200")

    # init flows
    p.flow("TaskSubmitted", "CreateTaskState")
    p.flow("CreateTaskState", "InitPushConfigs")
    p.flow("InitPushConfigs", "SetPending")
    p.flow("SetPending", "ReturnImmediately")
    p.flow("ReturnImmediately", "BuildInitialReply", "yes", cond="=req.blocking = false", route="up-in")
    p.flow("ReturnImmediately", "InitDone", "no", default=True)
    p.flow("BuildInitialReply", "PublishInitialReply")
    p.flow("PublishInitialReply", "InitDone", route="down-in")
    p.flow("InitDone", A)

    # --- terminal loop ----------------------------------------------------------------------
    p.xor("TerminalJoin", "Await terminal requests", 3350, 275)
    p.node("eventBasedGateway", "AwaitTerminal", "Await requests or expiry", 3450, 275)
    p.catch_msg("TerminalGet", "GetTask in terminal state", 3560, 142, "Msg_get")
    p.script("BuildTerminalView", "Build task view", 3650, 120, "=" + feel.wrapped("getReq.historyLength", "getReq.wrap"),
             "terminalView")
    p.call("PublishTerminalView", "Publish task view", 3800, 120, "a2a-publish-reply",
           inputs=pub("getReq.corrId", "terminalView", "null"))
    p.catch_msg("TerminalCancel", "CancelTask in terminal state", 3560, 282, "Msg_cancel")
    p.script("BuildNotCancelable", "Build not cancelable error", 3650, 260,
             "=" + feel.err(-32002, "Task cannot be canceled in its current state", "TASK_NOT_CANCELABLE"), "cancelError")
    p.call("PublishNotCancelable", "Publish not cancelable error", 3800, 260, "a2a-publish-reply",
           inputs=pub("cancelReq.corrId", "null", "cancelError"))
    p.catch_msg("TerminalSend", "SendMessage in terminal state", 3560, 422, "Msg_send")
    p.script("BuildTerminalSendError", "Build terminal state error", 3650, 400,
             "=" + feel.err(-32004, "Task is in a terminal state and cannot accept messages", "UNSUPPORTED_OPERATION"),
             "sendError")
    p.call("PublishTerminalSendError", "Publish terminal state error", 3800, 400, "a2a-publish-reply",
           inputs=pub("sendReq.corrId", "null", "sendError"))
    p.catch_timer("TaskExpires", "Task expires", 3560, 562, '="PT1H"')
    p.end("TaskExpired", "Task expired", 3660, 562)
    p.flow(A, "TerminalJoin")
    p.flow("TerminalJoin", "AwaitTerminal")
    p.flow("AwaitTerminal", "TerminalGet", route="up-in")
    p.flow("AwaitTerminal", "TerminalCancel")
    p.flow("AwaitTerminal", "TerminalSend", route="down-in")
    p.flow("AwaitTerminal", "TaskExpires", route="down-in")
    p.flow("TerminalGet", "BuildTerminalView")
    p.flow("BuildTerminalView", "PublishTerminalView")
    p.flow("PublishTerminalView", "TerminalJoin", route="over:80")
    p.flow("TerminalCancel", "BuildNotCancelable")
    p.flow("BuildNotCancelable", "PublishNotCancelable")
    p.flow("PublishNotCancelable", "TerminalJoin", route="back:80")
    p.flow("TerminalSend", "BuildTerminalSendError")
    p.flow("BuildTerminalSendError", "PublishTerminalSendError")
    p.flow("PublishTerminalSendError", "TerminalJoin", route="back:140")
    p.flow("TaskExpires", "TaskExpired")
    # --- push notifications: operations, delivery trigger -------------------------------------
    for n in list(p.nodes.values()):          # (a) make room in the active scope and the terminal loop
        if n.parent == A and n.x >= 1690 and n.y < 800 and n.kind != "boundaryEvent":
            n.x += 260
        elif n.parent is None and n.x >= 3350:
            n.x += 260
    p.nodes[A].w += 260
    p.nodes[C].w = 910
    # (b) delivery trigger between "Work done" and "Reply pending?"
    p.xor("HasPush", "Push configs?", 1680, 275, parent=A)
    p.node("serviceTask", "NotifyPush", "Start push delivery", 1780, 360, parent=A)
    p.xor("PushJoin", "Push handled", 1870, 275, parent=A)
    p.remove_flow("WorkDone", "IsPending")
    p.flow("WorkDone", "HasPush")
    p.flow("HasPush", "NotifyPush", "yes", cond="=count(pushConfigs) > 0", route="down-in")
    p.flow("HasPush", "PushJoin", "no", default=True)
    p.flow("NotifyPush", "PushJoin", route="up-in")
    p.flow("PushJoin", "IsPending")
    # cancel: notify too
    p.xor("HasPushCancel", "Push configs?", 2290, 875, parent=C)
    p.node("serviceTask", "NotifyPushCancel", "Start push delivery", 2380, 860, parent=C)
    p.end("CancelNotified", "Cancel published", 2540, 882, parent=C)
    p.nodes["CancelPublished"].x, p.nodes["CancelPublished"].y = 2540, 945
    p.remove_flow("PublishCancelView", "CancelPublished")
    p.flow("PublishCancelView", "HasPushCancel")
    p.flow("HasPushCancel", "NotifyPushCancel", "yes", cond="=count(pushConfigs) > 0")
    p.flow("HasPushCancel", "CancelPublished", "no", default=True, route="down-in")
    p.flow("NotifyPushCancel", "CancelNotified")
    # (c) push configuration operations while the task is active
    PA = "ActivePush"
    p.sub(PA, "Answer push configuration operation", 2690, 800, 760, 220, parent=A, attrs='triggeredByEvent="true"')
    p.msg("Msg_push", "a2a-push", "=taskId")
    p.msg_start("PushWhileActive", "Push operation while active", 2730, 882, "Msg_push", False, parent=PA)
    p.script("ComputePushOutcome", "Compute push outcome", 2810, 860, "=" + feel.push_outcome(), "pushOutcome", parent=PA)
    p.script("UpdatePushConfigs", "Update push configs", 2950, 860, "=" + feel.push_update(), "pushConfigs", parent=PA)
    p.call("PublishPushOutcome", "Publish push outcome", 3090, 860, "a2a-publish-reply",
           inputs=pub("pushReq.corrId", "pushOutcome.result", "pushOutcome.error"), parent=PA)
    p.end("PushOutcomePublished", "Push outcome published", 3250, 882, parent=PA)
    p.flow("PushWhileActive", "ComputePushOutcome")
    p.flow("ComputePushOutcome", "UpdatePushConfigs")
    p.flow("UpdatePushConfigs", "PublishPushOutcome")
    p.flow("PublishPushOutcome", "PushOutcomePublished")
    # terminal loop: the same operations
    p.catch_msg("TerminalPush", "Push operation in terminal state", 3820, 702, "Msg_push")
    p.script("ComputeTerminalPush", "Compute push outcome", 3910, 680, "=" + feel.push_outcome(), "pushOutcome")
    p.script("UpdateTerminalPush", "Update push configs", 4050, 680, "=" + feel.push_update(), "pushConfigs")
    p.call("PublishTerminalPush", "Publish push outcome", 4190, 680, "a2a-publish-reply",
           inputs=pub("pushReq.corrId", "pushOutcome.result", "pushOutcome.error"))
    p.flow("AwaitTerminal", "TerminalPush", route="down-in")
    p.flow("TerminalPush", "ComputeTerminalPush")
    p.flow("ComputeTerminalPush", "UpdateTerminalPush")
    p.flow("UpdateTerminalPush", "PublishTerminalPush")
    p.flow("PublishTerminalPush", "TerminalJoin", route="back:260")
    # (d) shift everything that is part of the main canvas to the right of the init chain
    for n in p.nodes.values():
        if n.x >= 1000:
            n.x += 160
    write("bpmn/a2a-task.bpmn", p.xml())
    apply("bpmn/a2a-task.bpmn", AGENT, "AgentTools", agent_settings())
    notify_body = one("""={processDefinitionId: "a2a-push-notify",
        variables: {configs: pushConfigs, payload: %s}}""" % feel.wrapped("null", '"task"'))
    http("bpmn/a2a-task.bpmn", "NotifyPush", "/v2/process-instances", notify_body)
    http("bpmn/a2a-task.bpmn", "NotifyPushCancel", "/v2/process-instances", notify_body)


def main():
    os.makedirs(os.path.join(ROOT, "bpmn"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "dmn"), exist_ok=True)
    decisions()
    publish_reply()
    push_notify()
    fetch_task()
    correlate()
    handler()
    task()
    card_proc()
    card_runtime()
    print("generated")


if __name__ == "__main__":
    main()
