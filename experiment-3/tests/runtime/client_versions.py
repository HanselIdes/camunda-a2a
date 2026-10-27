"""Engine-evaluated packaged-client patch handling plus native received headers."""
import json
import time
import xml.etree.ElementTree as ET

from observations import read_root_variable

Z = "http://camunda.org/schema/zeebe/1.0"


def run(root, reports, request, task_id, card):
    model = ET.parse(root / "blueprint/demo/a2a-client.bpmn")
    fetch = next(item for item in model.getroot().iter() if item.get("id") == "DiscoverAgent")
    expression = next(item.get("value") for item in fetch.iter(f"{{{Z}}}header")
                      if item.get("key") == "resultExpression")
    cases = []
    baseline = None
    for version in ("1.0", "1.0.2", "1.0.999"):
        candidate = json.loads(json.dumps(card))
        candidate["supportedInterfaces"][0]["protocolVersion"] = version
        status, body = request("/v2/expression/evaluation", {
            "expression": expression, "variables": {"response": {"body": candidate}}})
        assert status == 200, ("packaged client expression evaluation", status)
        result = json.loads(body)["result"]
        if baseline is None:
            baseline = result
        assert result == baseline and result["agentUrl"] == card["supportedInterfaces"][0]["url"], result
        cases.append({"advertisedVersion": version, "sameSelectedInterfaceAndContext": True})
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
        "headerProofScope": "Actual protocol root headers from supplied BPMN client requests, matched by result task ID.",
    }, indent=2) + "\n")
