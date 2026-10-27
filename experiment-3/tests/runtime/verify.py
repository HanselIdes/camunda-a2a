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
import xml.etree.ElementTree as ET
from pathlib import Path

from isolation import IsolatedCompose
from observations import read_root_variable
from conformance import run as run_conformance, source_snapshot

ROOT = Path(__file__).resolve().parents[2]
source_before = source_snapshot(ROOT)
if source_before["targetWorktreeDirty"]:
    raise RuntimeError("Runtime acceptance requires a clean source checkout; do not commit credentials to achieve this")
REPORTS = Path(os.environ.get("PROOF_REPORT_DIR", str(ROOT / "reports/runtime")))
REPORTS.mkdir(parents=True, exist_ok=False)
COMPOSE = os.path.join(os.path.dirname(__file__), "compose.yml")
env = dict(os.environ, PROOF_ENGINE_PASSWORD=secrets.token_urlsafe(32),
           PROOF_A2A_API_KEY=secrets.token_urlsafe(32), PROOF_TLS_PASSWORD=secrets.token_urlsafe(32))
conformance = bool(env.get("PROOF_TCK_DIRECTORY"))
env.setdefault("PROOF_AGENT_PROCESS", "a2a-tck-fixture" if conformance else "a2a-card-dispute")
allowed_agents = ("a2a-tck-fixture",) if conformance else ("a2a-card-dispute", "a2a-echo")
if env["PROOF_AGENT_PROCESS"] not in allowed_agents:
    raise ValueError("PROOF_AGENT_PROCESS must match the selected demo or conformance mode")
if env.get("PROOF_SDK_PYTHON") and env["PROOF_AGENT_PROCESS"] != "a2a-card-dispute":
    raise ValueError("PROOF_SDK_PYTHON checks the real card-dispute demo, not echo or the conformance fixture")
if env.get("PROOF_LOAD_AGENT"):
    if (env["PROOF_LOAD_AGENT"] not in ("alpha", "beta") or env["PROOF_AGENT_PROCESS"] != "a2a-echo"
            or conformance or env.get("PROOF_SDK_PYTHON")):
        raise ValueError("Workload mode requires alpha/beta, echo and no SDK/TCK mode")
    if not (Path(env["PROOF_CONTROL_DIR"]) / env["PROOF_LOAD_AGENT"]).is_dir():
        raise ValueError("Workload mode requires an existing coordinator control directory")
exporter_profile = env.setdefault("PROOF_EXPORTER_PROFILE", "low-latency")
if exporter_profile not in ("low-latency", "default"):
    raise ValueError("PROOF_EXPORTER_PROFILE must be low-latency or default")


def record_provenance(verdict, **details):
    (REPORTS / "runtime-provenance.json").write_text(json.dumps({
        **source_before, "sourceBefore": source_before, "verdict": verdict,
        "engineImage": env.get("PROOF_ENGINE_IMAGE", "camunda/camunda:8.8.21"),
        "connectorsImage": env.get("PROOF_CONNECTORS_IMAGE", "camunda/connectors-bundle:8.9.0"),
        "exporterProfile": exporter_profile,
        "exporterBulkDelaySeconds": 1 if exporter_profile == "low-latency" else 5,
        "clientExecutionThreads": 4, "activeVersionPolling": False, **details,
    }, indent=2) + "\n")


record_provenance("RUNNING")
stack = IsolatedCompose(COMPOSE, env)
cmd = stack.command
if exporter_profile == "low-latency":
    cmd.extend(["-f", str(Path(__file__).with_name("exporter-low-latency.yml"))])
engine_url = "http://127.0.0.1:" + env["PROOF_ENGINE_PORT"]
connectors_url = "https://127.0.0.1:" + env["PROOF_CONNECTORS_PORT"]
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


