"""Bounded observed prompt-content diagnostic; no blueprint adaptation changes."""
import ast
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

external = Path(__file__).with_name("matched-latest-external.py")
prefix = []
for statement in ast.parse(external.read_text()).body:
    if isinstance(statement, ast.Try):
        break
    prefix.append(statement)
local = {"__file__": str(external), "__name__": "quoting_provisioning"}
exec(compile(ast.Module(body=prefix, type_ignores=[]), str(external), "exec"), local)
namespace = local["namespace"]
stack = local["stack"]
reports = local["reports"]
module = local["module"]
cases = [
    ("quotes", 'Synthetic diagnostic only: a merchant label says "example". Please ask for missing details.'),
    ("backslashes", r"Synthetic diagnostic only: reference C:\lab\order\n.txt. Please ask for missing details."),
    ("newlines", "Synthetic diagnostic only:\nfirst line\nsecond line. Please ask for missing details."),
    ("controls", "Synthetic diagnostic only: A\tB\rC\bD\fE\u0001F. Please ask for missing details."),
]
observed = []
try:
    stack.start()
    namespace["record_exporter_configuration"]()
    root = namespace["ROOT"]
    namespace["deploy"]([root / "blueprint/profiles/basic/a2a-protocol.bpmn",
                         root / "blueprint/demo/a2a-card-dispute.bpmn", root / "dmn/a2a-validate.dmn"])
    deadline = time.monotonic() + 120
    while True:
        try:
            status, body = namespace["rpc"](
                {"jsonrpc": "2.0", "id": "safe-readiness", "method": "ListTasks", "params": {}}, False)
            if status != 404:
                assert status == 401, (status, body)
                break
        except local["urllib"].error.URLError:
            if time.monotonic() >= deadline:
                raise
        if time.monotonic() >= deadline:
            raise TimeoutError("Authenticated RPC readiness expired before diagnostic sends")
        time.sleep(1)
    for label, text in cases:
        request = {"jsonrpc": "2.0", "id": "quoting-" + label, "method": "SendMessage",
                   "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                          "parts": [{"text": text}]}}}
        (reports / (label + "-request.json")).write_text(json.dumps(request, indent=2) + "\n")
        status, response = namespace["rpc"](request)
        (reports / (label + "-response.json")).write_text(
            json.dumps({"httpStatus": status, "body": response}, indent=2) + "\n")
        assert status == 200 and "result" in response, (label, status, response)
        task = namespace["await_task"](response)
        assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", (label, task)
        deadline = time.monotonic() + 30
        while True:
            status, body = namespace["request"]("/v2/process-instances/search",
                {"filter": {"tags": ["task-" + task["id"]]}})
            assert status == 200
            items = json.loads(body)["items"]
            if len(items) == 1:
                business = items[0]["processInstanceKey"]
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Unique diagnostic business task was not indexed")
            time.sleep(0.5)
        read = namespace["read_root_variable"]
        req = read(namespace["request"], business, "req")
        encoded = read(namespace["request"], business, "jsonPrompt")
        agent = read(namespace["request"], business, "agent")
        module.write(reports / (label + "-context.json"), {
            "input": text, "requestRoot": req, "jsonPrompt": encoded, "agent": agent, "task": task})
        users = [c["text"] for m in agent["context"]["conversation"]["messages"] if m["role"] == "user"
                 for c in m.get("content", []) if c.get("type") == "text"]
        assert len(users) == 1
        stored = users[0]
        assert req["message"]["parts"][0]["text"] == text
        assert stored == encoded
        record = {"case": label, "inputText": text, "requestRootText": req["message"]["parts"][0]["text"],
                  "jsonPrompt": encoded, "storedModelUserText": stored, "task": task,
                  "agent": agent, "verbatim": stored == text,
                  "jsonDecodedEqualsOriginal": json.loads(stored) == text,
                  "inputCodepoints": [ord(c) for c in text],
                  "storedCodepoints": [ord(c) for c in stored]}
        observed.append(record)
        module.write(reports / "quoting-observations.json", observed)
    namespace["assert_no_persisted_credentials"]()
    assert namespace["source_snapshot"](root) == namespace["source_before"]
    namespace["record_provenance"](
        "DIAGNOSTIC_COMPLETE_VERBATIM_FAIL",
        cases=[{"case": c["case"], "verbatim": c["verbatim"],
                "jsonDecodedEqualsOriginal": c["jsonDecodedEqualsOriginal"]} for c in observed],
        scope="Stored connector model-input strings, not intercepted provider HTTP bytes; no behavior edits")
    print("Four actual model-context cases recorded; no verbatim waiver", flush=True)
finally:
    try:
        stack.close()
    finally:
        namespace["tls_directory"].cleanup()
