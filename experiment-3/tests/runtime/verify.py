import base64
import http.client
import json
import os
import secrets
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = Path(os.environ.get("PROOF_REPORT_DIR", str(ROOT / "reports/runtime")))
REPORTS.mkdir(parents=True, exist_ok=True)
COMPOSE = os.path.join(os.path.dirname(__file__), "compose.yml")
env = dict(os.environ, PROOF_ENGINE_PASSWORD=secrets.token_urlsafe(32),
           PROOF_A2A_API_KEY=secrets.token_urlsafe(32), PROOF_TLS_PASSWORD=secrets.token_urlsafe(32))
env.setdefault("PROOF_AGENT_PROCESS", "a2a-card-dispute")
if env["PROOF_AGENT_PROCESS"] not in ("a2a-card-dispute", "a2a-echo"):
    raise ValueError("PROOF_AGENT_PROCESS must select a2a-card-dispute or a2a-echo")
cmd = ["docker", "compose", "-p", "a2a-acceptance-88", "-f", COMPOSE]
demo = env.get("PROOF_AGENT_PROCESS") == "a2a-card-dispute"
tls_directory = tempfile.TemporaryDirectory(prefix="a2a-proof-tls-")
env["PROOF_CERTIFICATE_DIR"] = tls_directory.name
tls_path = Path(tls_directory.name)
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=host.docker.internal", "-addext", "subjectAltName=DNS:host.docker.internal,IP:127.0.0.1",
                "-keyout", str(tls_path / "server.key"), "-out", str(tls_path / "server.crt")],
               check=True, capture_output=True)
subprocess.run(["openssl", "pkcs12", "-export", "-in", str(tls_path / "server.crt"),
                "-inkey", str(tls_path / "server.key"), "-out", str(tls_path / "server.p12"),
                "-passout", "env:PROOF_TLS_PASSWORD"], env=env, check=True, capture_output=True)
subprocess.run(["keytool", "-importcert", "-alias", "a2a-proof", "-file", str(tls_path / "server.crt"),
                "-keystore", str(tls_path / "trust.p12"), "-storetype", "PKCS12",
                "-storepass:env", "PROOF_TLS_PASSWORD", "-noprompt"], env=env, check=True, capture_output=True)
tls_context = ssl.create_default_context(cafile=str(tls_path / "server.crt"))


