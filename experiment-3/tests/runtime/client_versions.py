"""Engine-evaluated packaged-client patch handling plus native received headers."""
import json
from copy import deepcopy
import time
import xml.etree.ElementTree as ET

from observations import read_root_variable

Z = "http://camunda.org/schema/zeebe/1.0"
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"


def run(root, reports, request, deploy, task_id, card):
    model = ET.parse(root / "blueprint/demo/a2a-client.bpmn")
    fetch = next(item for item in model.getroot().iter() if item.get("id") == "DiscoverAgent")
    expression = next(item.get("value") for item in fetch.iter(f"{{{Z}}}header")
                      if item.get("key") == "resultExpression")
    ET.register_namespace("bpmn", B)
    definitions = ET.Element(f"{{{B}}}definitions", targetNamespace="urn:nonshipping-client-version-proof")
    process = ET.SubElement(definitions, f"{{{B}}}process", id="a2a-client-version-proof", isExecutable="true")
    ET.SubElement(process, f"{{{B}}}startEvent", id="Start")
    script = ET.SubElement(process, f"{{{B}}}scriptTask", id="EvaluatePackagedMapping")
    extensions = ET.SubElement(script, f"{{{B}}}extensionElements")
    ET.SubElement(extensions, f"{{{Z}}}script", expression=expression, resultVariable="versionResult")
    ET.SubElement(process, f"{{{B}}}endEvent", id="End")
    for source, target in (("Start", "EvaluatePackagedMapping"), ("EvaluatePackagedMapping", "End")):
        ET.SubElement(process, f"{{{B}}}sequenceFlow", id=source + target, sourceRef=source, targetRef=target)
    poll = ET.SubElement(definitions, f"{{{B}}}process", id="a2a-client-poll-proof", isExecutable="true")
    ET.SubElement(poll, f"{{{B}}}startEvent", id="PollStart")
    connector = deepcopy(next(item for item in model.getroot().iter() if item.get("id") == "GetTask"))
    for element in list(connector):
        if element.tag in (f"{{{B}}}incoming", f"{{{B}}}outgoing"):
            connector.remove(element)
    poll.append(connector)
    ET.SubElement(poll, f"{{{B}}}endEvent", id="PollEnd")
    for source, target in (("PollStart", "GetTask"), ("GetTask", "PollEnd")):
        ET.SubElement(poll, f"{{{B}}}sequenceFlow", id=source + target, sourceRef=source, targetRef=target)
    fixture = reports / "nonshipping-client-version-proof.bpmn"
    ET.ElementTree(definitions).write(fixture, encoding="utf-8", xml_declaration=True)
    deploy([fixture])
    cases = []
    baseline = None
    for version in ("1.0", "1.0.2", "1.0.999"):
        candidate = json.loads(json.dumps(card))
        candidate["supportedInterfaces"][0]["protocolVersion"] = version
        status, body = request("/v2/process-instances", {
            "processDefinitionId": "a2a-client-version-proof", "variables": {"response": {"body": candidate}}})
        assert status == 200, ("packaged client mapping proof start", status)
        result = read_root_variable(request, json.loads(body)["processInstanceKey"], "versionResult")
        if baseline is None:
            baseline = result
        assert result == baseline and result["agentUrl"] == card["supportedInterfaces"][0]["url"], result
        cases.append({"advertisedVersion": version, "sameSelectedInterfaceAndContext": True})
    status, body = request("/v2/process-instances", {
        "processDefinitionId": "a2a-client-poll-proof", "variables": {
            "agentUrl": card["supportedInterfaces"][0]["url"], "reply": {"taskId": task_id}}})
    assert status == 200, ("packaged polling connector proof start", status)
    polled = read_root_variable(request, json.loads(body)["processInstanceKey"], "rpc")
    assert polled["result"]["id"] == task_id, polled
    received = []
    deadline = time.monotonic() + 15
    while True:
        status, body = request("/v2/variables/search?truncateValues=false", {
            "filter": {"name": "rpcResponse"}, "page": {"limit": 100}})
        assert status == 200, ("client request observation", status)
        records = json.loads(body)
        assert len(records["items"]) < 100, "Client proof response scan requires pagination"
        received = []
        for item in records["items"]:
            if item["scopeKey"] != item["processInstanceKey"]:
                continue
            response = json.loads(item["value"])
            result = response.get("result", {})
            if result.get("task", result).get("id") != task_id:
                continue
            instance = item["processInstanceKey"]
            headers = read_root_variable(request, instance, "hdr")
            rpc = read_root_variable(request, instance, "rpc")
            assert headers.get("a2a-version") == "1.0", (rpc["method"], headers.get("a2a-version"))
            received.append({"method": rpc["method"], "protocolVersion": headers["a2a-version"]})
        if {item["method"] for item in received} >= {"SendMessage", "GetTask"}:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Did not observe both native BPMN client methods with version headers")
        time.sleep(0.25)
    (reports / "bpmn-client-versions.json").write_text(json.dumps({
        "verdict": "PASS", "patchNegotiation": cases, "receivedRequestVersions": received,
        "patchProofScope": "Packaged discovery expression evaluated by the actual engine with patch-varied cards.",
        "headerProofScope": "Actual protocol root headers from supplied BPMN client SendMessage and its exact "
                            "GetTask connector in an isolated stock-BPMN fixture, matched by result task ID.",
    }, indent=2) + "\n")
