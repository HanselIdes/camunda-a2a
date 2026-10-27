#!/usr/bin/env python3
"""Build the push-disabled protocol from the authoritative experiment diagram.

Preserves the layout of surviving elements. Adopters deploy the committed output;
this command is only for contributors changing the protocol.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

from bpmn_gen import feel
from bpmn_gen.lib import Proc
from layout_bpmn import layout_xml
from gen_card import skills_feel, skills_from_bpmn

ROOT = Path(__file__).resolve().parents[1]
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z = "http://camunda.org/schema/zeebe/1.0"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
REQUEST_MAPPING = ('={rpc: request.body, hdr: {"content-type": request.headers.`content-type`, '
                   '"a2a-version": request.headers.`a2a-version`}}')
for prefix, uri in {
    "bpmn": B, "zeebe": Z, "bpmndi": D, "dc": DC, "di": DI,
    "modeler": "http://camunda.org/schema/modeler/1.0",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}.items():
    ET.register_namespace(prefix, uri)


def remove(root, ids):
    flow_ids = {e.get("id") for e in root.iter(f"{{{B}}}sequenceFlow")
                if e.get("sourceRef") in ids or e.get("targetRef") in ids}
    removed = ids | flow_ids
    for parent in root.iter():
        for child in list(parent):
            if child.get("id") in removed or child.get("bpmnElement") in removed:
                parent.remove(child)
            elif child.tag in (f"{{{B}}}incoming", f"{{{B}}}outgoing") and child.text in removed:
                parent.remove(child)


def connect(root, process_id, source, target, condition=None, default=False, name=None):
    process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == process_id)
    flow_id = f"Flow_{source}_{target}"
    flow = ET.SubElement(process, f"{{{B}}}sequenceFlow",
                         {"id": flow_id, "sourceRef": source, "targetRef": target})
    if name:
        flow.set("name", name)
    if condition:
        ET.SubElement(flow, f"{{{B}}}conditionExpression",
                      {"{http://www.w3.org/2001/XMLSchema-instance}type": "bpmn:tFormalExpression"}).text = condition
    if default:
        next(e for e in process if e.get("id") == source).set("default", flow_id)
    for node_id, reference in ((source, "outgoing"), (target, "incoming")):
        node = next(e for e in process if e.get("id") == node_id)
        preceding = {"documentation", "extensionElements", "auditing", "monitoring", "incoming"}
        if reference == "outgoing":
            preceding.add("outgoing")
        preceding = {f"{{{B}}}{name}" for name in preceding}
        index = next((i for i, child in enumerate(node) if child.tag not in preceding), len(node))
        element = ET.Element(f"{{{B}}}{reference}")
        element.text = flow_id
        node.insert(index, element)
    shapes = {e.get("bpmnElement"): e.find(f"{{{DC}}}Bounds") for e in root.iter(f"{{{D}}}BPMNShape")}
    a, b = shapes[source], shapes[target]
    edge = ET.SubElement(root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane"), f"{{{D}}}BPMNEdge",
                         {"id": flow_id + "_di", "bpmnElement": flow_id})
    sx, sy = float(a.get("x")) + float(a.get("width")), float(a.get("y")) + float(a.get("height")) / 2
    tx, ty = float(b.get("x")), float(b.get("y")) + float(b.get("height")) / 2
    for x, y in ((sx, sy), ((sx + tx) / 2, sy), ((sx + tx) / 2, ty), (tx, ty)):
        ET.SubElement(edge, f"{{{DI}}}waypoint", {"x": str(x), "y": str(y)})


def lookup_retry(root):
    process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-rpc")
    lookup = next(e for e in process if e.get("id") == "PrepareLookup").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    expression = lookup.get("expression")
    assert expression.startswith("={taskId:") and expression.endswith("}"), "Lookup source changed"
    lookup.set("expression", expression[:-1] + ', indexDeadline: string(now() + duration("PT3S"))}')
    read = next(e for e in process if e.get("id") == "ReadTask")
    next(e for e in read.iter(f"{{{Z}}}input") if e.get("target") == "deadline").set(
        "source", "=lookup.indexDeadline")

    ET.SubElement(process, f"{{{B}}}exclusiveGateway", {"id": "LookupTimeLeft", "name": "Lookup time left?"})
    ET.SubElement(process, f"{{{B}}}exclusiveGateway", {"id": "LookupJoin"})
    timer = ET.SubElement(process, f"{{{B}}}intermediateCatchEvent",
                          {"id": "WaitForIndex", "name": "Await task index"})
    definition = ET.SubElement(timer, f"{{{B}}}timerEventDefinition", {"id": "WaitForIndex_def"})
    ET.SubElement(definition, f"{{{B}}}timeDuration",
                  {"{http://www.w3.org/2001/XMLSchema-instance}type": "bpmn:tFormalExpression"}).text = '="PT0.25S"'

    shapes = {e.get("bpmnElement"): e.find(f"{{{DC}}}Bounds") for e in root.iter(f"{{{D}}}BPMNShape")}
    x = max(float(shapes[e.get("id")].get("x")) + float(shapes[e.get("id")].get("width"))
            for e in process if e.get("id") in shapes) + 150
    y = float(shapes["TaskKnown"].get("y")) + 110
    plane = root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane")
    for node_id, offset, size in (("LookupTimeLeft", 0, 50), ("WaitForIndex", 150, 36)):
        shape = ET.SubElement(plane, f"{{{D}}}BPMNShape", {"id": node_id + "_di", "bpmnElement": node_id})
        ET.SubElement(shape, f"{{{DC}}}Bounds",
                      {"x": str(x + offset), "y": str(y + (50 - size) / 2),
                       "width": str(size), "height": str(size)})
    shape = ET.SubElement(plane, f"{{{D}}}BPMNShape", {"id": "LookupJoin_di", "bpmnElement": "LookupJoin"})
    search = shapes["FindTask"]
    ET.SubElement(shape, f"{{{DC}}}Bounds",
                  {"x": str(float(search.get("x")) - 43),
                   "y": str(float(search.get("y")) + (float(search.get("height")) - 36) / 2),
                   "width": "36", "height": "36"})
    for participant in root.iter(f"{{{B}}}participant"):
        if participant.get("processRef") == "a2a-rpc":
            bounds = shapes[participant.get("id")]
            bounds.set("width", str(max(float(bounds.get("width")), x + 220 - float(bounds.get("x")))))

    remove(root, {"Flow_TaskKnown_NotFoundJoin", "Flow_PrepareLookup_FindTask"})
    connect(root, "a2a-rpc", "PrepareLookup", "LookupJoin")
    connect(root, "a2a-rpc", "LookupJoin", "FindTask")
    connect(root, "a2a-rpc", "TaskKnown", "LookupTimeLeft", default=True, name="not indexed")
    connect(root, "a2a-rpc", "LookupTimeLeft", "WaitForIndex",
            condition="=now() < date and time(lookup.indexDeadline)", name="retry")
    connect(root, "a2a-rpc", "LookupTimeLeft", "NotFoundJoin", default=True, name="expired")
    connect(root, "a2a-rpc", "WaitForIndex", "LookupJoin")


def response_mode(root):
    update = next(e for e in root.iter() if e.get("id") == "ApplyOutcome").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    expression = update.get("expression")
    marker = "{id: task.id, contextId: task.contextId, rev:"
    assert expression.count(marker) == 1, "Task outcome source changed"
    update.set("expression", expression.replace(marker,
        '{responseMode: if o.responseMode = "message" then "message" else "task", '
        'id: task.id, contextId: task.contextId, rev:', 1))
    for element, fallback in (("BuildNewTaskResponse", "lookup.task"), ("BuildFollowUpResponse", "task")):
        script = next(e for e in root.iter() if e.get("id") == element).find(
            f"{{{B}}}extensionElements/{{{Z}}}script")
        result = ('if task.responseMode = "message" and task.status.state = "TASK_STATE_COMPLETED" '
                  'and task.status.message != null and count(task.artifacts) = 0 '
                  'then {message: task.status.message} else ' + feel.wrapped("ctx.hl", '"task"'))
        script.set("expression", "=(for task in [if seen != null then seen else %s] return %s)[1]"
                   % (fallback, feel.result(result)))


def cancellation(root):
    remove(root, {"MarkCanceled", "StoreCanceled", "CancelAgent", "TaskGone", "AgentGone", "CancelSent",
                  "Flow_AwaitCanceled_BuildCanceledView"})
    process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-rpc")
    request = ET.SubElement(process, f"{{{B}}}callActivity", id="RequestCancellation",
                            name="Request atomic cancellation")
    extensions = ET.SubElement(request, f"{{{B}}}extensionElements")
    ET.SubElement(extensions, f"{{{Z}}}calledElement", processId="a2a-correlate",
                  propagateAllChildVariables="false", propagateAllParentVariables="false")
    mapping = ET.SubElement(extensions, f"{{{Z}}}ioMapping")
    for target, source in (("messageName", '="a2a-cancel"'), ("taskId", "=task.id"),
                           ("tries", "=3"), ("payload", "={}")):
        ET.SubElement(mapping, f"{{{Z}}}input", target=target, source=source)
    ET.SubElement(mapping, f"{{{Z}}}output", source="=correlated", target="correlated")
    ET.SubElement(process, f"{{{B}}}exclusiveGateway", id="CancellationOutcome",
                  name="Terminal outcome visible?")
    timeout = ET.SubElement(process, f"{{{B}}}scriptTask", id="CancellationTimeout",
                            name="Report cancellation visibility failure")
    extension = ET.SubElement(timeout, f"{{{B}}}extensionElements")
    ET.SubElement(extension, f"{{{Z}}}script", resultVariable="rpcResponse", expression="=" + feel.resp_from(
        feel.err(-32603, "Cancellation outcome was not visible before the deadline", "DEADLINE_EXCEEDED")))
    ET.SubElement(process, f"{{{B}}}endEvent", id="CancellationErrorReady", name="Cancellation failed")
    plane = root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane")
    for identifier, x, y, width, height in (
            ("RequestCancellation", 2200, 1120, 100, 80),
            ("CancellationOutcome", 3100, 1135, 50, 50),
            ("CancellationTimeout", 3100, 1240, 100, 80),
            ("CancellationErrorReady", 3282, 1262, 36, 36)):
        shape = ET.SubElement(plane, f"{{{D}}}BPMNShape", id=identifier + "_di", bpmnElement=identifier)
        ET.SubElement(shape, f"{{{DC}}}Bounds", x=str(x), y=str(y), width=str(width), height=str(height))
    connect(root, "a2a-rpc", "Cancelable", "RequestCancellation",
            condition=f"=not(list contains({feel.TERMINAL}, task.status.state))", name="active")
    connect(root, "a2a-rpc", "RequestCancellation", "AwaitCanceled")
    connect(root, "a2a-rpc", "AwaitCanceled", "CancellationOutcome")
    connect(root, "a2a-rpc", "CancellationOutcome", "BuildCanceledView",
            condition='=visible and seen.status.state = "TASK_STATE_CANCELED"', name="canceled")
    connect(root, "a2a-rpc", "CancellationOutcome", "NotCancelableJoin",
            condition=f'=seen != null and seen.status.state != "TASK_STATE_CANCELED" and '
                      f'((visible and list contains({feel.TERMINAL}, seen.status.state)) or not(correlated))',
            name="not canceled")
    connect(root, "a2a-rpc", "CancellationOutcome", "CancellationTimeout", default=True, name="not visible")
    connect(root, "a2a-rpc", "CancellationTimeout", "CancellationErrorReady")
    waiter = next(e for e in process if e.get("id") == "AwaitCanceled")
    next(e for e in waiter.iter(f"{{{Z}}}input") if e.get("target") == "until").set(
        "source", '={kind: "task", minRev: task.rev + 1, settled: true}')
    script = next(e for e in process if e.get("id") == "BuildCanceledView").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    script.set("expression", "=" + feel.result(feel.view("null", "seen")))
    script = next(e for e in process if e.get("id") == "BuildNotCancelable").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    script.set("expression", "=" + feel.resp_from(feel.err(
        -32002, "Task is terminal or its process did not accept the required a2a-cancel message",
        "TASK_NOT_CANCELABLE")))
    correlate = next(e for e in root.iter() if e.get("id") == "CorrelateMessage")
    correlate.find(f"{{{B}}}extensionElements/{{{Z}}}taskDefinition").set("retries", "1")
    headers = correlate.find(f"{{{B}}}extensionElements/{{{Z}}}taskHeaders")
    for header in list(headers):
        if header.get("key") == "retryBackoff":
            headers.remove(header)


def pagination(root):
    process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-rpc")
    originals = {identifier: deepcopy(next(e for e in process if e.get("id") == identifier))
                 for identifier in ("SearchTasks", "ReadTasks")}
    shapes = {e.get("bpmnElement"): deepcopy(e.find(f"{{{DC}}}Bounds"))
              for e in root.iter(f"{{{D}}}BPMNShape")}
    collector = Proc("a2a-list-collect", "A2A collect indexed task pages")
    collector.start("ListScanRequested", "Collect tasks", 150, 162)
    collector.script("StartListScan", "Start bounded scan", 230, 140,
                     '={items: [], keys: [], cursor: null, cursors: [], '
                     'deadline: string(now() + duration("PT10S"))}', "listScan")
    collector.xor("ListProcessPageJoin", "", 350, 155)
    collector.node("serviceTask", "SearchTasks", "Search next process page", 430, 140)
    collector.xor("AnyTasks", "Any tasks?", 580, 155)
    collector.xor("ListVariablesJoin", "", 660, 155)
    collector.node("serviceTask", "ReadTasks", "Read complete root-state batch", 740, 140)
    collector.xor("ListBatchJoin", "", 880, 155)
    collector.script("CollectListBatch", "Validate and collect batch", 960, 140,
        '=(for ready in [if count(taskKeys) = 0 then true else '
        'taskBatch instance of list and count(distinct values(taskKeys)) = count(taskKeys) '
        'and count(taskBatch) = count(taskKeys) and '
        'count(distinct values(taskBatch.scopeKey)) = count(taskKeys) and '
        '(every i in taskBatch satisfies i.scopeKey = i.processInstanceKey and '
        'list contains(taskKeys, i.scopeKey) and i.value instance of context and '
        'i.value.id instance of string and i.value.contextId instance of string and '
        'i.value.rev instance of number and i.value.status instance of context and '
        'i.value.status.state instance of string and i.value.status.timestamp instance of string and '
        'i.value.history instance of list and i.value.artifacts instance of list)] '
        'return for overlap in [some k in taskKeys satisfies list contains(listScan.keys, k)] '
        'return for nextOk in [listPage.cursor instance of string and listPage.cursor != "" and '
        'not(list contains(listScan.cursors, listPage.cursor))] '
        'return for action in [if not(ready) then '
        '(if now() >= date and time(listScan.deadline) then "deadline" else "variables") '
        'else if overlap then "overlap" else if listPage.count < 100 then "done" '
        'else if listPage.count != 100 or not(nextOk) then "cursor" '
        'else if now() >= date and time(listScan.deadline) then "deadline" else "page"] '
        'return context merge([listScan, {action: action, '
        'items: if ready and not(overlap) and count(taskKeys) > 0 '
        'then concatenate(listScan.items, taskBatch) else listScan.items, '
        'keys: if ready then concatenate(listScan.keys, taskKeys) else listScan.keys, '
        'cursor: if action = "page" then listPage.cursor else listScan.cursor, '
        'cursors: if action = "page" then append(listScan.cursors, listPage.cursor) else listScan.cursors}]))'
        '[1][1][1][1]', "listScan")
    collector.xor("ListScanDecision", "Scan outcome?", 1100, 155)
    collector.script("FinishListScan", "Return complete collection", 1240, 140,
                     '={items: listScan.items, failure: null}', "listing")
    collector.xor("ListResultJoin", "", 1400, 155)
    collector.end("ListScanReady", "Collection ready", 1480, 162)
    collector.catch_timer("WaitListVariables", "Await root-state index", 1107, 302, '="PT0.25S"')
    failure = ('if listScan.action = "deadline" then '
               + feel.err(-32603, "Task listing did not become complete before the deadline", "DEADLINE_EXCEEDED")
               + " else " + feel.err(-32603, "Task search pagination did not make progress", "DATA_LOSS"))
    collector.script("FailListScan", "Reject incomplete collection", 1240, 290,
                     '={items: [], failure: ' + failure + '}', "listing")
    collector.flow("ListScanRequested", "StartListScan")
    collector.flow("StartListScan", "ListProcessPageJoin")
    collector.flow("ListProcessPageJoin", "SearchTasks")
    collector.flow("SearchTasks", "AnyTasks")
    collector.flow("AnyTasks", "ListVariablesJoin", "read", "=count(taskKeys) > 0")
    collector.flow("ListVariablesJoin", "ReadTasks")
    collector.flow("AnyTasks", "ListBatchJoin", "empty", default=True, route="over:60")
    collector.flow("ReadTasks", "ListBatchJoin")
    collector.flow("ListBatchJoin", "CollectListBatch")
    collector.flow("CollectListBatch", "ListScanDecision")
    collector.flow("ListScanDecision", "FinishListScan", "complete", '=listScan.action = "done"')
    collector.flow("ListScanDecision", "ListProcessPageJoin", "next page", '=listScan.action = "page"', route="over:100")
    collector.flow("ListScanDecision", "WaitListVariables", "retry state", '=listScan.action = "variables"')
    collector.flow("WaitListVariables", "ListVariablesJoin", route="back:60")
    collector.flow("ListScanDecision", "FailListScan", "incomplete", default=True)
    collector.flow("FinishListScan", "ListResultJoin")
    collector.flow("FailListScan", "ListResultJoin")
    collector.flow("ListResultJoin", "ListScanReady")
    bottom = max(float(bounds.get("y")) + float(bounds.get("height")) for bounds in shapes.values())
    collector._shift(0, bottom + 200)
    helper = ET.fromstring(collector.xml())
    helper_process = helper.find(f"{{{B}}}process")
    for identifier, original in originals.items():
        placeholder = next(e for e in helper_process if e.get("id") == identifier)
        for reference in list(original):
            if reference.tag in (f"{{{B}}}incoming", f"{{{B}}}outgoing"):
                original.remove(reference)
        original.extend(deepcopy(reference) for reference in placeholder)
        original.set("name", placeholder.get("name"))
        helper_process.insert(list(helper_process).index(placeholder), original)
        helper_process.remove(placeholder)
    search = next(e for e in helper_process if e.get("id") == "SearchTasks")
    body = next(e for e in search.iter(f"{{{Z}}}input") if e.get("target") == "body")
    body.set("source", body.get("source").replace(
        'order: "DESC"}]', 'order: "DESC"}, {field: "processInstanceKey", order: "DESC"}]').replace(
        "page: {limit: 100}", "page: {limit: 100, after: listScan.cursor}"))
    header = next(e for e in search.iter(f"{{{Z}}}header") if e.get("key") == "resultExpression")
    header.set("value", "={taskKeys: for i in response.body.items return i.processInstanceKey, "
               "listPage: {count: count(response.body.items), cursor: response.body.page.endCursor}}")
    remove(root, {"SearchTasks", "AnyTasks", "ReadTasks", "ListJoin"})
    call = ET.SubElement(process, f"{{{B}}}callActivity", id="CollectTaskList", name="Collect all task pages")
    extension = ET.SubElement(call, f"{{{B}}}extensionElements")
    ET.SubElement(extension, f"{{{Z}}}calledElement", processId="a2a-list-collect",
                  propagateAllChildVariables="false", propagateAllParentVariables="false")
    mapping = ET.SubElement(extension, f"{{{Z}}}ioMapping")
    ET.SubElement(mapping, f"{{{Z}}}input", source="=listReq", target="listReq")
    for source, target in (("=listing.items", "taskItems"), ("=listing.failure", "listFailure")):
        ET.SubElement(mapping, f"{{{Z}}}output", source=source, target=target)
    ET.SubElement(process, f"{{{B}}}exclusiveGateway", id="ListCollected", name="Complete task collection?")
    error = ET.SubElement(process, f"{{{B}}}scriptTask", id="BuildListFailure", name="Report incomplete task list")
    extension = ET.SubElement(error, f"{{{B}}}extensionElements")
    ET.SubElement(extension, f"{{{Z}}}script", resultVariable="rpcResponse",
                  expression="=" + feel.resp_from("listFailure"))
    ET.SubElement(process, f"{{{B}}}endEvent", id="ListFailureReady", name="Listing failed")
    plane = root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane")
    for identifier, original, width in (("CollectTaskList", "SearchTasks", 100),
                                         ("ListCollected", "AnyTasks", 50),
                                         ("BuildListFailure", "ReadTasks", 100),
                                         ("ListFailureReady", "ListJoin", 36)):
        shape = ET.SubElement(plane, f"{{{D}}}BPMNShape", id=identifier + "_di", bpmnElement=identifier)
        bounds = deepcopy(shapes[original])
        bounds.set("width", str(width))
        bounds.set("height", str(80 if width == 100 else width))
        shape.append(bounds)
    connect(root, "a2a-rpc", "PrepareList", "CollectTaskList")
    connect(root, "a2a-rpc", "CollectTaskList", "ListCollected")
    connect(root, "a2a-rpc", "ListCollected", "BuildTaskList", condition="=listFailure = null", name="complete")
    connect(root, "a2a-rpc", "ListCollected", "BuildListFailure", default=True, name="incomplete")
    connect(root, "a2a-rpc", "BuildListFailure", "ListFailureReady")
    script = next(e for e in process if e.get("id") == "BuildTaskList").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    script.set("expression", script.get("expression").replace(
        "function(a, b) a.status.timestamp > b.status.timestamp",
        "function(a, b) if a.status.timestamp = b.status.timestamp then a.id > b.id "
        "else a.status.timestamp > b.status.timestamp"))
    root.insert(list(root).index(root.find(f"{{{D}}}BPMNDiagram")), helper_process)
    pool_id = "Pool_a2a-list-collect"
    ET.SubElement(root.find(f"{{{B}}}collaboration"), f"{{{B}}}participant",
                  id=pool_id, name="Collect all indexed task pages", processRef=collector.pid)
    pool = ET.SubElement(plane, f"{{{D}}}BPMNShape", id=pool_id + "_di", bpmnElement=pool_id, isHorizontal="true")
    _, _, right, low = collector.bbox()
    ET.SubElement(pool, f"{{{DC}}}Bounds", x="60", y=str(bottom + 180),
                  width=str(max(right + 100, max(float(b.get("width")) for b in shapes.values()))),
                  height=str(low - bottom - 100))
    plane.extend(helper.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane"))


def card_response_expression(agent_path):
    skills = skills_feel(skills_from_bpmn(agent_path))
    return feel.one("""={statusCode: 200, headers: {"Content-Type": "application/json"},
      body: {name: "Synthetic card-dispute reviewer", version: "0.1.0",
        description: "Non-production community demonstration. Reconciles synthetic charges for human review; "
                     + "performs no financial actions.",
        provider: {organization: "HanselIdes", url: "https://github.com/HanselIdes/camunda-a2a"},
        supportedInterfaces: [{url: "{{secrets.A2A_RPC_URL}}", protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
        capabilities: {streaming: false, pushNotifications: false, extendedAgentCard: false},
        defaultInputModes: ["text/plain"], defaultOutputModes: ["text/plain", "application/json"],
        securitySchemes: {a2aApiKey: {apiKeySecurityScheme: {location: "header", name: "X-A2A-Api-Key"}}},
        securityRequirements: [{schemes: {a2aApiKey: {}}}],
        skills: %s}}""" % skills)


def add_card_endpoint(root, agent_path):
    process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-rpc")
    message = ET.SubElement(root, f"{{{B}}}message", {
        "id": "AgentCardRequestMessage",
        "name": "Agent Card request",
    })
    start = ET.SubElement(process, f"{{{B}}}startEvent", {
        "id": "CardRequested",
        "name": "Agent Card requested",
        f"{{{Z}}}modelerTemplate": "dev.hansel.a2a.core.card.v1",
        f"{{{Z}}}modelerTemplateVersion": "1",
    })
    extension = ET.SubElement(start, f"{{{B}}}extensionElements")
    properties = ET.SubElement(extension, f"{{{Z}}}properties")
    for name, value in {
        "inbound.type": "io.camunda:webhook:1",
        "inbound.context": "a2a-card",
        "inbound.auth.type": "NONE",
        "inbound.method": "get",
        "inbound.responseExpression": card_response_expression(agent_path),
    }.items():
        ET.SubElement(properties, f"{{{Z}}}property", {"name": name, "value": value})
    end = ET.SubElement(process, f"{{{B}}}endEvent", {"id": "CardServed", "name": "Card served"})
    flow_id = "Flow_CardRequested_CardServed"
    ET.SubElement(process, f"{{{B}}}sequenceFlow", {
        "id": flow_id, "sourceRef": "CardRequested", "targetRef": "CardServed"
    })
    ET.SubElement(start, f"{{{B}}}outgoing").text = flow_id
    ET.SubElement(end, f"{{{B}}}incoming").text = flow_id
    ET.SubElement(start, f"{{{B}}}messageEventDefinition", {
        "id": "CardRequested_message",
        "messageRef": message.get("id"),
    })


def build(authentication, agent_path=None):
    root = ET.parse(ROOT / "bpmn/a2a-protocol.bpmn").getroot()
    root.set("{http://camunda.org/schema/modeler/1.0}executionPlatformVersion", "8.9.0")
    if agent_path is None:
        agent_path = ROOT / "blueprint/demo/02-server-agent-card-dispute.bpmn"
        if not agent_path.exists():
            agent_path = ROOT / "blueprint/demo/02-server-agent-card-dispute.bpmn"
    for node in root.iter():
        node.attrib.pop(f"{{{Z}}}modelerTemplateIcon", None)
        if node.get(f"{{{Z}}}modelerTemplate") == "io.camunda.connectors.HttpJson.v2":
            node.set(f"{{{Z}}}modelerTemplateVersion", "12")
            for header in node.findall(f"{{{B}}}extensionElements/{{{Z}}}taskHeaders/{{{Z}}}header"):
                if header.get("key") == "elementTemplateVersion":
                    header.set("value", "12")
    remove(root, {
        "BuildDirectMessage", "DirectMessageReady", "FindPushConfigs", "AnyPushConfigs",
        "StartPushDelivery", "PushHandled", "FindCancelPush", "AnyCancelPush", "StartCancelPush",
        "CancelPushHandled", "HasInlinePush", "StoreInlineConfig", "AwaitInlineConfig", "InlinePushDone",
        "ReadConfigs", "PreparePushOp", "WriteConfig", "CreateConfig", "ReplaceConfig", "DeleteConfig",
        "ConfigGone", "ConfigWritten", "AwaitConfig", "ConfigVisible", "BuildPushResponse", "PushResponseReady",
        "PushFailed",
    })
    push_process = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-push-notify")
    push_ids = {e.get("id") for e in push_process.iter() if e.get("id")}
    push_participants = {e.get("id") for e in root.iter(f"{{{B}}}participant")
                         if e.get("processRef") == "a2a-push-notify"}
    remove(root, push_ids | push_participants)
    connect(root, "a2a-task-update", "ApplyOutcome", "TaskUpdated")
    connect(root, "a2a-rpc", "PrepareNewTask", "CreateTask")
    lookup_retry(root)
    response_mode(root)
    cancellation(root)
    pagination(root)
    parse = next(e for e in root.iter() if e.get("id") == "ParseRequest").find(
        f"{{{B}}}extensionElements/{{{Z}}}script")
    old_version = ('versionOk: if ver instance of string then '
                   '(ver = "" or ver = "1" or starts with(ver, "1.")) else true')
    assert old_version in parse.get("expression"), "Version validation source changed"
    parse.set("expression", parse.get("expression").replace(
        old_version, 'versionOk: if ver instance of string then matches(ver, "^1[.]0([.][0-9]+)?$") else false'))

    setting = next(e for e in root.iter() if e.get("id") == "ReadPushSetting")
    setting.tag = f"{{{B}}}scriptTask"
    setting.attrib.pop(f"{{{Z}}}modelerTemplate", None)
    setting.attrib.pop(f"{{{Z}}}modelerTemplateVersion", None)
    setting.remove(setting.find(f"{{{B}}}extensionElements"))
    extension = ET.Element(f"{{{B}}}extensionElements")
    ET.SubElement(extension, f"{{{Z}}}script", {"expression": "=false", "resultVariable": "pushEnabled"})
    setting.insert(0, extension)
    for condition in root.iter(f"{{{B}}}conditionExpression"):
        if condition.text and 'not(starts with(ctx.messageId, "tck-message-response"))' in condition.text:
            condition.text = '=verdict.route = "SendMessage" and ctx.taskId = null'
    for script in root.iter(f"{{{Z}}}script"):
        script.set("expression", script.get("expression", "").replace(
            "from json(items[1].value)", "items[1].value").replace("from json(i.value)", "i.value"))

    for node in root.iter(f"{{{B}}}serviceTask"):
        mapping = node.find(f"{{{B}}}extensionElements/{{{Z}}}ioMapping")
        if mapping is None:
            continue
        url = next((e for e in mapping if e.get("target") == "url"), None)
        if url is None or "secrets.ENGINE_URL" not in url.get("source", ""):
            continue
        auth = next(e for e in mapping if e.get("target") == "authentication.type")
        auth.set("source", "basic" if authentication == "basic" else "oauth-client-credentials-flow")
        fields = {"username": "ENGINE_USERNAME", "password": "ENGINE_PASSWORD"} if authentication == "basic" else {
            "oauthTokenEndpoint": "ENGINE_OAUTH_TOKEN_ENDPOINT", "clientId": "ENGINE_CLIENT_ID",
            "clientSecret": "ENGINE_CLIENT_SECRET", "audience": "ENGINE_AUDIENCE",
        }
        for field, secret in fields.items():
            ET.SubElement(mapping, f"{{{Z}}}input",
                          {"source": "{{secrets.%s}}" % secret, "target": "authentication." + field})
        if authentication == "oauth":
            ET.SubElement(mapping, f"{{{Z}}}input",
                          {"source": "body", "target": "authentication.clientAuthentication"})
        body = next((e for e in mapping if e.get("target") == "body"), None)
        if body is not None and "process-instances/search" in url.get("source", ""):
            body.set("source", body.get("source").replace(
                "filter: {", 'filter: {processDefinitionId: "{{secrets.A2A_AGENT_PROCESS}}", ', 1))
        if node.get("id") in ("ReadState", "ReadTasks"):
            for header in node.iter(f"{{{Z}}}header"):
                if header.get("key") == "resultExpression":
                    target = "items" if node.get("id") == "ReadState" else "taskBatch"
                    header.set("value", "={%s: for i in response.body.items return "
                               "context merge([i, {value: from json(i.value)}])}" % target)
    for properties in root.iter(f"{{{Z}}}properties"):
        if any(e.get("name") == "inbound.context" and e.get("value") == "a2a" for e in properties):
            next(e for e in properties if e.get("name") == "inbound.auth.type").set("value", "APIKEY")
            next(e for e in properties if e.get("name") == "resultExpression").set("value", REQUEST_MAPPING)
            ET.SubElement(properties, f"{{{Z}}}property",
                          {"name": "inbound.auth.apiKey", "value": "{{secrets.A2A_API_KEY}}"})
            ET.SubElement(properties, f"{{{Z}}}property",
                          {"name": "inbound.auth.apiKeyLocator", "value": '=request.headers.`x-a2a-api-key`'})
    rpc = next(e for e in root.iter() if e.get("id") == "RpcReceived")
    rpc.set(f"{{{Z}}}modelerTemplate", "dev.hansel.a2a.core.rpc.v1")
    rpc.set(f"{{{Z}}}modelerTemplateVersion", "1")
    server = next(p for p in root.findall(f"{{{B}}}process") if p.get("id") == "a2a-rpc")
    server.set("name", "01 A2A Server - Protocol and Discovery")
    for participant in root.iter(f"{{{B}}}participant"):
        if participant.get("processRef") == "a2a-rpc":
            participant.set("name", "01 A2A Server - Protocol and Discovery")
    add_card_endpoint(root, agent_path)
    ET.indent(root, space="  ")
    return layout_xml(ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authentication", choices=("basic", "oauth"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true", help="Check both committed profiles without changing files")
    args = parser.parse_args()
    if args.check:
        if args.authentication or args.output:
            parser.error("--check cannot be combined with --authentication or --output")
        stale = []
        for authentication in ("basic", "oauth"):
            path = ROOT / "blueprint/profiles" / authentication / "01-a2a-server.bpmn"
            if not path.exists() or path.read_bytes() != build(authentication):
                stale.append(authentication)
        if stale:
            parser.exit(1, "Regenerate stale core profiles: " + ", ".join(stale) + "\n")
        print("Both core profiles match the authoritative experiment diagram")
    else:
        if not args.authentication or not args.output:
            parser.error("--authentication and --output are required when not checking")
        args.output.write_bytes(build(args.authentication))
