"""Run the authenticated client-agent-to-server-agent flow on the isolated 8.9 profile."""
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from conformance import source_snapshot
from isolation import IsolatedCompose
from observations import read_root_variable

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = Path(__file__).with_name("compose.yml")
source_before = source_snapshot(ROOT)
if source_before["targetWorktreeDirty"]:
    raise RuntimeError("Client-agent runtime verification requires a clean committed source tree")

report_dir = Path(os.environ.get(
    "PROOF_REPORT_DIR",
    ROOT / "reports" / f"client-agent-{source_before['targetCommit'][:8]}-{secrets.token_hex(4)}",
))
report_dir.mkdir(parents=True, exist_ok=False)
report_file = report_dir / "client-agent-e2e.json"
report = {
    **source_before,
    "verdict": "RUNNING",
    "engineImage": os.environ.get("PROOF_ENGINE_IMAGE", "camunda/camunda:8.9.26"),
    "connectorsImage": os.environ.get("PROOF_CONNECTORS_IMAGE", "camunda/connectors-bundle:8.9.17"),
    "elasticsearchImage": os.environ.get(
        "PROOF_ELASTICSEARCH_IMAGE", "docker.elastic.co/elasticsearch/elasticsearch:8.19.23"),
    "llmValidationOverride": "Local Ollama; shipping Camunda-provided secret references unchanged",
    "checks": [],
}
report_file.write_text(json.dumps(report, indent=2) + "\n")

env = dict(
    os.environ,
    PROOF_ENGINE_PASSWORD=secrets.token_urlsafe(32),
    PROOF_A2A_API_KEY=secrets.token_urlsafe(32),
    PROOF_TLS_PASSWORD=secrets.token_urlsafe(32),
    PROOF_RESTRICTED_PASSWORD=secrets.token_urlsafe(32),
    PROOF_AGENT_PROCESS="a2a-card-dispute",
    PROOF_EXPORTER_PROFILE="low-latency",
)
stack = IsolatedCompose(COMPOSE, env)
stack.command.extend(["-f", str(Path(__file__).with_name("exporter-low-latency.yml"))])
tls_directory = tempfile.TemporaryDirectory(prefix="a2a-client-agent-proof-tls-")
env["PROOF_CERTIFICATE_DIR"] = tls_directory.name
tls_path = Path(tls_directory.name)
subprocess.run(
    ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
     "-subj", "/CN=host.docker.internal",
     "-addext", "subjectAltName=DNS:host.docker.internal,IP:127.0.0.1",
     "-keyout", str(tls_path / "server.key"), "-out", str(tls_path / "server.crt")],
    check=True, capture_output=True,
)
subprocess.run(
    ["openssl", "pkcs12", "-export", "-in", str(tls_path / "server.crt"),
     "-inkey", str(tls_path / "server.key"), "-out", str(tls_path / "server.p12"),
     "-passout", "env:PROOF_TLS_PASSWORD"],
    env=env, check=True, capture_output=True,
)
subprocess.run(
    ["keytool", "-importcert", "-alias", "a2a-client-agent-proof",
     "-file", str(tls_path / "server.crt"), "-keystore", str(tls_path / "trust.p12"),
     "-storetype", "PKCS12", "-storepass:env", "PROOF_TLS_PASSWORD", "-noprompt"],
    env=env, check=True, capture_output=True,
)
tls_context = ssl.create_default_context(cafile=str(tls_path / "server.crt"))
engine_url = ""
connectors_url = ""


