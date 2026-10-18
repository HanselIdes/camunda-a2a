"""FEEL snippets shared by the process definitions. All expressions are null-safe on purpose:
a FEEL error raises an incident, which would hang the HTTP request that triggered it."""
import re


def one(s):
    return re.sub(r"\s+", " ", s).strip()


def nn(expr):
    """Drop null entries from a context (ProtoJSON forbids null keys)."""
    return "context(get entries(%s)[item.value != null])" % expr


TS = 'substring(string(now()), 1, 19) + "Z"'

# --- handler: request parsing ---------------------------------------------------------------
CTX = one("""{
 r: if rpc instance of context then rpc else {},
 p: if r.params instance of context then r.params else {},
 m: if p.message instance of context then p.message else {},
 cfg: if p.configuration instance of context then p.configuration else {},
 ct: get value(hdr, "content-type"),
 ver: get value(hdr, "a2a-version"),
 supported: ["text/plain", "application/json"],
 method: if r.method instance of string then r.method else null,
 id: r.id,
 versionOk: if ver instance of string then (ver = "" or ver = "1" or starts with(ver, "1.")) else true,
 contentTypeOk: if ct instance of string then (starts with(lower case(ct), "application/json") or starts with(lower case(ct), "application/a2a+json")) else false,
 jsonrpcOk: r.jsonrpc = "2.0" and method != null,
 msgOk: p.message instance of context and m.messageId instance of string and m.role instance of string and m.parts instance of list,
 mediaOk: if m.parts instance of list then not(some part in m.parts satisfies part instance of context and part.mediaType != null and not(list contains(supported, part.mediaType))) else true,
 pushMethods: ["CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig", "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig"],
 pushRef: if p.task_id instance of string then p.task_id else if p.taskId instance of string then p.taskId else null,
 ref: if method != null and list contains(pushMethods, method) then pushRef else if p.id instance of string then p.id else null,
 idOk: ref instance of string and ref != "",
 pushEnabled: pushEnabled = true,
 pushCfg: context(get entries({id: p.id, url: p.url, token: p.token, authentication: p.authentication})[item.value != null]),
 taskPush: if cfg.taskPushNotificationConfig instance of context then cfg.taskPushNotificationConfig else null,
 taskId: if m.taskId instance of string and m.taskId != "" then m.taskId else null,
 contextId: if m.contextId instance of string and m.contextId != "" then m.contextId else null,
 messageId: if m.messageId instance of string then m.messageId else null,
 blocking: cfg.returnImmediately != true,
 hl: if cfg.historyLength instance of number then cfg.historyLength else if p.historyLength instance of number then p.historyLength else if p.history_length instance of number then p.history_length else null,
 pageSize: if p.pageSize instance of number then p.pageSize else if p.page_size instance of number then p.page_size else 50,
 listContextId: if p.contextId instance of string and p.contextId != "" then p.contextId else if p.context_id instance of string and p.context_id != "" then p.context_id else null,
 listStatus: if p.status instance of string and p.status != "" then p.status else null,
 listAfter: if p.statusTimestampAfter instance of string then p.statusTimestampAfter else if p.status_timestamp_after instance of string then p.status_timestamp_after else null,
 pageToken: if p.pageToken instance of string then p.pageToken else if p.page_token instance of string then p.page_token else null,
 includeArtifacts: p.includeArtifacts = true or p.include_artifacts = true
}""")

# A2A error object from a verdict-like context e
def error_response(e, rid="ctx.id"):
    return one("""{jsonrpc: "2.0", id: %s, error: if %s.reason = null then {code: %s.code, message: %s.message} else {code: %s.code, message: %s.message, data: [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", reason: %s.reason, domain: "a2a-protocol.org"}]}}"""
               % (rid, e, e, e, e, e, e))


# --- task projections -----------------------------------------------------------------------
def view(hl, var="task"):
    """Task as returned to clients, projected by historyLength `hl` (an expression). The stored task also carries
    `rev`, a revision number the protocol uses to wait for its own writes; the view leaves it out."""
    t = var
    h = ("if %s = null or %s >= count(%s.history) then %s.history else "
         "if %s <= 0 then [] else sublist(%s.history, count(%s.history) - %s + 1)" % (hl, hl, t, t, hl, t, t, hl))
    return one("""(for h in [%s] return %s)[1]""" % (h, nn(
        """{id: %s.id, contextId: %s.contextId, status: %s.status,
        artifacts: if count(%s.artifacts) > 0 then %s.artifacts else null,
        history: if count(h) > 0 then h else null}""" % (t, t, t, t, t))))


