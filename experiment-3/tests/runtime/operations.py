"""Nonshipping terminal-ordering checks using stock engine APIs and authenticated A2A."""
from concurrent.futures import ThreadPoolExecutor
import json
import random
import time
import uuid
import xml.etree.ElementTree as ET

from observations import read_root_variable

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
CONTEXT = "native-terminal-ordering"
COMPLETED = "TASK_STATE_COMPLETED"
CANCELED = "TASK_STATE_CANCELED"


def controlled_model(source, target, process_id, hook=True):
    model = ET.parse(source)
    root = model.getroot()
    process = root.find(f"{{{B}}}process")
    process.set("id", process_id)
    root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane").set("bpmnElement", process_id)
    if not hook:
        subprocess = next(element for element in process if element.get("id") == "A2ACancellation")
        identifiers = {element.get("id") for element in subprocess.iter() if element.get("id")}
        process.remove(subprocess)
        root.remove(next(element for element in root if element.get("id") == "A2ACancelMessage"))
        plane = root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane")
        for element in list(plane):
            if element.get("bpmnElement") in identifiers:
                plane.remove(element)
    ET.register_namespace("bpmn", B)
    model.write(target, encoding="utf-8", xml_declaration=True)


def run(root, reports, rpc, request, deploy, process_id):
    records = []
    rng = random.Random(20261027)
    source = root / "tests/src/test/resources/bpmn/a2a-controlled-business.bpmn"
    model = reports / "nonshipping-controlled-business.bpmn"
    controlled_model(source, model, process_id)
    deploy([model])

    def save(verdict):
        (reports / "terminal-checks.json").write_text(json.dumps({
            "verdict": verdict, "seed": 20261027, "randomizedCompletionCancelIterations": 24,
            "followUpCancelIterations": 12, "concurrentFollowUpIterations": 4, "records": records,
            "conditionalFeatures": "No custom worker/server; nonshipping controlled business user tasks.",
        }, indent=2) + "\n")

    save("RUNNING")

    def call(method, params):
        identifier = str(uuid.uuid4())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        assert status == 200 and isinstance(response, dict) and response.get("id") == identifier, (status, response)
        return response

    def send(text="controlled"):
        response = call("SendMessage", {"message": {
            "messageId": str(uuid.uuid4()), "contextId": CONTEXT, "role": "ROLE_USER", "parts": [{"text": text}]},
            "configuration": {"returnImmediately": text != "input-required"}})
        return response["result"]["task"]

    def task(identifier):
        return call("GetTask", {"id": identifier})["result"]

    def wait(description, observe, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = observe()
            if predicate(last):
                return last
            time.sleep(0.25)
        raise TimeoutError(f"{description}: no matching observation within {seconds}s; last={last!r}")

    def search(path, filter):
        status, body = request(path, {"filter": filter, "page": {"limit": 100}})
        assert status == 200, (path, status, body)
        return json.loads(body)["items"]

    def instance(identifier):
        items = wait("task process index", lambda: search("/v2/process-instances/search", {
            "processDefinitionId": process_id, "tags": ["task-" + identifier]}), bool)
        assert len(items) == 1, items
        return items[0]["processInstanceKey"]

    def work_key(identifier):
        key = instance(identifier)
        items = wait("active controlled user task", lambda: search("/v2/user-tasks/search", {
            "processInstanceKey": key, "elementId": "ControlledWork", "state": "CREATED"}), bool)
        assert len(items) == 1, items
        return items[0]["userTaskKey"]

    def complete(key):
        status, body = request(f"/v2/user-tasks/{key}/completion", {})
        assert status in (200, 204, 404, 409), (status, body)
        return status

    def follow(identifier, delay=0):
        time.sleep(delay)
        return call("SendMessage", {"message": {"messageId": str(uuid.uuid4()), "taskId": identifier,
            "contextId": CONTEXT, "role": "ROLE_USER", "parts": [{"text": "Controlled continuation"}]},
            "configuration": {"returnImmediately": True}})

    def cancel(identifier, delay=0):
        time.sleep(delay)
        return call("CancelTask", {"id": identifier})

    def terminal(identifier, expected):
        observed = wait("terminal task", lambda: task(identifier), lambda value: value["status"]["state"] == expected)
        stored = read_root_variable(request, instance(identifier), "task")
        assert stored["status"] == observed["status"], (stored, observed)
        assert stored.get("artifacts", []) == observed.get("artifacts", []), (stored, observed)
        if expected == CANCELED:
            assert not observed.get("artifacts") and "message" not in observed["status"], observed
        else:
            assert observed["status"]["message"]["parts"] == [{"text": "Controlled completion"}], observed
            assert observed["artifacts"] == [
                {"artifactId": "controlled", "parts": [{"text": "Controlled artifact"}]}], observed
        listed = call("ListTasks", {"contextId": CONTEXT, "pageSize": 100, "includeArtifacts": True})["result"]
        match = [value for value in listed["tasks"] if value["id"] == identifier]
        assert len(match) == 1 and match[0]["status"] == observed["status"], (listed, observed)
        assert match[0].get("artifacts", []) == observed.get("artifacts", []), match
        assert cancel(identifier)["error"]["code"] == -32002
        assert follow(identifier)["error"]["code"] == -32004
        assert task(identifier) == observed, "Terminal operations changed the stored outcome"
        return observed

    try:
        working = send()
        identifier = working["id"]
        key = work_key(identifier)
        response = cancel(identifier)
        assert response["result"]["status"]["state"] == CANCELED, response
        late_status = complete(key)
        assert late_status in (404, 409), late_status
        observed = terminal(identifier, CANCELED)
        assert response["result"] == observed, (response, observed)
        records.append({"case": "cancel-first", "lateBusinessCompletionHttpStatus": late_status, "task": observed})

        working = send()
        identifier = working["id"]
        assert complete(work_key(identifier)) in (200, 204)
        observed = terminal(identifier, COMPLETED)
        records.append({"case": "completion-first", "cancelError": -32002, "task": observed})

        iterations = 24
        for iteration in range(iterations):
            working = send()
            identifier = working["id"]
            key = work_key(identifier)
            cancel_delay, completion_delay = rng.random() * 0.3, rng.random() * 2.5

            def finish():
                time.sleep(completion_delay)
                return complete(key)

            with ThreadPoolExecutor(max_workers=2) as pool:
                cancellation = pool.submit(cancel, identifier, cancel_delay)
                completion = pool.submit(finish)
                response, completion_status = cancellation.result(timeout=65), completion.result(timeout=65)
            expected = CANCELED if "result" in response else COMPLETED
            if expected == COMPLETED:
                assert response["error"]["code"] == -32002, response
                assert completion_status in (200, 204), completion_status
            observed = terminal(identifier, expected)
            if expected == CANCELED:
                assert response["result"] == observed, (response, observed)
            records.append({"case": "randomized-completion-cancel", "iteration": iteration,
                            "cancelDelaySeconds": cancel_delay, "completionDelaySeconds": completion_delay,
                            "businessCompletionHttpStatus": completion_status, "task": observed})

        for iteration in range(12):
            waiting = send("input-required")
            identifier = waiting["id"]
            assert waiting["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", waiting
            with ThreadPoolExecutor(max_workers=2) as pool:
                continuation = pool.submit(follow, identifier, rng.random() * 0.1)
                cancellation = pool.submit(cancel, identifier, rng.random() * 0.1)
                follow_response, response = continuation.result(timeout=65), cancellation.result(timeout=65)
            observed = terminal(identifier, CANCELED)
            assert response["result"] == observed, (response, observed)
            if "result" in follow_response:
                assert follow_response["result"]["task"]["id"] == identifier, follow_response
                assert follow_response["result"]["task"]["status"]["state"] in ("TASK_STATE_WORKING", CANCELED)
            else:
                assert follow_response["error"]["code"] == -32004, follow_response
            records.append({"case": "follow-up-cancel-race", "iteration": iteration,
                            "followUpResponse": follow_response, "task": observed})

        for iteration in range(4):
            waiting = send("input-required")
            identifier = waiting["id"]
            assert waiting["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", waiting
            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = pool.submit(follow, identifier), pool.submit(follow, identifier)
                responses = [first.result(timeout=65), second.result(timeout=65)]
            accepted = [response for response in responses if "result" in response]
            rejected = [response for response in responses if "error" in response]
            assert len(accepted) == len(rejected) == 1, responses
            assert rejected[0]["error"]["code"] == -32004, rejected
            response = cancel(identifier)
            observed = terminal(identifier, CANCELED)
            assert response["result"] == observed, (response, observed)
            assert len([message for message in observed["history"] if message["role"] == "ROLE_USER"]) == 2, observed
            records.append({"case": "concurrent-follow-ups", "iteration": iteration,
                            "acceptedFollowUps": 1, "rejectedFollowUps": 1, "task": observed})

        waiting = send("input-required")
        assert waiting["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", waiting
        response = cancel(waiting["id"])
        observed = terminal(waiting["id"], CANCELED)
        assert response["result"] == observed, (response, observed)
        records.append({"case": "cancel-input-required", "task": observed})

        missing_hook = reports / "nonshipping-missing-cancellation-hook.bpmn"
        controlled_model(source, missing_hook, process_id, hook=False)
        deploy([missing_hook])
        working = send()
        identifier = working["id"]
        key = work_key(identifier)
        response = cancel(identifier)
        assert response["error"]["code"] == -32002, response
        assert task(identifier)["status"]["state"] == "TASK_STATE_WORKING"
        assert complete(key) in (200, 204)
        observed = terminal(identifier, COMPLETED)
        records.append({"case": "missing-hook", "cancelError": -32002, "task": observed})
        assert cancel("unknown-cancellation-task")["error"]["code"] == -32001
        assert task(identifier) == observed, "Unknown cancellation reached a different task"
        save("PASS")
        print("Native cancellation/completion ordering and terminal-state checks: PASS", flush=True)
    except Exception:
        save("FAIL")
        raise
    finally:
        deploy([root / "bpmn/a2a-echo.bpmn"])
