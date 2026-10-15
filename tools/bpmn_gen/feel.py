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
 idOk: p.id instance of string and p.id != "",
 taskId: if m.taskId instance of string and m.taskId != "" then m.taskId else null,
 contextId: if m.contextId instance of string and m.contextId != "" then m.contextId else null,
 messageId: if m.messageId instance of string then m.messageId else null,
 blocking: cfg.returnImmediately != true,
 hl: if cfg.historyLength instance of number then cfg.historyLength else if p.historyLength instance of number then p.historyLength else if p.history_length instance of number then p.history_length else null,
 pageSize: if p.pageSize instance of number then p.pageSize else if p.page_size instance of number then p.page_size else 50
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