def wrapped(hl, wrap, var="task"):
    return one("""(for v in [%s] return if %s = "task" then {task: v} else v)[1]""" % (view(hl, var), wrap))


def err(code, message, reason=None):
    if reason:
        return '{code: %d, message: "%s", reason: "%s"}' % (code, message, reason)
    return '{code: %d, message: "%s"}' % (code, message)


def resp_from(e):
    return one("""(for e in [%s] return %s)[1]""" % (e, error_response("e")))


def result(expr):
    return one('{jsonrpc: "2.0", id: ctx.id, result: %s}' % expr)


TERMINAL = '["TASK_STATE_COMPLETED", "TASK_STATE_CANCELED", "TASK_STATE_FAILED", "TASK_STATE_REJECTED"]'
# states in which the agent waits: a blocking request returns once the task reaches one of them
SETTLED = ('["TASK_STATE_COMPLETED", "TASK_STATE_CANCELED", "TASK_STATE_FAILED", "TASK_STATE_REJECTED", '
           '"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"]')


# --- push notification configs: one cluster variable per task and config id ---------------------
def push_prefix(task_id):
    return '"a2a-push-" + %s + "~"' % task_id


def push_name(task_id, config_id):
    """Cluster variable names allow letters, digits and a few signs, so other characters of the config id become _."""
    return '%s + replace(%s, "[^A-Za-z0-9_.-]", "_")' % (push_prefix(task_id), config_id)


# --- ListTasks (handler side) --------------------------------------------------------------------
LIST_TAG_CONTEXT = one("""if ctx.listContextId != null then "ctx-" + (if string length(sanitizedList) > 90 then substring(sanitizedList, 1, 90) else sanitizedList) else null""")


def list_request():
    return one("""(for s in [if ctx.listContextId != null then replace(ctx.listContextId, "[^A-Za-z0-9_:.-]", "_") else ""] return
      {ctxTag: if ctx.listContextId != null then "ctx-" + (if string length(s) > 90 then substring(s, 1, 90) else s) else null,
       size: if ctx.pageSize < 1 then 50 else if ctx.pageSize > 100 then 100 else ctx.pageSize,
       start: if ctx.pageToken != null and number(ctx.pageToken) != null then number(ctx.pageToken) else 0})[1]""")


def list_response():
    return one("""(for views in [if is defined(taskViews) and taskViews != null then taskViews[item != null] else []] return
      for found in [sort(views[(ctx.listContextId = null or item.contextId = ctx.listContextId)
                              and (ctx.listStatus = null or item.status.state = ctx.listStatus)
                              and (ctx.listAfter = null or item.status.timestamp > ctx.listAfter)],
                         function(a, b) a.status.timestamp > b.status.timestamp)] return
      for left in [count(found) - listReq.start] return
      for page in [if left <= 0 then [] else sublist(found, listReq.start + 1, if left < listReq.size then left else listReq.size)] return
      {jsonrpc: "2.0", id: ctx.id, result: {
         tasks: for t in page return if ctx.includeArtifacts then t else context(get entries(t)[item.key != "artifacts"]),
         nextPageToken: if listReq.start + listReq.size < count(found) then string(listReq.start + listReq.size) else "",
         pageSize: listReq.size, totalSize: count(found)}})[1][1][1][1]""")


# --- runtime card: skills read from the deployed process definition XML --------------------------------
def _unescape(expr):
    for old, new in (("&quot;", '\\"'), ("&#34;", '\\"'), ("&apos;", "'"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        expr = 'replace(%s, "%s", "%s")' % (expr, old, new.replace("\\", "\\\\") if False else new)
    return expr


def runtime_skills():
    """FEEL that parses the tools (direct children of the ad-hoc sub-process) out of the XML in `xml`."""
    doc = _unescape('substring before(substring after(part, "<bpmn:documentation>"), "</bpmn:documentation>")')
    ex = _unescape('substring before(substring after(part, "name=\\"a2a:examples\\" value=\\""), "\\"")')
    return one("""(for inner in [substring before(substring after(xml, "<bpmn:adHocSubProcess "), "</bpmn:adHocSubProcess>")] return
      for parts in [sublist(split(inner, "<bpmn:(scriptTask|serviceTask|businessRuleTask|userTask|callActivity|subProcess) id=\\""), 2)] return
      for part in parts return
        {id: substring before(part, "\\""),
         name: substring before(substring after(part, "name=\\""), "\\""),
         description: %s,
         tags: split(substring before(substring after(part, "name=\\"a2a:tags\\" value=\\""), "\\""), ","),
         examples: split(%s, "[|]")})[1][1]""" % (doc, ex))
