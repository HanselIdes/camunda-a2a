#!/usr/bin/env python3
"""Generates the A2A server diagrams and the DMN, then applies element templates with c8ctl.

Run from experiment-3:  python3 tools/bpmn_gen/build.py

- bpmn/a2a-agent.bpmn: what a customer models. The Agent Card and the A2A task: the AI agent with its tools,
  "Update A2A task" after each turn, and a follow-up loop while the agent needs input from the client.
- bpmn/a2a-protocol.bpmn: the A2A 1.0 JSON-RPC protocol, deployed unchanged next to the agent. The endpoint answers
  every method from engine state: it reads the task variable of the agent's process instance through the search API and
  keeps push notification configs in cluster variables. The search API lags writes by about a second, so every request
  that changes state waits until the change is visible before it answers (a2a-await).
- tck/fixture/a2a-tck-fixture.bpmn and tck/fixture/a2a-classify.dmn: a scripted stand-in for the agent with the same
  contract, deployed only for the TCK runs (the secret A2A_AGENT_PROCESS selects the process the endpoint starts).

The contract between the protocol and an agent process:
  started with   variables task (the A2A Task plus a revision `rev`) and req (the message and request options),
                 tags a2a, task-<id>, ctx-<contextId>
  after a turn   calls a2a-task-update with task and outcome {state, text, artifacts} (or {agent: <AI Agent result>})
  needs input    waits for message a2a-send, correlation key =task.id, carrying followUp {message, blocking, hl}

The BPMN and DMN files are the source of truth once generated; this script documents how they were produced and
regenerates them, so edit either the script or the files, not both.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib import Proc, Collab  # noqa: E402
import dmn  # noqa: E402
import feel  # noqa: E402
from agent import AGENT, TECH_PROPS, add_tools, agent_outcome, agent_settings, tech_devices_settings, tool_ext  # noqa: E402
from feel import one, nn, TS, TERMINAL, SETTLED, push_name, push_prefix  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HTTP = "io.camunda.connectors.HttpJson.v2"
AGENT_BPMN = "bpmn/a2a-agent.bpmn"
PROTOCOL_BPMN = "bpmn/a2a-protocol.bpmn"
FIXTURE_BPMN = "tck/fixture/a2a-tck-fixture.bpmn"
# local templates, found through .camunda/element-templates
CARD_T = "dev.hansel.a2a.server.card.v1"
RPC_T = "dev.hansel.a2a.server.rpc.v1"
PUSH_T = "dev.hansel.a2a.server.push.v1"
APPLIES = []     # element template applications, run after the diagrams are written
# Engine calls that can miss turn the HTTP status into a BPMN error that a boundary event catches.
ENGINE_ERRORS = ('=if string(error.code) = "404" then bpmnError("NOT_FOUND", "not found") '
                 'else if string(error.code) = "409" then bpmnError("CONFLICT", "already exists") else null')
ERRORS = {"NotFound": "NOT_FOUND", "Conflict": "CONFLICT", "PushFailed": "PUSH_FAILED", "AgentFailed": "AGENT_FAILED"}


def write(path, content):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def apply(path, template, element, sets):
    APPLIES.append((path, template, element, sets))


def run_applies():
    for step in APPLIES:
        if callable(step):
            step()
            continue
        path, template, element, sets = step
        sets = sets() if callable(sets) else sets
        cmd = ["c8ctl", "element-template", "apply", "-i", template, element, os.path.join(ROOT, path)]
        for k, v in sets:
            cmd += ["--set", "%s=%s" % (k, v)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            sys.exit("template apply failed for %s/%s" % (path, element))


def add_properties(path, element, props):
    """An element template replaces the zeebe:properties of a tool, so they are written back afterwards."""
    def step():
        full = os.path.join(ROOT, path)
        xml = open(full).read()
        start = xml.index('id="%s"' % element)
        at = xml.index("<bpmn:extensionElements>", start) + len("<bpmn:extensionElements>")
        xml = xml[:at] + props + xml[at:]
        open(full, "w").write(xml)
    APPLIES.append(step)


def engine(path, element, url, body=None, result="={}", method="POST", errors=True, empty=False):
    """An HTTP JSON task that calls the engine REST API; `url` is a FEEL string expression for the path.
    `empty`: the call answers 204 without a body, which the JSON response format cannot read."""
    sets = [("method", method), ("url", '="{{secrets.ENGINE_URL}}" + %s' % url), ("resultExpression", result)]
    if empty:
        sets.append(("documentReturnFormat.choice", "TEXT"))
    if body is not None:
        sets += [("body", body), ("ignoreNullValues", "true")]
    if errors:
        sets.append(("errorExpression", ENGINE_ERRORS))
    apply(path, HTTP, element, sets)


def await_call(p, id, name, probe, until, seconds, out="seen", **kw):
    """Call a2a-await: read engine state with `probe` until `until` holds or `seconds` (a FEEL number) have passed.
    It always reads once, so 0 seconds is a single read."""
    deadline = '=string(now() + duration("PT" + string(%s) + "S"))' % seconds  # variables hold temporals as strings
    return p.call(id, name, 0, 0, "a2a-await", inputs=[("=" + probe, "probe"), ("=" + until, "until"), (deadline, "deadline")],
                  outputs=[("=check.seen", out), ("=check.visible", "visible")], **kw)


def task_probe(key):
    # scopeKey: the root scope only; a call activity's input mapping keeps its own copy of task in its element scope
    return one('{path: "/v2/variables/search?truncateValues=false", body: {filter: {name: "task", processInstanceKey: %s, '
               'scopeKey: %s}, page: {limit: 1}}}' % (key, key))


def config_probe(name):
    return one('{path: "/v2/cluster-variables/search?truncateValues=false", body: {filter: {name: %s}, page: {limit: 1}}}'
               % name)


def configs_search(task_id):
    return one('{filter: {name: {"$like": %s + "*"}}, page: {limit: 100}}' % push_prefix(task_id))


def follow_up_mapping():
    """Output mappings of the follow-up message: the client's message joins the history and the task is working again."""
    task = one("""={id: task.id, contextId: task.contextId, rev: task.rev + 1,
        status: {state: "TASK_STATE_WORKING", timestamp: %s}, artifacts: task.artifacts,
        history: append(task.history, put(put(followUp.message, "taskId", task.id), "contextId", task.contextId))}""" % TS)
    return ('<zeebe:ioMapping><zeebe:output source=%s target="task" /><zeebe:output source="=followUp" target="req" />'
            '</zeebe:ioMapping>' % feel_q(task))


