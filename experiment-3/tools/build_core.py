#!/usr/bin/env python3
"""Build the push-disabled protocol from the authoritative experiment diagram.

Preserves the layout of surviving elements. Adopters deploy the committed output;
this command is only for contributors changing the protocol.
"""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z = "http://camunda.org/schema/zeebe/1.0"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
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


def build(authentication):
    root = ET.parse(ROOT / "bpmn/a2a-protocol.bpmn").getroot()
    root.set("{http://camunda.org/schema/modeler/1.0}executionPlatformVersion", "8.8.0")
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
    connect(root, "a2a-rpc", "AwaitCanceled", "BuildCanceledView")
    connect(root, "a2a-rpc", "PrepareNewTask", "CreateTask")
    lookup_retry(root)

    setting = next(e for e in root.iter() if e.get("id") == "ReadPushSetting")
    setting.tag = f"{{{B}}}scriptTask"
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
                    target = "items" if node.get("id") == "ReadState" else "taskItems"
                    header.set("value", "={%s: for i in response.body.items return "
                               "context merge([i, {value: from json(i.value)}])}" % target)
    for properties in root.iter(f"{{{Z}}}properties"):
        if any(e.get("name") == "inbound.context" and e.get("value") == "a2a" for e in properties):
            next(e for e in properties if e.get("name") == "inbound.auth.type").set("value", "APIKEY")
            ET.SubElement(properties, f"{{{Z}}}property",
                          {"name": "inbound.auth.apiKey", "value": "{{secrets.A2A_API_KEY}}"})
            ET.SubElement(properties, f"{{{Z}}}property",
                          {"name": "inbound.auth.apiKeyLocator", "value": '=request.headers.`x-a2a-api-key`'})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n"


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
            path = ROOT / "blueprint/profiles" / authentication / "a2a-protocol.bpmn"
            if not path.exists() or path.read_bytes() != build(authentication):
                stale.append(authentication)
        if stale:
            parser.exit(1, "Regenerate stale core profiles: " + ", ".join(stale) + "\n")
        print("Both core profiles match the authoritative experiment diagram")
    else:
        if not args.authentication or not args.output:
            parser.error("--authentication and --output are required when not checking")
        args.output.write_bytes(build(args.authentication))