def request(path, body=None, authenticated=True):
    headers = {}
    if authenticated:
        token = base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode()
        headers["Authorization"] = "Basic " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request("http://127.0.0.1:38880" + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def deploy(files):
    boundary = secrets.token_hex(16)
    body = bytearray()
    for file in files:
        path = Path(file)
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"resources\"; "
                     f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    token = base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode()
    req = urllib.request.Request("http://127.0.0.1:38880/v2/deployments", data=body,
                                 headers={"Authorization": "Basic " + token,
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            print("deployment status", response.status, flush=True)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"deployment {error.code}: {error.read().decode()}") from error


def rpc(body, key=True):
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
    if key:
        headers["X-A2A-Api-Key"] = env["PROOF_A2A_API_KEY"] if key is True else key
    req = urllib.request.Request("https://127.0.0.1:38885/inbound/a2a",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=tls_context) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def await_task(response, seconds=300):
    result = response["result"]
    task = result["task"] if "task" in result else result
    deadline = time.monotonic() + seconds
    while task["status"]["state"] == "TASK_STATE_WORKING":
        if time.monotonic() >= deadline:
            raise TimeoutError("Business result visibility deadline expired")
        time.sleep(1)
        status, response = rpc({"jsonrpc": "2.0", "id": "proof-poll", "method": "GetTask",
                                "params": {"id": task["id"]}})
        assert status == 200 and "result" in response, (status, response)
        task = response["result"]
    return task


def record_model_inputs():
    captured = {}
    for name in ("agent", "data", "req"):
        status, body = request("/v2/variables/search?truncateValues=false",
                               {"filter": {"name": name}, "page": {"limit": 20}})
        assert status == 200, (name, status)
        for value in (env["PROOF_ENGINE_PASSWORD"], env["PROOF_A2A_API_KEY"]):
            body = body.replace(value, "[REDACTED]")
        captured[name] = json.loads(body)
    (REPORTS / "real-model-inputs.json").write_text(json.dumps(captured, indent=2))
    expected = "49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD."
    texts = []
    for item in captured["agent"]["items"]:
        agent = json.loads(item["value"])
        for message in agent.get("context", {}).get("conversation", {}).get("messages", []):
            if message.get("role") == "user":
                texts.extend(c.get("text") for c in message.get("content", []) if c.get("type") == "text")
    assert expected in texts, "Numeric-leading follow-up was not delivered verbatim to the model"
    print("Captured model input/context diagnostics without credentials", flush=True)


try:
    subprocess.run(cmd + ["up", "-d", "--wait", "--wait-timeout", "300"], env=env, check=True)
    deadline = time.monotonic() + 60
    while request("/v2/topology")[0] != 200:
        if time.monotonic() >= deadline:
            raise TimeoutError("Authenticated engine readiness deadline expired")
        time.sleep(1)
    checks = [
        ("unauthenticated topology", "/v2/topology", None, False),
        ("authenticated topology", "/v2/topology", None, True),
        ("expression evaluation", "/v2/expression/evaluation", {"expression": "=1+1"}, True),
        ("cluster variables", "/v2/cluster-variables/search", {"filter": {}, "page": {"limit": 1}}, True),
        ("tag search", "/v2/process-instances/search",
         {"filter": {"tags": ["a2a"]}, "page": {"limit": 1}}, True),
    ]
    for name, path, body, auth in checks:
        status, text = request(path, body, auth)
        print(json.dumps({"check": name, "status": status, "response": text[:2000]}), flush=True)
    agent_file = ROOT / ("blueprint/demo/a2a-card-dispute.bpmn" if demo else "bpmn/a2a-echo.bpmn")
    files = [ROOT / "blueprint/profiles/basic/a2a-protocol.bpmn", agent_file, ROOT / "dmn/a2a-validate.dmn"]
    if demo:
        files += list((ROOT / "blueprint/demo").glob("*.form"))
        files += [ROOT / "blueprint/demo/a2a-card.bpmn", ROOT / "blueprint/demo/a2a-client.bpmn"]
    deploy(files)
    text = ("Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. "
            "The expected charge was USD 49.95. Reconcile the two charges with your tool." if demo else
            "8.8 authenticated echo")
    message = {"jsonrpc": "2.0", "id": "proof-request", "method": "SendMessage",
               "params": {"message": {"messageId": "proof-message", "role": "ROLE_USER",
                                      "parts": [{"text": text}]}}}
    deadline = time.monotonic() + 120
    while True:
        try:
            status, body = rpc(message, False)
        except (urllib.error.URLError, http.client.RemoteDisconnected):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
            continue
        if status != 404:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("RPC registration deadline expired")
        time.sleep(1)
    assert status == 401, (status, body)
    print("missing API key rejected: 401", flush=True)
    status, body = rpc(message, "invalid")
    assert status == 401, (status, body)
    print("invalid API key rejected: 401", flush=True)
    status, body = rpc(message)
    print(json.dumps({"check": "authenticated echo", "status": status, "response": body}), flush=True)
    assert status == 200 and body["id"] == "proof-request", (status, body)
    task = body["result"]["task"]
    deadline = time.monotonic() + (300 if demo else 60)
    while task["status"]["state"] == "TASK_STATE_WORKING":
        if time.monotonic() >= deadline:
            raise TimeoutError("Business result visibility deadline expired")
        time.sleep(1)
        status, fetched = rpc({"jsonrpc": "2.0", "id": "proof-poll", "method": "GetTask",
                               "params": {"id": task["id"]}})
        assert status == 200 and "result" in fetched, (status, fetched)
        task = fetched["result"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
    if demo:
        def check_reconciliation(result):
            assert result["status"]["state"] == "TASK_STATE_COMPLETED", result
            artifact = next(a for a in result["artifacts"] if a["name"] == "reconciliation")
            assert artifact["parts"][0]["data"] == {
                "merchant": "Northwind Electronics", "currency": "USD", "chargeAmounts": [49.95, 49.95],
                "expectedAmount": 49.95, "paidAmount": 99.9, "overchargeAmount": 49.95,
                "matchingAmounts": True, "recommendation": "REQUEST_HUMAN_REVIEW", "syntheticOnly": True
            }, artifact
            assert "<tool_call>" not in result["status"]["message"]["parts"][0]["text"], result
        check_reconciliation(task)
        print("real-model synthetic reconciliation with exact arithmetic evidence: PASS", flush=True)
        status, response = rpc({
            "jsonrpc": "2.0", "id": "dispute-clarification", "method": "SendMessage",
            "params": {"message": {"messageId": "dispute-incomplete", "role": "ROLE_USER",
                                   "parts": [{"text": "Please review a synthetic card dispute."}]}}})
        assert status == 200 and "result" in response, (status, response)
        waiting = await_task(response)
        assert waiting["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", waiting
        follow_up_text = "49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD."
        status, response = rpc({
            "jsonrpc": "2.0", "id": "dispute-follow-up", "method": "SendMessage",
            "params": {"message": {"messageId": "dispute-complete", "role": "ROLE_USER",
                                   "taskId": waiting["id"], "contextId": waiting["contextId"],
                                   "parts": [{"text": follow_up_text}]}}})
        assert status == 200 and "result" in response, (status, response)
        followed = await_task(response)
        check_reconciliation(followed)
        assert followed["id"] == waiting["id"] and followed["contextId"] == waiting["contextId"], followed
        assert len(followed["history"]) == 4, followed
        assert all(m["taskId"] == followed["id"] and m["contextId"] == followed["contextId"]
                   for m in followed["history"]), followed
        print("real-model card-dispute numeric-leading follow-up completes same task with four-message history: PASS", flush=True)
        with urllib.request.urlopen("https://127.0.0.1:38885/inbound/a2a-card",
                                    context=tls_context, timeout=30) as response:
            card = json.load(response)
        assert card["supportedInterfaces"][0]["url"] == env.get(
            "EXPECTED_RPC_URL", "https://host.docker.internal:38885/inbound/a2a"), card
        assert card["capabilities"]["pushNotifications"] is False, card
        assert card["securitySchemes"]["a2aApiKey"]["apiKeySecurityScheme"]["name"] == "X-A2A-Api-Key", card
        assert [s["id"] for s in card["skills"]] == ["review_duplicate_charge"], card
        print("direct HTTPS discovery, truthful endpoint/skill and API-key schema: PASS", flush=True)
        status, response = request("/v2/process-instances", {
            "processDefinitionId": "a2a-client", "variables": {"question": text}})
        assert status in (200, 201), (status, response)
        client_key = json.loads(response)["processInstanceKey"]
        deadline = time.monotonic() + 180
        while True:
            status, response = request("/v2/user-tasks/search", {"filter": {"processInstanceKey": client_key}})
            assert status == 200, (status, response)
            tasks = json.loads(response)["items"]
            review = next((t for t in tasks if t["elementId"] == "ShowResult"), None)
            if review:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("BPMN client did not reach result review")
            time.sleep(1)
        status, response = request("/v2/variables/search?truncateValues=false", {
            "filter": {"processInstanceKey": client_key, "name": "rpc"}})
        assert status == 200, (status, response)
        client_rpc = json.loads(json.loads(response)["items"][0]["value"])
        client_task = client_rpc["result"].get("task", client_rpc["result"])
        check_reconciliation(client_task)
        assert client_task["id"] != task["id"] and client_task["contextId"] != task["contextId"], client_task
        status, response = request("/v2/variables/search?truncateValues=false", {
            "filter": {"processInstanceKey": client_key, "name": "resultText"}})
        assert status == 200, (status, response)
        result_text = json.loads(json.loads(response)["items"][0]["value"])
        assert "99.9 USD" in result_text and "49.95 USD" in result_text and "REQUEST_HUMAN_REVIEW" in result_text, result_text
        status, response = request(f"/v2/user-tasks/{review['userTaskKey']}/completion", {"variables": {}})
        assert status in (200, 204), (status, response)
        deadline = time.monotonic() + 15
        while True:
            status, response = request("/v2/process-instances/search", {
                "filter": {"processInstanceKey": client_key}})
            assert status == 200, (status, response)
            instances = json.loads(response)["items"]
            if instances and instances[0]["state"] == "COMPLETED":
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("BPMN client did not complete after result review")
            time.sleep(0.25)
        print("BPMN client -> direct HTTPS A2A protocol -> real agent -> exact result -> user review: PASS", flush=True)
        record_model_inputs()
    else:
        assert task["status"]["message"]["parts"][0]["text"] == "8.8 authenticated echo", task
    status, fetched = rpc({"jsonrpc": "2.0", "id": "proof-get", "method": "GetTask",
                           "params": {"id": task["id"]}})
    assert status == 200 and fetched["result"]["id"] == task["id"], (status, fetched)
    print("completed task polling preserves expected task: PASS", flush=True)
except Exception:
    status, incidents = request("/v2/incidents/search", {"filter": {"state": "ACTIVE"}})
    for value in (env["PROOF_ENGINE_PASSWORD"], env["PROOF_A2A_API_KEY"], env["PROOF_TLS_PASSWORD"]):
        incidents = incidents.replace(value, "[REDACTED]")
    print("Active incidents:", status, incidents, flush=True)
    status, instances = request("/v2/process-instances/search", {"filter": {}, "page": {"limit": 20}})
    if status == 200:
        print("Process states:", [(p["processDefinitionId"], p["state"], p.get("tags"),
                                   p["processInstanceKey"])
                                  for p in json.loads(instances)["items"]], flush=True)
    status, variables = request("/v2/variables/search?truncateValues=false",
                                {"filter": {"name": "task"}, "page": {"limit": 20}})
    print("Task variables:", status, variables, flush=True)
    logs = subprocess.run(cmd + ["logs", "--tail", "100", "camunda", "connectors"], env=env,
                          capture_output=True, text=True, check=True).stdout
    for value in (env["PROOF_ENGINE_PASSWORD"], env["PROOF_A2A_API_KEY"], env["PROOF_TLS_PASSWORD"]):
        logs = logs.replace(value, "[REDACTED]")
    print(logs, flush=True)
    raise
finally:
    subprocess.run(cmd + ["down"], env=env, check=True)
    tls_directory.cleanup()