def redact(text):
    sensitive = [env[name] for name in (
        "PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD",
        "PROOF_RESTRICTED_PASSWORD",
    )]
    sensitive.append(base64.b64encode(
        ("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()
    ).decode())
    for value in sensitive:
        text = text.replace(value, "[REDACTED]")
    return text


def engine_request(path, body=None, timeout=30):
    authorization = base64.b64encode(
        ("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()
    ).decode()
    request = urllib.request.Request(
        engine_url + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Basic " + authorization,
                 **({"Content-Type": "application/json"} if body is not None else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def rpc(body, api_key=True, timeout=60):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-A2A-Api-Key"] = env["PROOF_A2A_API_KEY"] if api_key is True else api_key
    request = urllib.request.Request(
        connectors_url + "/inbound/a2a",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def client_results(agent):
    messages = agent.get("context", {}).get("conversation", {}).get("messages", [])
    return [
        result
        for message in messages
        if message.get("role") == "tool_call_result"
        for result in message.get("results", [])
    ]


def result_body(result):
    content = result.get("content")
    if isinstance(content, str):
        content = json.loads(content)
    if isinstance(content, dict) and "toolCallResult" in content:
        content = content["toolCallResult"]
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        raise AssertionError(f"Tool {result.get('name')} did not return an object")
    return content


def task_from_rpc(response):
    result = response.get("result")
    if not isinstance(result, dict):
        raise AssertionError(f"A2A response did not contain a result: {response}")
    task = result.get("task")
    if task is None and result.get("id") and result.get("status"):
        task = result
    if not isinstance(task, dict):
        raise AssertionError(f"A2A response did not contain a task: {response}")
    return task


try:
    stack.start()
    engine_url = "http://127.0.0.1:" + env["PROOF_ENGINE_PORT"]
    connectors_url = "https://127.0.0.1:" + env["PROOF_CONNECTORS_PORT"]
    deadline = time.monotonic() + 90
    while engine_request("/v2/topology")[0] != 200:
        if time.monotonic() >= deadline:
            raise TimeoutError("Authenticated engine readiness deadline expired")
        time.sleep(1)

    resources = [
        ROOT / "blueprint/profiles/basic/01-a2a-server.bpmn",
        ROOT / "blueprint/demo/02-server-agent-card-dispute.bpmn",
        ROOT / "blueprint/demo/03-client-agent.bpmn",
        ROOT / "blueprint/demo/04-client-agent-ask.form",
        ROOT / "blueprint/demo/05-client-agent-confirm.form",
        ROOT / "blueprint/demo/06-client-agent-result.form",
        ROOT / "blueprint/demo/07-server-request-validation.dmn",
    ]
    boundary = secrets.token_hex(16)
    body = bytearray()
    for path in resources:
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"resources\"; "
                     f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    authorization = base64.b64encode(
        ("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()
    ).decode()
    request = urllib.request.Request(
        engine_url + "/v2/deployments",
        data=body,
        headers={"Authorization": "Basic " + authorization,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            assert response.status == 200, response.status
    except urllib.error.HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(f"Authenticated deployment failed with HTTP {error.code}: {detail}") from error
    report["checks"].append("authenticated 8.9 deployment of the seven BPMN/DMN/form resources")

    expected_card_url = (
        "https://host.docker.internal:" + env["PROOF_CONNECTORS_PORT"] + "/inbound/a2a"
    )
    deadline = time.monotonic() + 120
    while True:
        try:
            with urllib.request.urlopen(
                connectors_url + "/inbound/a2a-card", context=tls_context, timeout=10
            ) as response:
                card = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(1)
        except (urllib.error.URLError, http.client.RemoteDisconnected):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    assert card["supportedInterfaces"][0]["url"] == expected_card_url, card
    assert card["capabilities"]["pushNotifications"] is False, card
    assert [skill["id"] for skill in card["skills"]] == ["review_duplicate_charge"], card
    status, _ = rpc({"jsonrpc": "2.0", "id": "missing-key", "method": "ListTasks", "params": {}}, False)
    assert status == 401, f"Unauthenticated A2A request returned HTTP {status}, expected 401"
    status, _ = rpc({"jsonrpc": "2.0", "id": "invalid-key", "method": "ListTasks", "params": {}}, "invalid")
    assert status == 401, f"Invalid-key A2A request returned HTTP {status}, expected 401"
    report["checks"].append("integrated direct HTTPS Agent Card and authenticated endpoint rejection")

    question = (
        "Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. "
        "The expected charge was USD 49.95. Reconcile this example."
    )
    status, response = engine_request(
        "/v2/process-instances",
        {"processDefinitionId": "a2a-client", "variables": {"question": question}},
    )
    assert status in (200, 201), (status, response)
    client_key = json.loads(response)["processInstanceKey"]
    ask_completed = False
    ask_seen = False
    deadline = time.monotonic() + 480
    review_task = None
    ask_fields = {
        "followUp": "These are explicitly confirmed synthetic demonstration values.",
        "claimMerchant": "Northwind Electronics",
        "claimCurrency": "USD",
        "claimFirstAmount": 49.95,
        "claimSecondAmount": 49.95,
        "claimExpectedAmount": 49.95,
        "claimSyntheticOnly": True,
    }
    while True:
        status, response = engine_request(
            "/v2/user-tasks/search", {"filter": {"processInstanceKey": client_key}}
        )
        assert status == 200, (status, response)
        tasks = json.loads(response)["items"]
        ask_task = next((task for task in tasks if task["elementId"] == "AskClientForInput"), None)
        if ask_task and not ask_completed:
            ask_seen = True
            status, response = engine_request(
                f"/v2/user-tasks/{ask_task['userTaskKey']}/completion",
                {"variables": ask_fields},
            )
            assert status in (200, 204), (status, response)
            ask_completed = True
        review_task = next(
            (task for task in tasks if task["elementId"] == "ReviewClientResult"), None
        )
        if review_task:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Client agent did not reach result review within eight minutes")
        time.sleep(1)
    assert ask_seen and ask_completed, "The client agent never requested explicit user confirmation"

    agent = read_root_variable(engine_request, client_key, "clientAgent", seconds=30)
    result_text = read_root_variable(engine_request, client_key, "resultText", seconds=30)
    results = client_results(agent)
    tool_names = [result.get("name") for result in results]
    assert "DiscoverAgentCard" in tool_names, tool_names
    assert "SendA2AMessage" in tool_names, tool_names
    assert "GetA2ATask" in tool_names, tool_names
    assert "AskClientForInput" in tool_names, tool_names

    discovered = [
        result_body(result)
        for result in results if result.get("name") == "DiscoverAgentCard"
    ]
    discovered_card = next(
        (value.get("body", value) for value in discovered
         if isinstance(value.get("body", value), dict)
         and value.get("body", value).get("supportedInterfaces")),
        None,
    )
    assert discovered_card is not None, "Client tool did not return the Agent Card"
    assert discovered_card["supportedInterfaces"][0]["url"] == expected_card_url, discovered_card

    sent_tasks = []
    for result in results:
        if result.get("name") != "SendA2AMessage":
            continue
        response_body = result_body(result)
        if isinstance(response_body.get("result"), dict):
            sent_tasks.append(task_from_rpc(response_body))
    assert sent_tasks, "Client agent did not send an A2A message that created or updated a task"
    assert len({task["id"] for task in sent_tasks}) == 1, sent_tasks
    final_tasks = []
    for result in results:
        if result.get("name") != "GetA2ATask":
            continue
        response_body = result_body(result)
        if isinstance(response_body.get("result"), dict):
            final_tasks.append(task_from_rpc(response_body))
    task = next(
        (value for value in reversed(final_tasks)
         if value["status"]["state"] == "TASK_STATE_COMPLETED"),
        None,
    )
    assert task is not None, f"Client agent did not observe a completed A2A task: {final_tasks}"
    assert task["id"] == sent_tasks[0]["id"], (task, sent_tasks)
    artifact = next(item for item in task.get("artifacts", []) if item["name"] == "reconciliation")
    expected_artifact = {
        "merchant": "Northwind Electronics",
        "currency": "USD",
        "chargeAmounts": [49.95, 49.95],
        "expectedAmount": 49.95,
        "paidAmount": 99.9,
        "overchargeAmount": 49.95,
        "matchingAmounts": True,
        "recommendation": "REQUEST_HUMAN_REVIEW",
        "syntheticOnly": True,
    }
    assert artifact["parts"][0]["data"] == expected_artifact, artifact
    assert "TASK_STATE_COMPLETED" in result_text, result_text
    status, response = engine_request(
        f"/v2/user-tasks/{review_task['userTaskKey']}/completion", {"variables": {}}
    )
    assert status in (200, 204), (status, response)
    deadline = time.monotonic() + 30
    while True:
        status, response = engine_request(
            "/v2/process-instances/search", {"filter": {"processInstanceKey": client_key}}
        )
        assert status == 200, (status, response)
        instances = json.loads(response)["items"]
        if instances and instances[0]["state"] == "COMPLETED":
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Client process did not complete after result review")
        time.sleep(0.25)

    report["checks"].append(
        "client AI agent discovered the card, authenticated A2A, requested explicit confirmation, "
        "followed up, polled the same task and reviewed the exact server-agent artifact"
    )
    report.update({
        "verdict": "PASS",
        "serverTaskId": task["id"],
        "serverTaskState": task["status"]["state"],
        "artifact": expected_artifact,
        "clientProcessState": "COMPLETED",
        "clientToolCalls": tool_names,
        "providerValidation": "Local Ollama override completed the actual task-v8 client and task-v5 server calls.",
        "sourceAfter": source_snapshot(ROOT),
        "evidenceLocation": str(report_file),
    })
    assert report["sourceAfter"] == source_before, "Source changed during runtime verification"
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Client-agent 8.9 end-to-end verification PASS: {report_file}", flush=True)
except Exception as failure:
    report.update({"verdict": "FAIL", "failureType": type(failure).__name__,
                   "failureMessage": redact(str(failure))})
    if stack.started:
        diagnostics = subprocess.run(
            stack.command + ["logs", "--tail", "100", "camunda", "connectors"],
            env=env, capture_output=True, text=True, check=False,
        )
        log_path = report_dir / "runtime-diagnostic.log"
        log_path.write_text(redact(diagnostics.stdout + diagnostics.stderr))
        report["diagnosticLog"] = str(log_path)
        report["diagnosticLogExitCode"] = diagnostics.returncode
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Client-agent runtime verification failed ({type(failure).__name__}); evidence: {report_file}",
          flush=True)
    raise
finally:
    try:
        stack.close()
    finally:
        tls_directory.cleanup()