def request(path, body=None, authenticated=True, timeout=30):
    headers = {}
    if authenticated:
        token = base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode()
        headers["Authorization"] = "Basic " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(engine_url + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def redact(text):
    sensitive = [env[name] for name in ("PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD")]
    sensitive.append(base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode())
    for value in sensitive:
        text = text.replace(value, "[REDACTED]")
    return text


def record_exporter_configuration():
    logs = subprocess.check_output(cmd + ["logs", "--no-color", "camunda"], env=env, text=True)
    configurations = {line.split("Configuring exporter with ", 1)[1]
                      for line in logs.splitlines() if "Configuring exporter with " in line}
    if not configurations:
        raise RuntimeError("No effective exporter configuration found in startup logs")
    (REPORTS / "exporter-configurations.json").write_text(
        json.dumps([redact(config) for config in sorted(configurations)], indent=2) + "\n")
    expected_delay = 1 if exporter_profile == "low-latency" else 5
    if any(f"bulk=BulkConfiguration{{delay={expected_delay}," not in config for config in configurations):
        raise RuntimeError("Effective exporter configuration differs from the declared profile")


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
    req = urllib.request.Request(engine_url + "/v2/deployments", data=body,
                                 headers={"Authorization": "Basic " + token,
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            print("deployment status", response.status, flush=True)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"deployment {error.code}: {error.read().decode()}") from error


def rpc(body, key=True, timeout=60, version="1.0"):
    headers = {"Content-Type": "application/json"}
    if version is not None:
        headers["A2A-Version"] = version
    if key:
        headers["X-A2A-Api-Key"] = env["PROOF_A2A_API_KEY"] if key is True else key
    req = urllib.request.Request(connectors_url + "/inbound/a2a",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context) as response:
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


def assert_no_persisted_credentials():
    cursor = None
    while True:
        page = {"limit": 100}
        if cursor:
            page["after"] = cursor
        status, body = request("/v2/variables/search?truncateValues=false", {"filter": {}, "page": page})
        assert status == 200, "Cannot verify credential exclusion: variable search failed"
        variables = json.loads(body)
        forbidden = [env[name] for name in ("PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD")]
        forbidden.append(base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode())
        assert not any(value in body for value in forbidden), "Credential persisted in engine variables"
        for item in variables["items"]:
            if item["name"] == "hdr":
                assert set(json.loads(item["value"])) <= {"content-type", "a2a-version"}, \
                    "Non-allowlisted request header persisted"
        pagination = variables["page"]
        next_cursor = pagination.get("endCursor")
        if len(variables["items"]) < 100:
            break
        assert next_cursor and next_cursor != cursor, "Variable pagination made no progress"
        cursor = next_cursor
    print("All persisted process variables exclude runtime credentials and arbitrary headers: PASS", flush=True)


try:
    stack.start()
    deadline = time.monotonic() + 60
    while request("/v2/topology")[0] != 200:
        if time.monotonic() >= deadline:
            raise TimeoutError("Authenticated engine readiness deadline expired")
        time.sleep(1)
    record_exporter_configuration()
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
        if name == "unauthenticated topology":
            assert status == 401, "Engine API accepted unauthenticated access"
        elif name == "authenticated topology":
            assert status == 200, "Authenticated engine API access failed"
    agent_file = ROOT / ("tck/fixture/a2a-tck-fixture.bpmn" if conformance else
                         "blueprint/demo/a2a-card-dispute.bpmn" if demo else "bpmn/a2a-echo.bpmn")
    files = [ROOT / "blueprint/profiles/basic/a2a-protocol.bpmn", agent_file, ROOT / "dmn/a2a-validate.dmn"]
    if demo:
        files += list((ROOT / "blueprint/demo").glob("*.form"))
        files += [ROOT / "blueprint/demo/a2a-card.bpmn", ROOT / "blueprint/demo/a2a-client.bpmn"]
    elif conformance:
        card = ET.parse(ROOT / "blueprint/demo/a2a-card.bpmn")
        expression = next(p for p in card.getroot().iter()
                          if p.get("name") == "inbound.responseExpression")
        expression.set("value", """={statusCode: 200, headers: {"Content-Type": "application/json"},
          body: {name: "A2A lifecycle conformance fixture", version: "0.1.0",
          description: "Nonshipping deterministic protocol verification only.",
          supportedInterfaces: [{url: "{{secrets.A2A_RPC_URL}}", protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
          capabilities: {streaming: false, pushNotifications: false, extendedAgentCard: false},
          defaultInputModes: ["text/plain"], defaultOutputModes: ["text/plain", "application/json"],
          securitySchemes: {a2aApiKey: {apiKeySecurityScheme: {location: "header", name: "X-A2A-Api-Key"}}},
          securityRequirements: [{schemes: {a2aApiKey: {}}}],
          skills: [{id: "exercise_task_lifecycle", name: "Exercise task lifecycle",
          description: "Simulates deterministic lifecycle and artifact scenarios for conformance checks.",
          tags: ["test-only"], examples: ["Conformance lifecycle request"]}]}}""")
        fixture_card = tls_path / "conformance-card.bpmn"
        card.write(fixture_card, encoding="utf-8", xml_declaration=True)
        files += [ROOT / "tck/fixture/a2a-classify.dmn", fixture_card]
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
        with urllib.request.urlopen(connectors_url + "/inbound/a2a-card",
                                    context=tls_context, timeout=30) as response:
            card = json.load(response)
        assert card["supportedInterfaces"][0]["url"] == env.get(
            "EXPECTED_RPC_URL", "https://host.docker.internal:" + env["PROOF_CONNECTORS_PORT"] + "/inbound/a2a"), card
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
        client_rpc = read_root_variable(request, client_key, "rpc")
        client_task = client_rpc["result"].get("task", client_rpc["result"])
        check_reconciliation(client_task)
        assert client_task["id"] != task["id"] and client_task["contextId"] != task["contextId"], client_task
        result_text = read_root_variable(request, client_key, "resultText")
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
    elif not conformance:
        assert task["status"]["message"]["parts"][0]["text"] == "8.8 authenticated echo", task
    status, fetched = rpc({"jsonrpc": "2.0", "id": "proof-get", "method": "GetTask",
                           "params": {"id": task["id"]}})
    assert status == 200 and fetched["result"]["id"] == task["id"], (status, fetched)
    print("completed task polling preserves expected task: PASS", flush=True)
    auth_checks = []
    methods = ("SendMessage", "GetTask", "ListTasks", "CancelTask", "SendStreamingMessage", "SubscribeToTask",
               "GetExtendedAgentCard", "CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig",
               "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig")
    for method in methods:
        for key in (False, "invalid"):
            status, response = rpc({"jsonrpc": "2.0", "id": "unauthorized-operation", "method": method,
                                    "params": message["params"] if method == "SendMessage" else {"id": task["id"]}}, key)
            assert status == 401 and task["id"] not in str(response), (method, status, response)
            auth_checks.append({"method": method, "key": "missing" if key is False else "invalid", "status": status})
    for identifier in (task["id"], "unknown-auth-resource"):
        for key in (False, "invalid"):
            status, response = rpc({"jsonrpc": "2.0", "id": "unauthorized-resource", "method": "GetTask",
                                    "params": {"id": identifier}}, key)
            assert status == 401 and identifier not in str(response), (status, response)
    version_checks = []
    for version in ("1.0", "1.0.2", "1.0.999"):
        status, response = rpc({"jsonrpc": "2.0", "id": "patch-equivalence", "method": "GetTask",
                                "params": {"id": task["id"]}}, version=version)
        assert status == 200 and response["result"] == fetched["result"], (version, status, response)
        version_checks.append({"version": version, "sameTask": True})
    for version in ("1.1", "1.9", "2.0", "0.3", "1", "1.x", "1.0.x", "", None):
        status, response = rpc({"jsonrpc": "2.0", "id": "unsupported-version", "method": "ListTasks",
                                "params": {}}, version=version)
        assert status == 200 and response["error"]["code"] == -32009, (version, status, response)
        version_checks.append({"version": version, "errorCode": -32009})
    (REPORTS / "native-checks.json").write_text(json.dumps({
        "authentication": auth_checks, "unauthorizedResourceExistenceHidden": True,
        "versionNegotiation": version_checks, "verdict": "PASS",
    }, indent=2) + "\n")
    print("All operation key checks, unauthorized resource non-disclosure and version semantics: PASS", flush=True)
    if conformance:
        run_conformance(ROOT, REPORTS, env, engine_url, connectors_url, tls_path / "server.crt")
    elif env.get("PROOF_SDK_PYTHON"):
        sdk_env = dict(env, PROOF_SDK_CONNECTORS_URL=connectors_url,
                       PROOF_SDK_CA=str(tls_path / "server.crt"), PROOF_SDK_REPORT=str(REPORTS / "sdk.json"))
        subprocess.run([env["PROOF_SDK_PYTHON"], "-I",
                        str(Path(__file__).with_name("independent_client.py"))], env=sdk_env, check=True)
    if env.get("PROOF_LOAD_AGENT"):
        from reliability import run_agent
        run_agent(env, REPORTS, rpc, stack, deploy, ROOT)
    assert_no_persisted_credentials()
    source_after = source_snapshot(ROOT)
    if source_after != source_before:
        raise RuntimeError("Source changed during runtime verification; discard this acceptance run")
    images = {}
    for service in ("camunda", "connectors", "elasticsearch"):
        container = subprocess.check_output(cmd + ["ps", "-q", service], env=env, text=True).strip()
        image = subprocess.check_output(["docker", "inspect", "--format", "{{.Image}}", container],
                                        text=True).strip()
        digests = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image], text=True))
        images[service] = {"imageId": image, "repositoryDigests": digests}
    record_provenance("PASS", sourceAfter=source_after, images=images)
except Exception as failure:
    record_provenance("FAIL", failureType=type(failure).__name__)
    if stack.started:
        logs = subprocess.run(cmd + ["logs", "--tail", "100", "camunda", "connectors"], env=env,
                              capture_output=True, text=True)
        print("Runtime diagnostic logs (exit code", logs.returncode, "):",
              redact(logs.stdout + logs.stderr), flush=True)
        try:
            status, incidents = request("/v2/incidents/search", {"filter": {"state": "ACTIVE"}})
            print("Active incidents:", status, redact(incidents), flush=True)
            status, instances = request("/v2/process-instances/search", {"filter": {}, "page": {"limit": 20}})
            if status == 200:
                print("Process states:", [(p["processDefinitionId"], p["state"], p.get("tags"),
                                           p["processInstanceKey"])
                                          for p in json.loads(instances)["items"]], flush=True)
            status, variables = request("/v2/variables/search?truncateValues=false",
                                        {"filter": {"name": "task"}, "page": {"limit": 20}})
            print("Task variables:", status, redact(variables), flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as diagnostic_error:
            print("Engine diagnostics unavailable:", type(diagnostic_error).__name__, flush=True)
    raise
finally:
    try:
        stack.close()
    finally:
        tls_directory.cleanup()
