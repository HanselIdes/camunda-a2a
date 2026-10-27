"""Nonshipping stock-connector failure injection and operator recovery."""
import json
import time
import uuid
import xml.etree.ElementTree as ET

from observations import read_root_variable
from operations import B, controlled_model

Z = "http://camunda.org/schema/zeebe/1.0"


def fault_model(source, target, mode):
    ET.register_namespace("bpmn", B)
    model = ET.parse(source)
    task = next(element for element in model.getroot().iter() if element.get("id") == "CreateTask")
    task.find(f"{{{B}}}extensionElements/{{{Z}}}taskDefinition").set("retries", "1")
    for element in task.iter(f"{{{Z}}}input"):
        field = element.get("target")
        if field in ("connectionTimeoutInSeconds", "readTimeoutInSeconds"):
            element.set("source", "=1")
        elif mode == "unavailable-engine" and field == "url":
            element.set("source", '="http://127.0.0.1:1/v2/process-instances"')
        elif mode == "invalid-credentials" and field == "authentication.password":
            element.set("source", "deliberately-invalid-noncredential")
        elif mode == "insufficient-permissions" and field == "authentication.username":
            element.set("source", "a2a-restricted-proof")
        elif mode == "insufficient-permissions" and field == "authentication.password":
            element.set("source", "{{secrets.PROOF_RESTRICTED_PASSWORD}}")
    model.write(target, encoding="utf-8", xml_declaration=True)


