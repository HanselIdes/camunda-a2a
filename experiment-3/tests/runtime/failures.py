"""Nonshipping stock-connector failure injection and operator recovery."""
import base64
import http.client
import json
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
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
        elif mode == "unreachable-engine-endpoint" and field == "url":
            element.set("source", '="http://127.0.0.1:1/v2/process-instances"')
        elif mode == "invalid-credentials" and field == "authentication.password":
            element.set("source", "deliberately-invalid-noncredential")
        elif mode in ("insufficient-permissions", "revoked-credentials") and field == "authentication.username":
            element.set("source", "a2a-restricted-proof")
        elif mode in ("insufficient-permissions", "revoked-credentials") and field == "authentication.password":
            element.set("source", "{{secrets.PROOF_RESTRICTED_PASSWORD}}")
    model.write(target, encoding="utf-8", xml_declaration=True)


def run(root, reports, rpc, request, deploy, env, stack):
    records = []
    protocol = root / "blueprint/profiles/basic/a2a-protocol.bpmn"
    echo = root / "bpmn/a2a-echo.bpmn"
    user = "a2a-restricted-proof"

    def save(verdict):
        (reports / "failure-checks.json").write_text(json.dumps({
            "verdict": verdict, "records": records,
            "credentialScope": "Basic authentication has no token expiry. Invalid and unprivileged credentials "
                               "and password-rotated credentials are injected; expiring OAuth tokens are not covered.",
            "fixtures": "Derived nonshipping diagrams and stock engine APIs, plus a shipped-protocol "
                        "deployment-secret fault; no custom server/worker.",
            "inputFaultScope": "Derived CreateTask inputs, retries=1 and 1s timeouts. Handler started via engine "
                               "API; no webhook response claimed for these cases. Local job-input repair only.",
            "endpointFaultScope": "Only the connector endpoint is unreachable; the engine remains running. "
                                  "This is not engine-outage or restart evidence.",
            "modelFaultScope": "Derived provider inputs; handlers started via engine API and tasks polled over A2A.",
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

    def search(path, filter=None):
        body = {"page": {"limit": 100}}
        if filter is not None:
            body["filter"] = filter
        status, body = request(path, body)
        assert status == 200, (path, status)
        return json.loads(body)["items"]

    def stale_credential_status(path="/v2/users/search", body=b'{"page":{"limit":1}}'):
        token = base64.b64encode((user + ":" + env["PROOF_RESTRICTED_PASSWORD"]).encode()).decode()
        probe = urllib.request.Request("http://127.0.0.1:" + env["PROOF_ENGINE_PORT"] + path,
                                       data=body,
                                       headers={"Authorization": "Basic " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(probe, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def restart_connectors():
        subprocess.run(stack.command + ["up", "-d", "--no-deps", "--force-recreate", "--wait",
                                       "--wait-timeout", "300", "connectors"], env=env, check=True,
                       capture_output=True)

        def ready():
            try:
                status, _ = rpc({"jsonrpc": "2.0", "id": "readiness-no-work", "method": "GetTask",
                                 "params": {"id": "readiness-no-work"}}, key=False, timeout=5)
            except (urllib.error.URLError, http.client.RemoteDisconnected):
                return False
            assert status in (401, 404), ("unexpected unauthenticated readiness status", status)
            return status == 401

        wait("owned Connectors TLS/webhook readiness after recreation", ready, bool, seconds=120)
        print("Owned Connectors TLS endpoint and API-key rejection ready after recreation", flush=True)

    def call(method, params):
        identifier = str(uuid.uuid4())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        assert status == 200 and isinstance(response, dict) and response.get("id") == identifier, (status, response)
        return response

    def send(text):
        identifier = str(uuid.uuid4())
        status, body = request("/v2/process-instances", {
            "processDefinitionId": "a2a-rpc", "variables": {
                "hdr": {"content-type": "application/json", "a2a-version": "1.0"},
                "rpc": {"jsonrpc": "2.0", "id": identifier, "method": "SendMessage", "params": {
                    "message": {"messageId": identifier, "role": "ROLE_USER", "parts": [{"text": text}]},
                    "configuration": {"returnImmediately": True}}}}})
        assert status == 200, ("model-fault handler start", status)
        response = read_root_variable(request, json.loads(body)["processInstanceKey"], "rpcResponse", seconds=45)
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
                                     ("revoked-credentials", "401"), ("unreachable-engine-endpoint", None)):
            if mode == "revoked-credentials":
                status, _ = request(f"/v2/users/{user}", {"password": secrets.token_urlsafe(32)}, method="PUT")
                assert status == 200, ("revoke old password", status)
                wait("rotated password becomes invalid", stale_credential_status, lambda value: value == 401)
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
        for mode, expected_error in (("deployment-engine-password-secret", "401"),
                                     ("deployment-user-missing-permission", "403")):
            if expected_error == "401":
                env["PROOF_PROTOCOL_ENGINE_PASSWORD"] = "deliberately-invalid-noncredential"
            else:
                status, _ = request(f"/v2/users/{user}", {"password": env["PROOF_RESTRICTED_PASSWORD"]}, method="PUT")
                assert status == 200, ("restore test user's valid password", status)
                wait("test user's restored credential is valid", stale_credential_status, lambda value: value == 200)
                assert user not in [item["username"] for item in search("/v2/roles/admin/users/search")]
                env["PROOF_PROTOCOL_ENGINE_USERNAME"] = user
                env["PROOF_PROTOCOL_ENGINE_PASSWORD"] = env["PROOF_RESTRICTED_PASSWORD"]
            restart_connectors()
            identifier = "deployment-failure-" + str(uuid.uuid4())
            text = "Exact result after " + mode + " repair"
            started = time.monotonic()
            try:
                response = rpc({"jsonrpc": "2.0", "id": identifier, "method": "SendMessage", "params": {
                    "message": {"messageId": identifier, "role": "ROLE_USER", "parts": [{"text": text}]}}},
                    timeout=5)
            except (TimeoutError, socket.timeout):
                client_observation = "five-second-client-timeout"
            else:
                raise AssertionError(f"Expected client timeout rather than a fabricated response: {response[0]}")
            incident = wait("deployment failure after shipped retries",
                lambda: search("/v2/incidents/search", {"processDefinitionId": "a2a-rpc", "state": "ACTIVE"}),
                bool, seconds=120)[0]
            assert incident["elementId"] == "CreateTask" and incident["errorType"] == "JOB_NO_RETRIES", incident
            assert expected_error in incident["errorMessage"]
            instance = incident["processInstanceKey"]
            assert read_root_variable(request, instance, "rpc")["id"] == identifier
            assert not search("/v2/variables/search", {"processInstanceKey": instance, "name": "rpcResponse"})
            incident_seconds = time.monotonic() - started
            if expected_error == "401":
                env.pop("PROOF_PROTOCOL_ENGINE_PASSWORD")
                restart_connectors()
                repair = "Correct ENGINE_PASSWORD, recreate owned Connectors, retry and resolve"
            else:
                status, _ = request(f"/v2/roles/admin/users/{user}", method="PUT")
                assert status == 204, ("grant test user role", status)
                wait("test authorization grant visible",
                     lambda: search("/v2/roles/admin/users/search"),
                     lambda values: user in [item["username"] for item in values])
                wait("test user's granted process access effective",
                     lambda: stale_credential_status(f"/v2/process-instances/{instance}", body=None),
                     lambda status: status == 200, seconds=120)
                status, _ = request("/v2/authorizations", {
                    "ownerId": user, "ownerType": "USER", "resourceType": "PROCESS_DEFINITION",
                    "resourceId": "a2a-echo", "permissionTypes": ["CREATE_PROCESS_INSTANCE"]})
                assert status == 201, ("grant explicit business-start permission", status)
                wait("explicit business-start grant indexed",
                     lambda: search("/v2/authorizations/search", {
                         "ownerId": user, "ownerType": "USER", "resourceType": "PROCESS_DEFINITION",
                         "resourceIds": ["a2a-echo"]}),
                     lambda values: any("CREATE_PROCESS_INSTANCE" in item["permissionTypes"] for item in values))
                repair = "Grant isolated test user admin read access plus explicit CREATE_PROCESS_INSTANCE on " \
                         "a2a-echo, then retry and resolve; not a least-privilege recipe"
            status, _ = request(f'/v2/jobs/{incident["jobKey"]}', {"changeset": {"retries": 1}}, method="PATCH")
            assert status == 204, ("retry after deployment repair", status)
            status, _ = request(f'/v2/incidents/{incident["incidentKey"]}/resolution', {}, method="POST")
            assert status in (204, 404), ("resolve repaired deployment incident", status)
            response = read_root_variable(request, instance, "rpcResponse", seconds=45)
            assert response["id"] == identifier and "error" not in response, response
            recovered = response["result"]["task"]
            assert recovered["status"]["state"] == "TASK_STATE_COMPLETED", recovered
            assert recovered["status"]["message"]["parts"] == [{"text": text}], recovered
            assert call("GetTask", {"id": recovered["id"]})["result"] == recovered
            wait("deployment incident cleared", lambda: search("/v2/incidents/search", {
                "processInstanceKey": instance, "state": "ACTIVE"}), lambda values: not values)
            fresh_text = "Fresh external work after " + mode + " repair"
            fresh = call("SendMessage", {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                                   "parts": [{"text": fresh_text}]}})["result"]["task"]
            fresh = wait("fresh external work after deployment repair",
                         lambda: call("GetTask", {"id": fresh["id"]})["result"],
                         lambda value: value["status"]["state"] == "TASK_STATE_COMPLETED")
            assert fresh["status"]["message"]["parts"] == [{"text": fresh_text}], fresh
            records.append({"case": mode, "connectorInputsUnmodified": True, "expectedHttpError": expected_error,
                            "shippedRetries": 3, "shippedRetryBackoffSeconds": 30,
                            "clientObservation": client_observation, "incidentSeconds": round(incident_seconds, 3),
                            "noFabricatedResponse": True, "recoveredExactTask": True,
                            "operatorRepair": repair, "freshWorkAfterRepair": True})
        env.pop("PROOF_PROTOCOL_ENGINE_USERNAME")
        env.pop("PROOF_PROTOCOL_ENGINE_PASSWORD")
        restart_connectors()
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
        env.pop("PROOF_PROTOCOL_ENGINE_USERNAME", None)
        env.pop("PROOF_PROTOCOL_ENGINE_PASSWORD", None)
        deploy([protocol, echo])
        if created_user:
            status, _ = request(f"/v2/users/{user}", method="DELETE")
            assert status == 204, ("restricted user cleanup", status)