def feel_q(s):
    from lib import q
    return q(s)


def update_call(p, id, name, x, y, outcome, **kw):
    return p.call(id, name, x, y, "a2a-task-update", inputs=[("=task", "task"), ("=" + outcome, "outcome")],
                  outputs=[("=task", "task")], **kw)


# =============================================================================================
# bpmn/a2a-agent.bpmn: what a customer models
# =============================================================================================
def card_proc():
    p = Proc("a2a-card", "A2A Agent Card")
    p.start("CardRequested", "Agent Card requested", 150, 82)
    p.end("CardServed", "Card served", 280, 82)
    p.flow("CardRequested", "CardServed")
    return p


def agent_proc():
    p = Proc("a2a-agent", "A2A task")
    p.error_codes = ERRORS
    p.msg("Msg_followUp", "a2a-send", "=task.id")
    p.start("TaskReceived", "A2A task received", 150, 262)
    p.xor("NextTurn", "", 230, 255)
    p.sub("AgentTools", "A2A Server Agent", 330, 120, 400, 280, kind="adHocSubProcess")
    add_tools(p, "AgentTools", 395, 220)
    p.boundary_error("AgentError", "Agent failed", "AgentTools", "AgentFailed", 690, 382)
    update_call(p, "UpdateTask", "Update A2A task", 800, 238, "{agent: agent}")
    p.xor("InputRequired", "Input required?", 950, 253)
    p.catch_msg("FollowUp", "Follow-up received", 1060, 260, "Msg_followUp", ext=follow_up_mapping())
    p.end("TaskDone", "Task done", 1060, 370)
    update_call(p, "ReportFailure", "Report failure", 800, 460,
                '{state: "TASK_STATE_FAILED", text: "The agent could not complete the request."}')
    p.end("TaskFailed", "Task failed", 950, 482)
    p.flow("TaskReceived", "NextTurn")
    p.flow("NextTurn", "AgentTools")
    p.flow("AgentTools", "UpdateTask")
    p.flow("UpdateTask", "InputRequired")
    p.flow("InputRequired", "FollowUp", "yes", cond='=task.status.state = "TASK_STATE_INPUT_REQUIRED"')
    p.flow("InputRequired", "TaskDone", "no", default=True, route="down-in")
    p.flow("FollowUp", "NextTurn", route="over:155")
    p.flow("AgentError", "ReportFailure")
    p.flow("ReportFailure", "TaskFailed")
    apply(AGENT_BPMN, AGENT, "AgentTools", agent_settings())
    apply(AGENT_BPMN, HTTP, "list_tech_devices", tech_devices_settings())
    add_properties(AGENT_BPMN, "list_tech_devices", tool_ext(*TECH_PROPS))
    return p


