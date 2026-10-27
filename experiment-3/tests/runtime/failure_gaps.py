"""Nonshipping native engine-outage and correlation-transport checks."""
import http.client
import json
import socket
import subprocess
import time
import urllib.error
import uuid
import xml.etree.ElementTree as ET

from observations import read_root_variable
from operations import B, controlled_model

Z = "http://camunda.org/schema/zeebe/1.0"


def correlation_fault(source, target):
    ET.register_namespace("bpmn", B)
    model = ET.parse(source)
    task = next(item for item in model.getroot().iter() if item.get("id") == "CorrelateMessage")
    url = next(item for item in task.iter(f"{{{Z}}}input") if item.get("target") == "url")
    url.set("source", '="http://127.0.0.1:1/v2/messages/correlation"')
    model.write(target, encoding="utf-8", xml_declaration=True)


def observe_fault(invoke):
    started = time.monotonic()
    try:
        status, response = invoke()
    except (TimeoutError, socket.timeout):
        return {"client": "five-second-client-timeout",
                "seconds": round(time.monotonic() - started, 3)}
    except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionError) as error:
        return {"client": "transport-error", "errorType": type(error).__name__,
                "seconds": round(time.monotonic() - started, 3)}
    assert status >= 400 or (isinstance(response, dict) and "error" in response
                             and "result" not in response), (status, response)
    return {"client": "explicit-error", "httpStatus": status,
            "response": response, "seconds": round(time.monotonic() - started, 3)}


