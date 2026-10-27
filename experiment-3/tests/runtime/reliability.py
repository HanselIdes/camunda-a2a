"""Nonshipping two-agent workload against separate authenticated stock-runtime deployments."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import xml.etree.ElementTree as ET

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
WAYPOINT = "http://www.omg.org/spec/DD/20100524/DI"
TIMER_SECONDS = 15


def write_json(path, value):
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def peak_concurrency(results):
    events = [(result["started"], 1) for result in results]
    events += [(result["finished"], -1) for result in results]
    active = peak = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    return peak


def check_completed(task, text, context):
    assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
    assert task["status"]["message"]["parts"] == [{"text": text}], task
    assert task["contextId"] == context, task
    assert [message["parts"] for message in task["history"]] == [[{"text": text}], [{"text": text}]], task
    assert not task.get("artifacts"), task


def timed_echo(source, target):
    model = ET.parse(source)
    root = model.getroot()
    process = root.find(f"{{{B}}}process")
    start = process.find(f"{{{B}}}startEvent")
    start.find(f"{{{B}}}outgoing").text = "Flow_Received_Hold"
    echo = process.find(f"{{{B}}}scriptTask")
    echo.find(f"{{{B}}}incoming").text = "Flow_Hold_Echo"
    flow = next(element for element in process if element.get("id") == "Flow_Received_Echo")
    flow.set("id", "Flow_Received_Hold")
    flow.set("targetRef", "HoldConcurrency")
    timer = ET.Element(f"{{{B}}}intermediateCatchEvent", id="HoldConcurrency", name="Hold concurrent work")
    ET.SubElement(timer, f"{{{B}}}incoming").text = "Flow_Received_Hold"
    ET.SubElement(timer, f"{{{B}}}outgoing").text = "Flow_Hold_Echo"
    definition = ET.SubElement(timer, f"{{{B}}}timerEventDefinition", id="HoldConcurrency_timer")
    ET.SubElement(definition, f"{{{B}}}timeDuration", {
        "{http://www.w3.org/2001/XMLSchema-instance}type": "bpmn:tFormalExpression"
    }).text = f'="PT{TIMER_SECONDS}S"'
    process.insert(list(process).index(start) + 1, timer)
    ET.SubElement(process, f"{{{B}}}sequenceFlow", id="Flow_Hold_Echo",
                  sourceRef="HoldConcurrency", targetRef="EchoMessage")
    plane = root.find(f"{{{DI}}}BPMNDiagram/{{{DI}}}BPMNPlane")
    for shape in plane.findall(f"{{{DI}}}BPMNShape"):
        if shape.get("bpmnElement") != "TaskReceived":
            bounds = shape.find(f"{{{DC}}}Bounds")
            bounds.set("x", str(int(bounds.get("x")) + 160))
    for edge in plane.findall(f"{{{DI}}}BPMNEdge"):
        if edge.get("bpmnElement") == "Flow_Received_Echo":
            edge.set("id", "Flow_Received_Hold_di")
            edge.set("bpmnElement", "Flow_Received_Hold")
        else:
            for point in edge:
                point.set("x", str(int(point.get("x")) + 160))
    shape = ET.SubElement(plane, f"{{{DI}}}BPMNShape", id="HoldConcurrency_di", bpmnElement="HoldConcurrency")
    ET.SubElement(shape, f"{{{DC}}}Bounds", x="240", y="122", width="36", height="36")
    edge = ET.SubElement(plane, f"{{{DI}}}BPMNEdge", id="Flow_Hold_Echo_di", bpmnElement="Flow_Hold_Echo")
    ET.SubElement(edge, f"{{{WAYPOINT}}}waypoint", x="276", y="140")
    ET.SubElement(edge, f"{{{WAYPOINT}}}waypoint", x="400", y="140")
    for prefix, namespace in (("bpmn", B), ("bpmndi", DI), ("dc", DC), ("di", WAYPOINT),
                              ("xsi", "http://www.w3.org/2001/XMLSchema-instance")):
        ET.register_namespace(prefix, namespace)
    ET.indent(model, space="  ")
    model.write(target, encoding="utf-8", xml_declaration=True)


def run_agent(env, reports, rpc, stack, deploy, root):
    agent = env["PROOF_LOAD_AGENT"]
    control = Path(env["PROOF_CONTROL_DIR"]) / agent
    context = "load-" + agent
    completed = []
    duplicate_ids = []
    restart_checks = []

    def call(method, params, timeout=60):
        identifier = agent + "-" + str(time.time_ns())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method,
                                "params": params}, timeout=timeout)
        assert status == 200 and response["id"] == identifier, (status, response)
        return response

    def send(text, message_id=None, slow=False):
        started = time.monotonic()
        response = call("SendMessage", {"message": {
            "messageId": message_id or agent + "-" + str(time.time_ns()),
            "contextId": context, "role": "ROLE_USER", "parts": [{"text": text}]},
            "configuration": {"returnImmediately": True}})
        task = response["result"]["task"]
        accepted = time.monotonic()
        if slow:
            assert task["status"]["state"] == "TASK_STATE_WORKING", task
            time.sleep(max(0, started + TIMER_SECONDS - time.monotonic()))
        completion_deadline = time.monotonic() + 60
        while task["status"]["state"] == "TASK_STATE_WORKING":
            if time.monotonic() >= completion_deadline:
                raise TimeoutError("Workload result deadline expired")
            task = call("GetTask", {"id": task["id"]})["result"]
            if task["status"]["state"] == "TASK_STATE_WORKING":
                time.sleep(0.5)
        check_completed(task, text, context)
        return {"started": started, "accepted": accepted, "finished": time.monotonic(),
                "expectedText": text, "task": task}

    write_json(control / "ready.json", {"agent": agent})
    command_index = 0
    deadline = time.monotonic() + 300
    while True:
        command = control / f"command-{command_index}.json"
        if not command.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{agent}: workload coordinator deadline expired")
            time.sleep(0.1)
            continue
        data = json.loads(command.read_text())
        operation = data["operation"]
        if operation == "stop":
            break
        if operation == "send":
            result = send(data["text"])
            completed.append(result)
        elif operation == "concurrent":
            timed_model = reports / "nonshipping-timed-echo.bpmn"
            timed_echo(root / "bpmn/a2a-echo.bpmn", timed_model)
            deploy([timed_model])
            write_json(control / "concurrent-ready.json", {"agent": agent})
            barrier_deadline = time.monotonic() + 60
            while not (control.parent / "concurrent-go").exists():
                if time.monotonic() >= barrier_deadline:
                    raise TimeoutError("Concurrent workload start barrier expired")
                time.sleep(0.02)
            with ThreadPoolExecutor(max_workers=10) as pool:
                result = list(pool.map(lambda text: send(text, slow=True), data["texts"]))
            completed.extend(result)
            deploy([root / "bpmn/a2a-echo.bpmn"])
        elif operation == "check":
            for foreign_id in data["foreignTaskIds"]:
                response = call("GetTask", {"id": foreign_id})
                assert response["error"]["code"] == -32001, response
            listed, cursor, seen_cursors = [], "", set()
            for _ in range(10):
                response = call("ListTasks", {"contextId": context, "pageSize": 17, "pageToken": cursor})
                page = response["result"]
                assert page["totalSize"] == 60, page
                listed.extend(page["tasks"])
                cursor = page["nextPageToken"]
                if not cursor:
                    break
                assert cursor not in seen_cursors, "ListTasks cursor did not progress"
                seen_cursors.add(cursor)
            else:
                raise TimeoutError("ListTasks exceeded its bounded page count")
            assert len(listed) == 60, len(listed)
            assert {task["id"] for task in listed} == {item["task"]["id"] for item in completed}
            sample = completed[0]
            response = call("GetTask", {"id": sample["task"]["id"], "historyLength": 1})
            assert len(response["result"]["history"]) == 1, response
            result = {"foreignTasksNotFound": True, "exactPaginatedTasks": 60, "historyLimit": 1}
        elif operation == "duplicate":
            first = send("duplicate-" + agent, "same-message-id-" + agent)
            second = send("duplicate-" + agent, "same-message-id-" + agent)
            assert first["task"]["id"] != second["task"]["id"], "Unexpected deduplication semantics"
            duplicate_ids = [first["task"]["id"], second["task"]["id"]]
            result = {"behavior": "Independent new tasks; message IDs do not deduplicate side effects.",
                      "taskIds": duplicate_ids}
        elif operation == "restart":
            service = data["service"]
            if service not in ("camunda", "connectors"):
                raise ValueError("Only this run's engine or Connectors may be restarted")
            subprocess.run(stack.command + ["restart", service], env=env, check=True, timeout=180)
            readiness_deadline = time.monotonic() + 180
            diagnostic = "No response"
            while True:
                try:
                    status, response = rpc({"jsonrpc": "2.0", "id": "restart-check", "method": "GetTask",
                                           "params": {"id": completed[0]["task"]["id"]}}, timeout=10)
                    diagnostic = f"HTTP {status}"
                    if status == 200 and "result" in response:
                        assert response["result"] == completed[0]["task"], response
                        break
                    if status == 200:
                        diagnostic += f"; JSON-RPC error {response.get('error', {}).get('code')}"
                except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                    diagnostic = type(error).__name__
                if time.monotonic() >= readiness_deadline:
                    raise TimeoutError(f"{service} restart recovery deadline expired: {diagnostic}")
                time.sleep(1)
            restarted = send("after-" + service + "-restart-" + agent)
            restart_checks.append({"service": service, "preservedTask": completed[0]["task"]["id"],
                                   "newTask": restarted["task"]})
            result = restart_checks[-1]
        else:
            raise ValueError(f"Unknown workload operation: {operation}")
        write_json(control / f"result-{command_index}.json", result)
        command_index += 1
        deadline = time.monotonic() + 300
    write_json(reports / "workload.json", {
        "agent": agent, "isolation": "Separate authenticated engine and Connectors per agent.",
        "results": completed, "duplicateTaskIds": duplicate_ids, "restartChecks": restart_checks,
        "verdict": "PASS",
    })


def main():
    root = Path(__file__).resolve().parents[2]
    reports = Path(os.environ.get("PROOF_REPORT_DIR", str(root / "reports/reliability"))).resolve()
    reports.mkdir(parents=True, exist_ok=False)
    processes, logs, counters = {}, {}, {"alpha": 0, "beta": 0}
    with tempfile.TemporaryDirectory(prefix="a2a-workload-control-") as directory:
        control = Path(directory)

        def wait(path, seconds=120):
            deadline = time.monotonic() + seconds
            while not path.exists():
                for agent, process in processes.items():
                    if process.poll() is not None:
                        raise RuntimeError(f"{agent} exited {process.returncode}; see its runtime log")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Workload control deadline expired: {path.name}")
                time.sleep(0.1)
            return json.loads(path.read_text())

        def dispatch(agent, operation, **fields):
            index = counters[agent]
            counters[agent] += 1
            write_json(control / agent / f"command-{index}.json", {"operation": operation, **fields})
            return control / agent / f"result-{index}.json"

        try:
            for agent in counters:
                (control / agent).mkdir()
                logs[agent] = (reports / f"{agent}.log").open("w")
                env = dict(os.environ, PROOF_AGENT_PROCESS="a2a-echo", PROOF_LOAD_AGENT=agent,
                           PROOF_CONTROL_DIR=str(control), PROOF_REPORT_DIR=str(reports / agent))
                processes[agent] = subprocess.Popen([sys.executable, str(Path(__file__).with_name("verify.py"))],
                                                    env=env, stdout=logs[agent], stderr=subprocess.STDOUT)
            for agent in counters:
                wait(control / agent / "ready.json", seconds=360)
            sequential = []
            for index in range(100):
                agent = "alpha" if index % 2 == 0 else "beta"
                sequential.append(wait(dispatch(agent, "send", text=f"{agent}-sequential-{index}")))
            batch_paths = {agent: dispatch(agent, "concurrent", texts=[
                f"{agent}-concurrent-{index}" for index in range(10)]) for agent in counters}
            for agent in counters:
                wait(control / agent / "concurrent-ready.json")
            (control / "concurrent-go").touch()
            concurrent = [item for path in batch_paths.values() for item in wait(path)]
            assert len(concurrent) == 20 and peak_concurrency(concurrent) == 20
            creation_spread = max(item["accepted"] for item in concurrent) - min(
                item["started"] for item in concurrent)
            assert creation_spread < TIMER_SECONDS, "The timed business instances did not prove 20-way overlap"
            assert len({item["task"]["id"] for item in sequential + concurrent}) == 120
            boundary_checks = {}
            for agent, other in (("alpha", "beta"), ("beta", "alpha")):
                foreign = [item["task"]["id"] for item in sequential
                           if item["expectedText"].startswith(other + "-")][:2]
                boundary_checks[agent] = wait(dispatch(agent, "check", foreignTaskIds=foreign))
            duplicates = {agent: wait(dispatch(agent, "duplicate")) for agent in counters}
            restarts = []
            for service in ("connectors", "camunda"):
                restarts.append(wait(dispatch("alpha", "restart", service=service), seconds=240))
            for agent in counters:
                dispatch(agent, "stop")
            for agent, process in processes.items():
                code = process.wait(timeout=120)
                assert code == 0, f"{agent} failed final native verification: {code}"
            provenances = [json.loads((reports / agent / "runtime-provenance.json").read_text())
                           for agent in counters]
            assert all(p["verdict"] == "PASS" and not p["targetWorktreeDirty"] for p in provenances)
            assert len({p["targetCommit"] for p in provenances}) == 1
            write_json(reports / "summary.json", {
                "targetCommit": provenances[0]["targetCommit"], "targetWorktreeDirty": False,
                "sequentialTasks": len(sequential), "concurrentTasks": len(concurrent),
                "measuredPeakActiveTaskOperations": peak_concurrency(concurrent),
                "businessTimerSeconds": TIMER_SECONDS,
                "creationWindowSeconds": creation_spread,
                "minimumProvenBusinessOverlapSeconds": TIMER_SECONDS - creation_spread,
                "agents": 2, "isolation": "Two separate authenticated Self-Managed deployments.",
                "boundaryChecks": boundary_checks, "duplicates": duplicates, "restarts": restarts,
                "exactResultChecks": 120, "verdict": "PASS",
            })
            print("Two agents: 100 sequential + 20 measured concurrent exact results, boundaries and restarts: PASS")
        finally:
            for agent, process in processes.items():
                if process.poll() is None:
                    dispatch(agent, "stop")
                    try:
                        process.wait(timeout=120)
                    except subprocess.TimeoutExpired:
                        process.send_signal(signal.SIGINT)
                        process.wait(timeout=90)
            for log in logs.values():
                log.close()


if __name__ == "__main__":
    main()
