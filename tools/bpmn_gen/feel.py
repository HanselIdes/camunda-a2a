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
def view(hl):
    """Task as returned to clients, projected by historyLength `hl` (an expression)."""
    h = ("if %s = null or %s >= count(task.history) then task.history else "
         "if %s <= 0 then [] else sublist(task.history, count(task.history) - %s + 1)" % (hl, hl, hl, hl))
    return one("""(for h in [%s] return %s)[1]""" % (h, nn(
        """{id: task.id, contextId: task.contextId, status: task.status,
        artifacts: if count(task.artifacts) > 0 then task.artifacts else null,
        history: if count(h) > 0 then h else null}""")))


def wrapped(hl, wrap):
    return one("""(for v in [%s] return if %s = "task" then {task: v} else v)[1]""" % (view(hl), wrap))


def err(code, message, reason=None):
    if reason:
        return '{code: %d, message: "%s", reason: "%s"}' % (code, message, reason)
    return '{code: %d, message: "%s"}' % (code, message)


def resp_from(e):
    return one("""(for e in [%s] return %s)[1]""" % (e, error_response("e")))


# --- push notification configuration operations (task side) ----------------------------------
def push_outcome():
    """{result: ...} or {error: ...} for the push operation in `pushReq`, given the current `pushConfigs`."""
    return one("""(for op in [pushReq.op] return
      if op = "CreateTaskPushNotificationConfig" then
        (if pushReq.config.url instance of string and pushReq.config.url != "" then
           {result: put(put(pushReq.config, "taskId", task.id), "id",
              if pushReq.config.id != null then pushReq.config.id else uuid())}
         else {error: {code: -32602, message: "Invalid params: url is required"}})
      else if op = "GetTaskPushNotificationConfig" then
        (if count(pushConfigs[item.id = pushReq.configId]) > 0 then {result: pushConfigs[item.id = pushReq.configId][1]}
         else {error: {code: -32602, message: "Push notification config not found"}})
      else if op = "ListTaskPushNotificationConfigs" then {result: {configs: pushConfigs, nextPageToken: ""}}
      else {result: {}})[1]""")


def push_update():
    return one("""if pushReq.op = "CreateTaskPushNotificationConfig" and pushOutcome.result != null then
        append(pushConfigs[item.id != pushOutcome.result.id], pushOutcome.result)
      else if pushReq.op = "DeleteTaskPushNotificationConfig" then pushConfigs[item.id != pushReq.configId]
      else pushConfigs""")


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