def run(root, reports, rpc, request, deploy, env):
    records = []
    protocol = root / "blueprint/profiles/basic/a2a-protocol.bpmn"
    echo = root / "bpmn/a2a-echo.bpmn"
    user = "a2a-restricted-proof"

    def save(verdict):
        (reports / "failure-checks.json").write_text(json.dumps({
            "verdict": verdict, "records": records,
            "credentialScope": "Basic authentication has no token expiry. Invalid and unprivileged credentials "
                               "are injected; expiring OAuth tokens are not covered.",
            "fixtures": "Derived nonshipping diagrams and stock engine APIs; no custom server/worker.",
        }, indent=2) + "\n")

    def wait(description, observe, predicate, seconds=45):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = observe()
            if predicate(last):
                return last
            time.sleep(0.25)
        raise TimeoutError(f"{description}: no matching observation within {seconds}s")

    def search(path, filter):
        status, body = request(path, {"filter": filter, "page": {"limit": 100}})
        assert status == 200, (path, status)
        return json.loads(body)["items"]

    def call(method, params):
        identifier = str(uuid.uuid4())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        assert status == 200 and isinstance(response, dict) and response.get("id") == identifier, (status, response)
        return response

    def send(text):
        response = call("SendMessage", {"message": {
            "messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]},
            "configuration": {"returnImmediately": True}})
        assert "result" in response, response
        task = response["result"]["task"]
        return wait("business terminal state", lambda: call("GetTask", {"id": task["id"]})["result"],
                    lambda value: value["status"]["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"),
                    seconds=300)

    save("RUNNING")
    created_user = False
    try:
        status, _ = request("/v2/users", {"username": user, "password": env["PROOF_RESTRICTED_PASSWORD"],
                                         "name": "Unprivileged isolated test user"})
        assert status == 201, ("restricted user creation", status)
        created_user = True
        for mode, expected_error in (("invalid-credentials", "401"), ("insufficient-permissions", "403"),
                                     ("unavailable-engine", None)):
            fault = reports / f"nonshipping-{mode}.bpmn"
            fault_model(protocol, fault, mode)
            deploy([fault])
            identifier = "failure-" + str(uuid.uuid4())
            text = "Exact recovered " + mode
            status, body = request("/v2/process-instances", {
                "processDefinitionId": "a2a-rpc", "variables": {
                    "hdr": {"content-type": "application/json", "a2a-version": "1.0"},
                    "rpc": {"jsonrpc": "2.0", "id": identifier, "method": "SendMessage", "params": {
                        "message": {"messageId": identifier, "role": "ROLE_USER", "parts": [{"text": text}]}}}}})
            assert status == 200, ("RPC handler start", status)
            instance = json.loads(body)["processInstanceKey"]
            incident = wait("operator-visible connector failure",
                lambda: search("/v2/incidents/search", {"processInstanceKey": instance, "state": "ACTIVE"}), bool)[0]
            assert incident["elementId"] == "CreateTask" and incident["errorType"] == "JOB_NO_RETRIES", incident
            if expected_error:
                assert expected_error in incident["errorMessage"], (mode, incident["errorType"])
            assert not search("/v2/variables/search", {"processInstanceKey": instance, "name": "rpcResponse"}), \
                "Infrastructure failure invented an RPC response"
            assert incident["jobKey"] and incident["elementInstanceKey"], "Incident lacks actionable job references"
            status, _ = request(f'/v2/element-instances/{incident["elementInstanceKey"]}/variables', {
                "local": True, "variables": {
                    "url": "http://camunda:8080/v2/process-instances",
                    "authentication": {"type": "basic", "username": "proof",
                                       "password": "{{secrets.ENGINE_PASSWORD}}"}}}, method="PUT")
            assert status == 204, ("repair connector variables", status)
            status, _ = request(f'/v2/jobs/{incident["jobKey"]}', {"changeset": {"retries": 1}}, method="PATCH")
            assert status == 204, ("restore job retry", status)
            status, _ = request(f'/v2/incidents/{incident["incidentKey"]}/resolution', {}, method="POST")
            assert status in (204, 404), ("resolve incident", status)
            response = read_root_variable(request, instance, "rpcResponse", seconds=45)
            assert response.get("id") == identifier and "error" not in response, response
            task = response["result"]["task"]
            assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
            assert task["status"]["message"]["parts"] == [{"text": text}], task
            assert call("GetTask", {"id": task["id"]})["result"] == task
            wait("incident resolution", lambda: search("/v2/incidents/search", {
                "processInstanceKey": instance, "state": "ACTIVE"}), lambda values: not values)
            records.append({"case": mode, "incidentElement": "CreateTask", "errorType": "JOB_NO_RETRIES",
                            "expectedHttpError": expected_error, "noFabricatedResponse": True,
                            "operatorRepair": "Local connector inputs, job retry, incident resolution",
                            "recoveredExactTask": True})
        deploy([protocol])
        for mode in ("unavailable-model-endpoint", "unknown-model"):
            derived = reports / f"nonshipping-{mode}.bpmn"
            controlled_model(root / "blueprint/demo/a2a-card-dispute.bpmn", derived, "a2a-echo")
            model = ET.parse(derived)
            target = ("provider.openaiCompatible.endpoint" if mode == "unavailable-model-endpoint"
                      else "provider.openaiCompatible.model.model")
            for element in model.getroot().iter(f"{{{Z}}}input"):
                if element.get("target") == target:
                    element.set("source", "http://127.0.0.1:1/v1" if mode == "unavailable-model-endpoint"
                                else "nonexistent-a2a-proof-model")
            model.write(derived, encoding="utf-8", xml_declaration=True)
            deploy([derived])
            failed = send("49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD.")
            assert failed["status"]["state"] == "TASK_STATE_FAILED", failed
            assert failed["status"]["message"]["parts"] == [{"text": "The agent could not complete the request."}]
            assert not failed.get("artifacts"), failed
            assert not search("/v2/incidents/search", {"state": "ACTIVE"}), "Model error escaped its BPMN boundary"
            records.append({"case": mode, "state": "TASK_STATE_FAILED", "noArtifacts": True,
                            "notOrdinaryUncertainty": True})
        repaired = reports / "nonshipping-repaired-agent.bpmn"
        controlled_model(root / "blueprint/demo/a2a-card-dispute.bpmn", repaired, "a2a-echo")
        deploy([repaired])
        completed = send("49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD.")
        assert completed["status"]["state"] == "TASK_STATE_COMPLETED", completed
        evidence = next(item for item in completed["artifacts"] if item["name"] == "reconciliation")["parts"][0]["data"]
        assert evidence == {
            "merchant": "Northwind Electronics", "currency": "USD", "chargeAmounts": [49.95, 49.95],
            "expectedAmount": 49.95, "paidAmount": 99.9, "overchargeAmount": 49.95,
            "matchingAmounts": True, "recommendation": "REQUEST_HUMAN_REVIEW", "syntheticOnly": True}, evidence
        records.append({"case": "model-configuration-repair", "exactReconciliation": True})
        save("PASS")
        print("Native connector/model failure injection and operator recovery: PASS", flush=True)
    except Exception:
        save("FAIL")
        raise
    finally:
        deploy([protocol, echo])
        if created_user:
            status, _ = request(f"/v2/users/{user}", method="DELETE")
            assert status == 204, ("restricted user cleanup", status)