def run(root, reports, rpc, request, deploy, env, stack, redact):
    records, observations = [], []
    protocol = root / "blueprint/profiles/basic/01-a2a-server.bpmn"

    def save(verdict):
        (reports / "failure-gap-checks.json").write_text(redact(json.dumps({
            "verdict": verdict, "records": records, "observations": observations,
            "scope": "Native stock Basic profile. True outage stops only the owned engine. Correlation "
                     "fault changes only a derived nonshipping connector URL; retries/timeouts unchanged.",
            "exclusions": {
                "pushCallbacks": "Not applicable: push is disabled and unadvertised; no callback is invoked.",
                "oauthExpiry": "Not applicable: declared profile uses Basic authentication without token expiry.",
                "standardPathIngress": "Not applicable: optional ingress is outside the direct-URL profile.",
                "responseLossAfterCommit": "Native response-loss-after-commit is not injected here. "
                                          "Existing Core tests cover deterministic reconciliation; refusal "
                                          "before delivery is a distinct transport case.",
            },
        }, indent=2)) + "\n")

    def wait(description, observe, predicate, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = observe()
            if predicate(value):
                return value
            time.sleep(0.5)
        raise TimeoutError(f"{description}: no matching observation within {seconds}s")

    def compose(*arguments):
        subprocess.run(stack.command + list(arguments), env=env, check=True, capture_output=True)

    def search(path, filter):
        status, body = request(path, {"filter": filter, "page": {"limit": 100}})
        assert status == 200, (path, status)
        return json.loads(body)["items"]

    def call(method, params, timeout=60):
        identifier = str(uuid.uuid4())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method,
                                "params": params}, timeout=timeout)
        assert status == 200 and isinstance(response, dict) and response.get("id") == identifier, \
            (status, response)
        return response

    def send(text):
        response = call("SendMessage", {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                                   "parts": [{"text": text}]}})
        assert "error" not in response, response
        task = response["result"]["task"]
        return wait("non-working task", lambda: call("GetTask", {"id": task["id"]})["result"],
                    lambda value: value["status"]["state"] != "TASK_STATE_WORKING")

    def ready_task(identifier):
        try:
            status, response = rpc({"jsonrpc": "2.0", "id": "outage-readiness", "method": "GetTask",
                                    "params": {"id": identifier}}, timeout=5)
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, socket.timeout):
            return None
        return response.get("result") if status == 200 and isinstance(response, dict) else None

    save("RUNNING")
    try:
        original = send("Exact task preserved through real engine outage")
        assert original["status"]["state"] == "TASK_STATE_COMPLETED", original
        assert original["status"]["message"]["parts"] == [
            {"text": "Exact task preserved through real engine outage"}], original
        container = subprocess.check_output(stack.command + ["ps", "-q", "camunda"],
                                            env=env, text=True).strip()
        assert container, "Owned engine container is missing"
        compose("stop", "--timeout", "10", "camunda")
        state = json.loads(subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .State}}", container], text=True))
        assert state["Running"] is False, state
        observations.append({"case": "engine-outage", "engineRunning": state["Running"],
                             "engineStatus": state["Status"]})
        fault = observe_fault(lambda: rpc({"jsonrpc": "2.0", "id": "engine-down-get",
            "method": "GetTask", "params": {"id": original["id"]}}, timeout=5))
        observations.append({"case": "engine-outage", **fault})
        logs = subprocess.check_output(stack.command + ["logs", "--no-color", "--tail", "150", "connectors"],
                                       env=env, text=True)
        diagnostics = [line for line in logs.splitlines()
                       if any(term in line.lower() for term in
                              ("unavailable", "connection refused", "failed", "error", "deadline"))]
        assert diagnostics, "No operator-visible Connectors outage diagnostic"
        (reports / "engine-outage-connectors.log").write_text(redact("\n".join(diagnostics)) + "\n")
        compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "300", "camunda")
        recovered = wait("engine recovery and registered webhook", lambda: ready_task(original["id"]),
                         lambda value: value == original, seconds=180)
        assert recovered == original
        fresh = send("Exact fresh work after engine outage")
        assert fresh["status"]["state"] == "TASK_STATE_COMPLETED", fresh
        assert fresh["status"]["message"]["parts"] == [{"text": "Exact fresh work after engine outage"}]
        assert not search("/v2/incidents/search", {"state": "ACTIVE"})
        records.append({"case": "true-engine-outage", "clientObservation": fault,
                        "operatorVisible": "engine-outage-connectors.log",
                        "originalTaskUnchanged": True, "freshExactWork": True, "activeIncidentsAfterRepair": 0,
                        "scope": "External GetTask while engine container stopped; new handler cannot start. "
                                 "No engine incident is asserted while the engine is unavailable. "
                                 "Eventual webhook response after client deadline is unobserved."})
        observations.append({"case": "engine-recovery", "originalTask": recovered, "freshTask": fresh})
        save("RUNNING")

        model = reports / "nonshipping-gap-controlled-business.bpmn"
        controlled_model(root / "tests/src/test/resources/bpmn/a2a-controlled-business.bpmn",
                         model, env["PROOF_AGENT_PROCESS"])
        deploy([model])
        fault_model = reports / "nonshipping-correlation-transport.bpmn"
        correlation_fault(protocol, fault_model)
        for method in ("SendMessage", "CancelTask"):
            deploy([protocol])
            task = send("input-required")
            assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", task
            business = wait("controlled task indexed", lambda: search("/v2/process-instances/search", {
                "processDefinitionId": env["PROOF_AGENT_PROCESS"], "tags": ["task-" + task["id"]]}), bool)[0]
            deploy([fault_model])
            identifier = "transport-" + str(uuid.uuid4())
            params = {"id": task["id"]} if method == "CancelTask" else {
                "message": {"messageId": identifier, "taskId": task["id"], "contextId": task["contextId"],
                            "role": "ROLE_USER", "parts": [{"text": "Exact transport-repaired input"}]},
                "configuration": {"returnImmediately": True}}
            fault = observe_fault(lambda: rpc({"jsonrpc": "2.0", "id": identifier,
                                               "method": method, "params": params}, timeout=5))
            observations.append({"case": method + "-client", **fault})
            save("RUNNING")
            incident = wait("correlation transport incident", lambda: search("/v2/incidents/search", {
                "processDefinitionId": "a2a-correlate", "state": "ACTIVE"}), bool)[0]
            assert incident["elementId"] == "CorrelateMessage" and incident["errorType"] == "JOB_NO_RETRIES", incident
            assert any(term in incident["errorMessage"].lower() for term in
                       ("refused", "connect", "i/o")), incident
            def matching_root():
                variables = search("/v2/variables/search?truncateValues=false", {"name": "rpc"})
                matches = [value for value in variables if json.loads(value["value"]).get("id") == identifier
                           and value["scopeKey"] == value["processInstanceKey"]]
                assert len(matches) <= 1, "Duplicate RPC root for one external call"
                return matches

            instance = wait("external RPC root indexed", matching_root, bool)[0]["processInstanceKey"]
            assert read_root_variable(request, instance, "rpc")["id"] == identifier
            assert not search("/v2/variables/search", {"processInstanceKey": instance, "name": "rpcResponse"}), \
                "Transport failure fabricated an RPC response"
            assert call("GetTask", {"id": task["id"]})["result"] == task, "Refused transport changed business state"
            observations.append({"case": method + "-refused", "client": fault,
                                 "incident": incident, "unchangedTask": task})
            save("RUNNING")
            status, _ = request(f'/v2/element-instances/{incident["elementInstanceKey"]}/variables', {
                "local": True, "variables": {"url": "http://camunda:8080/v2/messages/correlation"}}, method="PUT")
            assert status == 204, ("repair correlation URL", status)
            status, _ = request(f'/v2/jobs/{incident["jobKey"]}', {"changeset": {"retries": 1}}, method="PATCH")
            assert status == 204, ("retry repaired correlation", status)
            status, _ = request(f'/v2/incidents/{incident["incidentKey"]}/resolution', {}, method="POST")
            assert status in (204, 404), ("resolve repaired correlation", status)
            response = read_root_variable(request, instance, "rpcResponse", seconds=45)
            assert response.get("id") == identifier and "error" not in response, response
            if method == "CancelTask":
                terminal = response["result"]
                assert terminal["status"]["state"] == "TASK_STATE_CANCELED" and not terminal.get("artifacts"), terminal
            else:
                resumed = response["result"]["task"]
                assert resumed["id"] == task["id"] and resumed["status"]["state"] == "TASK_STATE_WORKING", resumed
                assert resumed["history"][-1]["parts"] == [{"text": "Exact transport-repaired input"}], resumed
                work = wait("resumed user task", lambda: search("/v2/user-tasks/search", {
                    "processInstanceKey": business["processInstanceKey"], "elementId": "ControlledWork",
                    "state": "CREATED"}), bool)[0]
                status, _ = request(f'/v2/user-tasks/{work["userTaskKey"]}/completion', {})
                assert status in (200, 204), ("complete repaired work", status)
                terminal = wait("repaired task completion", lambda: call("GetTask", {"id": task["id"]})["result"],
                                lambda value: value["status"]["state"] == "TASK_STATE_COMPLETED")
                assert terminal["status"]["message"]["parts"] == [{"text": "Controlled completion"}], terminal
                assert terminal["artifacts"] == [
                    {"artifactId": "controlled", "parts": [{"text": "Controlled artifact"}]}], terminal
            assert call("GetTask", {"id": task["id"]})["result"] == terminal
            wait("repaired incident cleared", lambda: search("/v2/incidents/search", {
                "processInstanceKey": incident["processInstanceKey"], "state": "ACTIVE"}), lambda value: not value)
            observations.append({"case": method + "-repaired", "rpcResponse": response, "terminal": terminal})
            records.append({"case": method + "-correlation-transport", "connectorRetries": 1,
                            "connectorTimeoutSeconds": 20, "clientObservation": fault,
                            "incident": "CorrelateMessage / JOB_NO_RETRIES", "noFabricatedResponse": True,
                            "businessUnchangedBeforeRepair": True, "originalRpcRecovered": True,
                            "exactTerminalAgreement": True, "activeIncidentsAfterRepair": 0})
            save("RUNNING")
        deploy([protocol, root / "bpmn/a2a-echo.bpmn"])
        assert not search("/v2/incidents/search", {"state": "ACTIVE"})
        save("PASS")
    except Exception:
        save("FAIL")
        raise