def card_template():
    """Last, because the card is read from the tools as they are in the written diagram."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_card
    apply(AGENT_BPMN, CARD_T, "CardRequested", lambda: [
        ("inbound.responseExpression", gen_card.card_response(gen_card.skills_from_bpmn(
            os.path.join(ROOT, AGENT_BPMN))))])


# =============================================================================================
# tck/fixture: the scripted stand-in for the agent
# =============================================================================================
def fixture_proc():
    p = Proc("a2a-tck-fixture", "A2A TCK fixture")
    p.msg("Msg_followUp", "a2a-send", "=task.id")
    p.start("TaskReceived", "Task received", 150, 262)
    p.xor("NextTurn", "", 230, 255)
    p.rule("ClassifyMessage", "Classify message", 330, 240, "a2a-classify", "sc")
    art = one("""if sc.artifact = null then null else [{artifactId: uuid(), name: "output", parts:
        if sc.artifact = "text" then [{text: "Generated text content"}]
        else if sc.artifact = "file" then [{raw: "dGNr", mediaType: "text/plain", filename: "output.txt"}]
        else if sc.artifact = "file-url" then [{url: "https://example.com/output.txt", mediaType: "text/plain", filename: "output.txt"}]
        else [{data: {key: "value", count: 42}}]}]""")
    p.script("ApplyScenario", "Apply scenario", 480, 240, one("""={state: sc.state,
        text: if sc.statusText != null then sc.statusText
              else if sc.echo then "Unhandled messageId prefix: " + req.message.messageId else null,
        artifacts: %s}""" % art), "outcome")
    update_call(p, "UpdateTask", "Update A2A task", 630, 240, "outcome")
    p.xor("InputRequired", "Input required?", 780, 255)
    p.catch_msg("FollowUp", "Follow-up received", 890, 262, "Msg_followUp", ext=follow_up_mapping())
    p.end("TaskDone", "Task done", 890, 372)
    p.flow("TaskReceived", "NextTurn")
    p.flow("NextTurn", "ClassifyMessage")
    p.flow("ClassifyMessage", "ApplyScenario")
    p.flow("ApplyScenario", "UpdateTask")
    p.flow("UpdateTask", "InputRequired")
    p.flow("InputRequired", "FollowUp", "yes", cond='=task.status.state = "TASK_STATE_INPUT_REQUIRED"')
    p.flow("InputRequired", "TaskDone", "no", default=True, route="down-in")
    p.flow("FollowUp", "NextTurn", route="over:120")
    return p


CLASSIFY_IN = [("Message id", "req.message.messageId", "string")]


def decisions():
    prefix = lambda s: 'starts with(?, "%s")' % s  # noqa: E731
    rules = [
        ("TCK: stay input-required", [prefix("tck-input-required")], ['"TASK_STATE_INPUT_REQUIRED"', "null", "null", "false"]),
        ("TCK: file artifact by url", [prefix("tck-artifact-file-url")], ['"TASK_STATE_COMPLETED"', "null", '"file-url"', "false"]),
        ("TCK: file artifact", [prefix("tck-artifact-file")], ['"TASK_STATE_COMPLETED"', "null", '"file"', "false"]),
        ("TCK: text artifact", [prefix("tck-artifact-text")], ['"TASK_STATE_COMPLETED"', "null", '"text"', "false"]),
        ("TCK: data artifact", [prefix("tck-artifact-data")], ['"TASK_STATE_COMPLETED"', "null", '"data"', "false"]),
        ("TCK: complete the task", [prefix("tck-complete-task")],
         ['"TASK_STATE_COMPLETED"', '"Hello from TCK"', "null", "false"]),
        ("Any other message echoes its id and completes", ["-"], ['"TASK_STATE_COMPLETED"', "null", "null", "true"]),
    ]
    write("tck/fixture/a2a-classify.dmn", dmn.table(
        "a2a-classify", "Classify A2A message", CLASSIFY_IN,
        [("state", "State", "string"), ("statusText", "Status text", "string"),
         ("artifact", "Artifact", "string"), ("echo", "Echo", "boolean")], rules))

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


# =============================================================================================
# bpmn/a2a-protocol.bpmn: the A2A 1.0 protocol
# =============================================================================================
P = PROTOCOL_BPMN


def task_update():
    """Called by the agent process after each turn: applies the outcome to the task and starts push delivery."""
    p = Proc("a2a-task-update", "A2A task update")
    p.start("TurnFinished", "Turn finished")
    out = "(if outcome.agent != null then %s else outcome)" % agent_outcome("outcome")
    p.script("ApplyOutcome", "Apply outcome", 0, 0, one("""=
      (for o in [%s] return
       for m in [if o.text = null then null else {messageId: uuid(), contextId: task.contextId, taskId: task.id,
                 role: "ROLE_AGENT", parts: [{text: o.text}]}] return
       {id: task.id, contextId: task.contextId, rev: task.rev + 1,
        status: %s,
        artifacts: concatenate(if o.replaceAnswer = true then task.artifacts[not(list contains(["tool-trace", "answer", "question"], item.name))]
                               else task.artifacts, if o.artifacts = null then [] else o.artifacts),
        history: if m = null then task.history else append(task.history, m)})[1][1]"""
        % (out, nn("{state: o.state, message: m, timestamp: %s}" % TS))), "task")
    p.node("serviceTask", "FindPushConfigs", "Find push configs")
    p.xor("AnyPushConfigs", "Push configs?")
    p.node("serviceTask", "StartPushDelivery", "Start push delivery")
    p.xor("PushHandled", "")
    p.end("TaskUpdated", "Task updated")
    p.flow("TurnFinished", "ApplyOutcome")
    p.flow("ApplyOutcome", "FindPushConfigs")
    p.flow("FindPushConfigs", "AnyPushConfigs")
    p.flow("AnyPushConfigs", "StartPushDelivery", "yes", cond="=count(configItems) > 0")
    p.flow("AnyPushConfigs", "PushHandled", "no", default=True)
    p.flow("StartPushDelivery", "PushHandled")
    p.flow("PushHandled", "TaskUpdated")
    p.auto({"StartPushDelivery": -1}, cols={"PushHandled": 5, "TaskUpdated": 6})
    find_and_deliver("FindPushConfigs", "StartPushDelivery", "task.id")
    return p


def find_and_deliver(find, start, task_id, task_var="task"):
    engine(P, find, '"/v2/cluster-variables/search?truncateValues=false"', "=" + configs_search(task_id),
           result="={configItems: response.body.items}")
    engine(P, start, '"/v2/process-instances"', "=" + one("""{processDefinitionId: "a2a-push-notify",
        variables: {configs: for i in configItems return from json(i.value), payload: %s}}"""
                                                           % feel.wrapped("null", '"task"', task_var)))


def push_notify():
    p = Proc("a2a-push-notify", "A2A push notification delivery")
    p.error_codes = ERRORS
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
    apply(P, PUSH_T, "DeliverNotification", [("retries", "2"), ("retryBackoff", "PT1S")])
    return p


def await_proc():
    """Reads engine state until a write is visible: the search API is eventually consistent."""
    p = Proc("a2a-await", "A2A await visible state")
    p.start("AwaitRequested", "Wait requested")
    p.xor("LookAgain", "")
    p.node("serviceTask", "ReadState", "Read engine state")
    p.script("CheckState", "Check state", 0, 0, one("""=
      (for v in [if count(items) > 0 then from json(items[1].value) else null] return
       {attempt: (if is defined(check) and check != null then check.attempt else 0) + 1, seen: v,
        visible: if until.kind = "absent" then v = null
          else if until.kind = "present" then v != null and (until.value = null or v = until.value)
          else v != null and v.rev >= until.minRev
            and (until.settled != true or list contains(%s, v.status.state))
            and (until.messageId = null or (some h in v.history satisfies h.messageId = until.messageId))})[1]""" % SETTLED),
             "check")
    p.xor("IsVisible", "Visible?")
    p.end("Visible", "Visible")
    p.xor("TriesLeft", "Time left?")
    p.catch_timer("WaitAMoment", "Wait a moment", 0, 0, '="PT0.25S"')
    p.end("GaveUp", "Gave up")
    p.flow("AwaitRequested", "LookAgain")
    p.flow("LookAgain", "ReadState")
    p.flow("ReadState", "CheckState")
    p.flow("CheckState", "IsVisible")
    p.flow("IsVisible", "Visible", "yes", cond="=check.visible")
    p.flow("IsVisible", "TriesLeft", "no", default=True)
    p.flow("TriesLeft", "WaitAMoment", "yes", cond="=now() < date and time(deadline)")
    p.flow("TriesLeft", "GaveUp", "no", default=True)
    p.flow("WaitAMoment", "LookAgain", route="back:60")
    p.auto({"TriesLeft": 1, "WaitAMoment": 1, "GaveUp": 2}, cols={"WaitAMoment": 6, "GaveUp": 6})
    engine(P, "ReadState", "probe.path", "=probe.body", result="={items: response.body.items}")
    return p


def correlate():
    p = Proc("a2a-correlate", "A2A correlate message to task")
    p.error_codes = ERRORS
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
    engine(P, "CorrelateMessage", '"/v2/messages/correlation"',
           "={name: messageName, correlationKey: taskId, variables: payload}")
    return p


def handler():
    p = Proc("a2a-rpc", "A2A JSON-RPC handler")
    p.error_codes = ERRORS
    rows = {}

    def at(row, *ids):
        for i in ids:
            rows[i] = row

    # --- spine: push switch, parse, validate, route ----------------------------------------------
    p.start("RpcReceived", "A2A request received")
    p.xor("IsPushMethod", "Push involved?")
    p.node("serviceTask", "ReadPushSetting", "Read push setting")
    p.xor("PushSettingKnown", "")
    p.script("ParseRequest", "Parse request", 0, 0, "=" + feel.CTX, "ctx")
    p.rule("ValidateRequest", "Validate request", 0, 0, "a2a-validate", "verdict")
    p.xor("RouteRequest", "Route request")
    at(4, "RpcReceived", "IsPushMethod", "PushSettingKnown", "ParseRequest", "ValidateRequest", "RouteRequest")
    at(3, "ReadPushSetting")
    p.flow("RpcReceived", "IsPushMethod")
    p.flow("IsPushMethod", "ReadPushSetting", "push", cond=one(
        '''=rpc instance of context and rpc.method instance of string and (list contains(["CreateTaskPushNotificationConfig",
        "GetTaskPushNotificationConfig", "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig"], rpc.method)
        or (rpc.method = "SendMessage" and rpc.params.configuration.taskPushNotificationConfig != null))'''))
    p.flow("IsPushMethod", "PushSettingKnown", "other", default=True)
    p.flow("ReadPushSetting", "PushSettingKnown")
    p.flow("PushSettingKnown", "ParseRequest")
    p.flow("ParseRequest", "ValidateRequest")
    p.flow("ValidateRequest", "RouteRequest")

    # --- answered without a task -----------------------------------------------------------------
    p.script("BuildValidationError", "Build validation error", 0, 0, "=" + feel.error_response("verdict"), "rpcResponse")
    p.end("ValidationErrorReady", "Error response ready")
    p.script("BuildDirectMessage", "Build direct message response", 0, 0, "=" + feel.result(one(
        '''{message: {messageId: uuid(), contextId: if ctx.contextId != null then ctx.contextId else uuid(),
        role: "ROLE_AGENT", parts: [{text: "Direct message response"}]}}''')), "rpcResponse")
    p.end("DirectMessageReady", "Message response ready")
    at(0, "BuildValidationError", "ValidationErrorReady")
    at(1, "BuildDirectMessage", "DirectMessageReady")
    p.flow("RouteRequest", "BuildValidationError", "invalid", cond='=verdict.route = "error"')
    p.flow("RouteRequest", "BuildDirectMessage", "direct message",
           cond='=verdict.route = "SendMessage" and ctx.messageId != null and starts with(ctx.messageId, "tck-message-response")')
    p.flow("BuildValidationError", "ValidationErrorReady")
    p.flow("BuildDirectMessage", "DirectMessageReady")

    # --- ListTasks: tasks by tag, their task variables in one search -------------------------------
    p.script("PrepareList", "Prepare task list", 0, 0, "=" + feel.list_request(), "listReq")
    p.node("serviceTask", "SearchTasks", "Search tasks")
    p.xor("AnyTasks", "Any tasks?")
    p.node("serviceTask", "ReadTasks", "Read their state")
    p.xor("ListJoin", "")
    views = one("""if is defined(taskItems) and taskItems != null then
        for i in taskItems return (for task in [from json(i.value)] return %s)[1] else []""" % feel.view("ctx.hl"))
    p.script("BuildTaskList", "Build task list", 0, 0, "=(for taskViews in [%s] return %s)[1]"
             % (views, feel.list_response()), "rpcResponse")
    p.end("TaskListReady", "Task list ready")
    at(2, "PrepareList", "SearchTasks", "AnyTasks", "ReadTasks", "ListJoin", "BuildTaskList", "TaskListReady")
    p.flow("RouteRequest", "PrepareList", "list", cond='=verdict.route = "ListTasks"')
    p.flow("PrepareList", "SearchTasks")
    p.flow("SearchTasks", "AnyTasks")
    p.flow("AnyTasks", "ReadTasks", "tasks", cond="=count(taskKeys) > 0")
    p.flow("AnyTasks", "ListJoin", "none", default=True, route="over:30")
    p.flow("ReadTasks", "ListJoin")
    p.flow("ListJoin", "BuildTaskList")
    p.flow("BuildTaskList", "TaskListReady")
    engine(P, "SearchTasks", '"/v2/process-instances/search"', "=" + one("""{filter: {tags:
        if listReq.ctxTag != null then ["a2a", listReq.ctxTag] else ["a2a"]},
        sort: [{field: "startDate", order: "DESC"}], page: {limit: 100}}"""),
           result="={taskKeys: for i in response.body.items return i.processInstanceKey}")
    engine(P, "ReadTasks", '"/v2/variables/search?truncateValues=false"',
           '={filter: {name: "task", processInstanceKey: {"$in": taskKeys}, scopeKey: {"$in": taskKeys}}, page: {limit: 100}}',
           result="={taskItems: response.body.items}")

    # --- SendMessage that starts a task ------------------------------------------------------------
    # the agent process starts working on the task as soon as it is created, so the task starts as working
    p.script("PrepareNewTask", "Prepare new task", 0, 0, one("""=
      (for cid in [if ctx.contextId != null then ctx.contextId else uuid()] return
       for s in [replace(cid, "[^A-Za-z0-9_:.-]", "_")] return
       for tid in [uuid()] return
       {taskId: tid, contextId: cid, ctxTag: "ctx-" + (if string length(s) > 90 then substring(s, 1, 90) else s),
        task: {id: tid, contextId: cid, rev: 1, status: {state: "TASK_STATE_WORKING", timestamp: %s}, artifacts: [],
               history: [put(put(ctx.m, "taskId", tid), "contextId", cid)]},
        push: if ctx.pushEnabled and ctx.taskPush != null then put(put(ctx.taskPush, "taskId", tid), "id",
              if ctx.taskPush.id instance of string then ctx.taskPush.id else uuid()) else null})[1][1][1]""" % TS),
             "lookup")
    p.xor("HasInlinePush", "Push config given?")
    p.node("serviceTask", "StoreInlineConfig", "Store push config")
    await_call(p, "AwaitInlineConfig", "Await push config", config_probe(push_name("lookup.taskId", "lookup.push.id")),
               '{kind: "present", value: lookup.push}', "5")
    p.xor("InlinePushDone", "")
    p.node("serviceTask", "CreateTask", "Start agent process")
    await_call(p, "AwaitNewTask", "Await task", task_probe("created"),
               '{kind: "task", minRev: 1, settled: ctx.blocking}', "if ctx.blocking then 20 else 5")
    p.script("BuildNewTaskResponse", "Build task response", 0, 0, "=" + one(
        "(for task in [if seen != null then seen else lookup.task] return %s)[1]"
        % feel.result(feel.wrapped("ctx.hl", '"task"'))), "rpcResponse")
    p.end("NewTaskReady", "Task response ready")
    at(4, "PrepareNewTask", "HasInlinePush", "InlinePushDone", "CreateTask", "AwaitNewTask", "BuildNewTaskResponse",
       "NewTaskReady")
    at(5, "StoreInlineConfig", "AwaitInlineConfig")
    p.flow("RouteRequest", "PrepareNewTask", "new task",
           cond='=verdict.route = "SendMessage" and ctx.taskId = null and not(starts with(ctx.messageId, "tck-message-response"))')
    p.flow("PrepareNewTask", "HasInlinePush")
    p.flow("HasInlinePush", "StoreInlineConfig", "yes", cond="=lookup.push != null")
    p.flow("HasInlinePush", "InlinePushDone", "no", default=True)
    p.flow("StoreInlineConfig", "AwaitInlineConfig")
    p.flow("AwaitInlineConfig", "InlinePushDone")
    p.flow("InlinePushDone", "CreateTask")
    p.flow("CreateTask", "AwaitNewTask")
    p.flow("AwaitNewTask", "BuildNewTaskResponse")
    p.flow("BuildNewTaskResponse", "NewTaskReady")
    engine(P, "StoreInlineConfig", '"/v2/cluster-variables/global"',
           "={name: %s, value: lookup.push}" % push_name("lookup.taskId", "lookup.push.id"))
    engine(P, "CreateTask", '"/v2/process-instances"', "=" + one("""{processDefinitionId: "{{secrets.A2A_AGENT_PROCESS}}",
        variables: {task: lookup.task, req: {message: ctx.m, blocking: ctx.blocking, hl: ctx.hl}},
        tags: ["a2a", "task-" + lookup.taskId, lookup.ctxTag]}"""),
           result="={created: response.body.processInstanceKey}")

    # --- every other method works on an existing task ------------------------------------------------
    p.script("PrepareLookup", "Prepare lookup", 0, 0,
             '={taskId: if ctx.method = "SendMessage" then ctx.taskId else ctx.ref}', "lookup")
    p.node("serviceTask", "FindTask", "Find task")
    p.xor("TaskKnown", "Task known?")
    await_call(p, "ReadTask", "Read task", task_probe("found"), '{kind: "task", minRev: 0}', "0", out="task")
    p.xor("RouteMethod", "Method")
    p.xor("NotFoundJoin", "")
    p.script("BuildNotFound", "Build task not found error", 0, 0,
             "=" + feel.resp_from(feel.err(-32001, "Task not found", "TASK_NOT_FOUND")), "rpcResponse")
    p.end("NotFoundReady", "Not found response ready")
    at(7, "PrepareLookup", "FindTask", "TaskKnown", "ReadTask", "RouteMethod")
    at(6, "NotFoundJoin", "BuildNotFound", "NotFoundReady")
    p.flow("RouteRequest", "PrepareLookup", "task method", default=True)
    p.flow("PrepareLookup", "FindTask")
    p.flow("FindTask", "TaskKnown")
    p.flow("TaskKnown", "ReadTask", "yes", cond="=found != null")
    p.flow("TaskKnown", "NotFoundJoin", "no", default=True)
    p.flow("ReadTask", "RouteMethod")
    p.flow("RouteMethod", "NotFoundJoin", "task not visible", default=True)
    p.flow("NotFoundJoin", "BuildNotFound")
    p.flow("BuildNotFound", "NotFoundReady")
    engine(P, "FindTask", '"/v2/process-instances/search"',
           '={filter: {tags: ["task-" + lookup.taskId]}, page: {limit: 1}}',
           result="={found: if count(response.body.items) > 0 then response.body.items[1].processInstanceKey else null}")

    # GetTask
    p.script("BuildTaskView", "Build task view", 0, 0, "=" + feel.result(feel.view("ctx.hl")), "rpcResponse")
    p.end("TaskViewReady", "Task response ready")
    at(7, "BuildTaskView", "TaskViewReady")
    p.flow("RouteMethod", "BuildTaskView", "GetTask", cond='=task != null and ctx.method = "GetTask"')
    p.flow("BuildTaskView", "TaskViewReady")

    # CancelTask
    p.xor("Cancelable", "Cancelable?")
    p.script("MarkCanceled", "Mark canceled", 0, 0, one("""={id: task.id, contextId: task.contextId, rev: task.rev + 1,
        status: {state: "TASK_STATE_CANCELED", timestamp: %s}, artifacts: task.artifacts, history: task.history}""" % TS),
             "task")
    p.node("serviceTask", "StoreCanceled", "Store canceled task")
    p.boundary_error("TaskGone", "Task ended", "StoreCanceled", "NotFound", 0, 0)
    p.node("serviceTask", "CancelAgent", "Cancel agent process")
    p.boundary_error("AgentGone", "Already ended", "CancelAgent", "NotFound", 0, 0)
    p.xor("CancelSent", "")
    await_call(p, "AwaitCanceled", "Await canceled task", task_probe("found"), '{kind: "task", minRev: task.rev}', "5",
               out="seen")
    p.node("serviceTask", "FindCancelPush", "Find push configs")
    p.xor("AnyCancelPush", "Push configs?")
    p.node("serviceTask", "StartCancelPush", "Start push delivery")
    p.xor("CancelPushHandled", "")
    p.script("BuildCanceledView", "Build canceled task view", 0, 0, "=" + feel.result(feel.view("null")), "rpcResponse")
    p.end("CanceledReady", "Cancel response ready")
    p.xor("NotCancelableJoin", "")
    p.script("BuildNotCancelable", "Build not cancelable error", 0, 0, "=" + feel.resp_from(
        feel.err(-32002, "Task cannot be canceled in its current state", "TASK_NOT_CANCELABLE")), "rpcResponse")
    p.end("NotCancelableReady", "Not cancelable response ready")
    at(8, "Cancelable", "MarkCanceled", "StoreCanceled", "CancelAgent", "CancelSent", "AwaitCanceled", "FindCancelPush",
       "AnyCancelPush", "CancelPushHandled", "BuildCanceledView", "CanceledReady")
    at(9, "StartCancelPush")
    at(10, "NotCancelableJoin", "BuildNotCancelable", "NotCancelableReady")
    p.flow("RouteMethod", "Cancelable", "CancelTask", cond='=task != null and ctx.method = "CancelTask"')
    p.flow("Cancelable", "MarkCanceled", "yes", cond="=not(list contains(%s, task.status.state))" % TERMINAL)
    p.flow("Cancelable", "NotCancelableJoin", "no", default=True)
    p.flow("MarkCanceled", "StoreCanceled")
    p.flow("StoreCanceled", "CancelAgent")
    p.flow("TaskGone", "NotCancelableJoin")
    p.flow("CancelAgent", "CancelSent")
    p.flow("AgentGone", "CancelSent")
    p.flow("CancelSent", "AwaitCanceled")
    p.flow("AwaitCanceled", "FindCancelPush")
    p.flow("FindCancelPush", "AnyCancelPush")
    p.flow("AnyCancelPush", "StartCancelPush", "yes", cond="=count(configItems) > 0")
    p.flow("AnyCancelPush", "CancelPushHandled", "no", default=True)
    p.flow("StartCancelPush", "CancelPushHandled")
    p.flow("CancelPushHandled", "BuildCanceledView")
    p.flow("BuildCanceledView", "CanceledReady")
    p.flow("NotCancelableJoin", "BuildNotCancelable")
    p.flow("BuildNotCancelable", "NotCancelableReady")
    engine(P, "StoreCanceled", 'string("/v2/element-instances/") + found + "/variables"', "={variables: {task: task}}",
           method="PUT", empty=True)
    engine(P, "CancelAgent", 'string("/v2/process-instances/") + found + "/cancellation"', "={}", empty=True)
    find_and_deliver("FindCancelPush", "StartCancelPush", "task.id")

    # SendMessage to an existing task: a follow-up
    follow_error = one("""if ctx.contextId != null and ctx.contextId != task.contextId then %s
        else if list contains(%s, task.status.state) then %s else null""" % (
        feel.err(-32602, "contextId does not match the task"), TERMINAL,
        feel.err(-32004, "Task is in a terminal state and cannot accept messages", "UNSUPPORTED_OPERATION")))
    p.script("CheckFollowUp", "Check follow-up", 0, 0, "=" + follow_error, "followError")
    p.xor("FollowUpAccepted", "Accepted?")
    p.call("CorrelateFollowUp", "Hand follow-up to the task", 0, 0, "a2a-correlate",
           inputs=[('="a2a-send"', "messageName"), ("=task.id", "taskId"), ("=3", "tries"),
                   ("={followUp: {message: ctx.m, blocking: ctx.blocking, hl: ctx.hl}}", "payload")],
           outputs=[("=correlated", "correlated")])
    p.xor("TaskWaiting", "Task was waiting?")
    await_call(p, "AwaitFollowUp", "Await task", task_probe("found"),
               '{kind: "task", minRev: 0, messageId: ctx.messageId, settled: ctx.blocking}',
               "if ctx.blocking then 20 else 5")
    p.script("BuildFollowUpResponse", "Build task response", 0, 0, "=" + one(
        "(for task in [if seen != null then seen else task] return %s)[1]" % feel.result(feel.wrapped("ctx.hl", '"task"'))),
             "rpcResponse")
    p.end("FollowUpReady", "Task response ready")
    p.script("BuildFollowUpError", "Build follow-up error", 0, 0, "=" + one(
        "(for e in [if followError != null then followError else %s] return %s)[1]"
        % (feel.err(-32004, "Task is not waiting for input", "UNSUPPORTED_OPERATION"), feel.error_response("e"))),
             "rpcResponse")
    p.xor("FollowUpErrorJoin", "")
    p.end("FollowUpErrorReady", "Error response ready")
    at(11, "CheckFollowUp", "FollowUpAccepted", "CorrelateFollowUp", "TaskWaiting", "AwaitFollowUp", "BuildFollowUpResponse",
       "FollowUpReady")
    at(12, "FollowUpErrorJoin", "BuildFollowUpError", "FollowUpErrorReady")
    p.flow("RouteMethod", "CheckFollowUp", "SendMessage", cond='=task != null and ctx.method = "SendMessage"')
    p.flow("CheckFollowUp", "FollowUpAccepted")
    p.flow("FollowUpAccepted", "CorrelateFollowUp", "yes", cond="=followError = null")
    p.flow("FollowUpAccepted", "FollowUpErrorJoin", "no", default=True)
    p.flow("CorrelateFollowUp", "TaskWaiting")
    p.flow("TaskWaiting", "AwaitFollowUp", "yes", cond="=correlated = true")
    p.flow("TaskWaiting", "FollowUpErrorJoin", "no", default=True)
    p.flow("AwaitFollowUp", "BuildFollowUpResponse")
    p.flow("BuildFollowUpResponse", "FollowUpReady")
    p.flow("FollowUpErrorJoin", "BuildFollowUpError")
    p.flow("BuildFollowUpError", "FollowUpErrorReady")

    # push notification config operations: one cluster variable per config
    p.node("serviceTask", "ReadConfigs", "Read push configs")
    p.script("PreparePushOp", "Prepare push operation", 0, 0, one("""=
      (for configs in [for i in configItems return from json(i.value)] return
       for create in [ctx.method = "CreateTaskPushNotificationConfig"] return
       for cfgId in [if create then (if ctx.pushCfg.id instance of string then ctx.pushCfg.id else uuid())
                  else ctx.p.id] return
       for config in [put(put(ctx.pushCfg, "taskId", task.id), "id", cfgId)] return
       for exists in [count(configs[item.id = cfgId]) > 0] return
       {name: %s, config: config,
        write: if create and not(ctx.pushCfg.url instance of string and ctx.pushCfg.url != "") then "none"
               else if create then (if exists then "replace" else "create")
               else if ctx.method = "DeleteTaskPushNotificationConfig" and exists then "delete" else "none",
        response: if create and not(ctx.pushCfg.url instance of string and ctx.pushCfg.url != "") then
                    {error: %s}
                  else if create then {result: config}
                  else if ctx.method = "GetTaskPushNotificationConfig" then
                    (if exists then {result: configs[item.id = cfgId][1]} else {error: %s})
                  else if ctx.method = "ListTaskPushNotificationConfigs" then {result: {configs: configs, nextPageToken: ""}}
                  else {result: {}}})[1][1][1][1][1]""" % (
        push_name("task.id", "cfgId"), feel.err(-32602, "Invalid params: url is required"),
        feel.err(-32602, "Push notification config not found"))), "pushOp")
    p.xor("WriteConfig", "Write config?")
    p.node("serviceTask", "CreateConfig", "Create config")
    p.node("serviceTask", "ReplaceConfig", "Replace config")
    p.node("serviceTask", "DeleteConfig", "Delete config")
    p.boundary_error("ConfigGone", "Already deleted", "DeleteConfig", "NotFound", 0, 0)
    p.xor("ConfigWritten", "")
    await_call(p, "AwaitConfig", "Await config change", config_probe("pushOp.name"),
               '{kind: if pushOp.write = "delete" then "absent" else "present", value: pushOp.config}', "5", out="seenConfig")
    p.xor("ConfigVisible", "")
    p.script("BuildPushResponse", "Build push response", 0, 0, "=" + one(
        """if pushOp.response.error != null then %s else %s""" % (
            feel.error_response("pushOp.response.error"), feel.result("pushOp.response.result"))), "rpcResponse")
    p.end("PushResponseReady", "Push response ready")
    at(13, "ReadConfigs", "PreparePushOp", "WriteConfig", "ReplaceConfig", "ConfigWritten", "AwaitConfig", "ConfigVisible",
       "BuildPushResponse", "PushResponseReady")
    at(14, "CreateConfig")
    at(15, "DeleteConfig")
    p.flow("RouteMethod", "ReadConfigs", "push config", cond="=task != null and list contains(ctx.pushMethods, ctx.method)")
    p.flow("ReadConfigs", "PreparePushOp")
    p.flow("PreparePushOp", "WriteConfig")
    p.flow("WriteConfig", "ReplaceConfig", "replace", cond='=pushOp.write = "replace"')
    p.flow("WriteConfig", "CreateConfig", "create", cond='=pushOp.write = "create"')
    p.flow("WriteConfig", "DeleteConfig", "delete", cond='=pushOp.write = "delete"')
    p.flow("WriteConfig", "ConfigVisible", "none", default=True, route="over:30")
    p.flow("ReplaceConfig", "ConfigWritten")
    p.flow("CreateConfig", "ConfigWritten")
    p.flow("DeleteConfig", "ConfigWritten")
    p.flow("ConfigGone", "ConfigWritten")
    p.flow("ConfigWritten", "AwaitConfig")
    p.flow("AwaitConfig", "ConfigVisible")
    p.flow("ConfigVisible", "BuildPushResponse")
    p.flow("BuildPushResponse", "PushResponseReady")
    engine(P, "ReadConfigs", '"/v2/cluster-variables/search?truncateValues=false"', "=" + configs_search("task.id"),
           result="={configItems: response.body.items}")
    engine(P, "CreateConfig", '"/v2/cluster-variables/global"', "={name: pushOp.name, value: pushOp.config}")
    engine(P, "ReplaceConfig", 'string("/v2/cluster-variables/global/") + pushOp.name', "={value: pushOp.config}",
           method="PUT")
    engine(P, "DeleteConfig", 'string("/v2/cluster-variables/global/") + pushOp.name', method="DELETE", empty=True)

    p.auto(rows)
    engine(P, "ReadPushSetting", '"/v2/expression/evaluation"',
           '={expression: "=\\"{{secrets.A2A_PUSH_ENABLED}}\\""}', result='={pushEnabled: response.body.result = "true"}',
           errors=False)
    apply(P, RPC_T, "RpcReceived", [])
    return p


def main():
    decisions()
    # the customer's diagram
    c = Collab("Collaboration_a2a_agent", "A2A agent",
               "An A2A 1.0 server agent: the Agent Card and one A2A task, worked on by an AI agent with its tools. "
               "Everything protocol-specific (JSON-RPC, task state, push notifications) is in a2a-protocol.bpmn, "
               "which is deployed unchanged next to this diagram.")
    c.add(card_proc(), "Agent Card")
    c.add(agent_proc(), "A2A task")
    write(AGENT_BPMN, c.xml())
    # the protocol
    c = Collab("Collaboration_a2a_protocol", "A2A protocol",
               "The A2A 1.0 JSON-RPC binding, deployed unchanged next to an agent diagram. The endpoint starts the "
               "process named by the secret A2A_AGENT_PROCESS for each new task and answers every other method from "
               "engine state. Not meant to be edited.")
    for proc, label in ((handler(), "A2A JSON-RPC endpoint"), (task_update(), "Update A2A task (called by the agent)"),
                        (await_proc(), "Wait until engine state is visible"), (correlate(), "Hand a follow-up to a task"),
                        (push_notify(), "Deliver push notifications")):
        c.add(proc, label)
    write(PROTOCOL_BPMN, c.xml())
    # the TCK fixture
    write(FIXTURE_BPMN, fixture_proc().xml())
    card_template()
    run_applies()
    print("generated")


if __name__ == "__main__":
    main()
