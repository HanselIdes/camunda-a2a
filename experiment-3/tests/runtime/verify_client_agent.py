"""Run the authenticated Sub-process client journey on the isolated 8.10 profile."""
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
import xml.etree.ElementTree as ET

from conformance import source_snapshot
from confirmations import agent_history_checks
from isolation import IsolatedCompose, write_secret_store
from observations import read_root_variable

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = Path(__file__).with_name("compose.yml")
SERVER_CARD_PLACEHOLDER = "https://camunda-a2a-demo.example.com/inbound/a2a"
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
    "engineImage": os.environ.get("PROOF_ENGINE_IMAGE", "camunda/camunda:8.10.2"),
    "connectorsImage": os.environ.get("PROOF_CONNECTORS_IMAGE", "camunda/connectors-bundle:8.10.2"),
    "elasticsearchImage": os.environ.get(
        "PROOF_ELASTICSEARCH_IMAGE", "docker.elastic.co/elasticsearch/elasticsearch:8.19.23"),
    "llmValidationOverride": "Local Ollama; shipping Camunda-provided secret references unchanged",
    "checks": [],
}
report_file.write_text(json.dumps(report, indent=2) + "\n")

env = dict(
    os.environ,
    PROOF_ENGINE_IMAGE=report["engineImage"],
    PROOF_CONNECTORS_IMAGE=report["connectorsImage"],
    PROOF_ENGINE_PASSWORD=secrets.token_urlsafe(32),
    PROOF_A2A_API_KEY=secrets.token_urlsafe(32),
    PROOF_TLS_PASSWORD=secrets.token_urlsafe(32),
    PROOF_RESTRICTED_PASSWORD=secrets.token_urlsafe(32),
    PROOF_AGENT_PROCESS="a2a-card-dispute",
    PROOF_EXPORTER_PROFILE="low-latency",
)
stack = IsolatedCompose(COMPOSE, env)
stack.command.extend(["-f", str(Path(__file__).with_name("exporter-low-latency.yml"))])
stack.command.extend(["-f", str(Path(__file__).with_name("secrets-810.yml"))])
secret_directory = tempfile.TemporaryDirectory(prefix="a2a-client-secret-proof-")
secret_values = {
    "ENGINE_URL": "http://camunda:8080",
    "ENGINE_USERNAME": "proof",
    "ENGINE_PASSWORD": env["PROOF_ENGINE_PASSWORD"],
    "A2A_API_KEY": env["PROOF_A2A_API_KEY"],
    "A2A_AGENT_PROCESS": env["PROOF_AGENT_PROCESS"],
    "A2A_RPC_URL": "https://host.docker.internal:" + env["PROOF_CONNECTORS_PORT"] + "/inbound/a2a",
    "A2A_AGENT_CARD_URL": "https://host.docker.internal:" + env["PROOF_CONNECTORS_PORT"] + "/inbound/a2a-card",
    "CAMUNDA_PROVIDED_LLM_API_ENDPOINT": "http://host.docker.internal:11434/v1",
    "CAMUNDA_PROVIDED_LLM_API_KEY": "ollama",
    "CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL": "qwen3-coder-30b-64k:latest",
}
env["PROOF_SECRET_DIR"] = str(write_secret_store(secret_directory.name, secret_values))
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
        headers["X-Api-Key"] = env["PROOF_A2A_API_KEY"] if api_key is True else api_key
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
    if not (isinstance(content, list) and len(content) == 1
            and content[0].get("type") == "object"):
        raise AssertionError(f"Tool {result.get('name')} did not return one object content block")
    content = content[0]["content"]
    if isinstance(content, str):
        content = json.loads(content)
    if isinstance(content, dict) and "toolCallResult" in content:
        content = content["toolCallResult"]
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        raise AssertionError(f"Tool {result.get('name')} did not return an object")
    if result.get("name") == "SendA2AMessage":
        content = content["response"]
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
        ROOT / "blueprint/profiles/basic/02-a2a-server.bpmn",
        ROOT / "blueprint/demo/03-server-agent-card-dispute.bpmn",
        ROOT / "blueprint/demo/01-client-agent.bpmn",
        ROOT / "blueprint/demo/04-client-agent-ask.form",
        ROOT / "blueprint/demo/05-client-agent-confirm.form",
        ROOT / "blueprint/demo/06-client-agent-result.form",
        ROOT / "blueprint/demo/07-server-request-validation.dmn",
    ]
    boundary = secrets.token_hex(16)
    body = bytearray()
    for path in resources:
        contents = path.read_bytes()
        if path.name == "02-a2a-server.bpmn":
            for _, namespace in ET.iterparse(path, events=("start-ns",)):
                ET.register_namespace(*namespace)
            model = ET.fromstring(contents)
            field = model.find(
                ".//{http://camunda.org/schema/zeebe/1.0}property[@name='inbound.publicRpcUrl']"
            )
            assert field is not None and field.get("value") == SERVER_CARD_PLACEHOLDER, (
                "Expected the documented server Agent Card URL placeholder"
            )
            field.set("value", secret_values["A2A_RPC_URL"])
            contents = ET.tostring(model, encoding="utf-8", xml_declaration=True)
        body.extend((f"--{boundary}\r\nContent-Disposition: form-data; name=\"resources\"; "
                     f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode())
        body.extend(contents)
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
    report["checks"].append("authenticated 8.10 deployment of the seven BPMN/DMN/form resources")
    for expression, expected in (
        ("=camunda.secrets.A2A_API_KEY", "camunda.secrets.A2A_API_KEY"),
        ('={key: camunda.secrets.A2A_API_KEY}', {"key": "camunda.secrets.A2A_API_KEY"}),
        ('=camunda.secrets.ENGINE_URL + "/v2/topology"', "camunda.secrets.ENGINE_URL/v2/topology"),
    ):
        status, response = engine_request("/v2/expression/evaluation", {"expression": expression})
        assert status == 200, (status, response)
        evaluated = json.loads(response)
        assert evaluated["result"] == expected and not evaluated.get("warnings"), evaluated
        assert evaluated.get("referencedSecrets"), evaluated
    report["checks"].append(
        "native engine secret references reported for whole values, context leaves and URL concatenation"
    )
    agent_history_checks(ROOT, engine_request)
    report["checks"].append(
        "native engine FEEL regressions for structured 8.10 tool content, confirmed claim, "
        "response-derived task/context identity, client output mapping, server evidence "
        "and explicit card URL configuration errors"
    )

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

    monitoring = subprocess.run(
        stack.command + ["port", "camunda", "9600"],
        env=env, capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    scenario = subprocess.run(
        ["mvn", "-q", "-Dtest=BlueprintLiveScenarioIT", "test"],
        cwd=ROOT / "tests",
        env=dict(env, PROOF_ENGINE_URL=engine_url, PROOF_CONNECTORS_URL=connectors_url,
                 PROOF_MONITORING_URL="http://" + monitoring),
        capture_output=True, text=True, timeout=900,
    )
    (report_dir / "web-modeler-e2e.log").write_text(redact(scenario.stdout + scenario.stderr))
    assert scenario.returncode == 0, "Web Modeler E2E scenario failed; see web-modeler-e2e.log"
    report["checks"].append("shipped Web Modeler E2E JSON executed by the official CPT 8.10.4 runner")
    status, response = engine_request(
        "/v2/process-instances/search", {"filter": {"processDefinitionId": "a2a-client"}}
    )
    assert status == 200, (status, response)
    clients = json.loads(response)["items"]
    assert len(clients) == 1 and clients[0]["state"] == "COMPLETED", clients
    client_key = clients[0]["processInstanceKey"]
    status, response = engine_request(
        "/v2/user-tasks/search", {"filter": {"processInstanceKey": client_key}}
    )
    assert status == 200, (status, response)
    completed_tasks = json.loads(response)["items"]
    ask_completed = any(task["elementId"] == "AskClientForInput" and task["state"] == "COMPLETED"
                        for task in completed_tasks)
    assert ask_completed, "The client agent never requested explicit user confirmation"

    agent = read_root_variable(engine_request, client_key, "clientAgent", seconds=30)
    result_text = read_root_variable(engine_request, client_key, "resultText", seconds=30)
    discovered_card = read_root_variable(engine_request, client_key, "agentCard", seconds=30)
    results = client_results(agent)
    tool_names = [result.get("name") for result in results]
    assert "DiscoverAgentCard" not in tool_names, tool_names
    assert "SendA2AMessage" in tool_names, tool_names
    assert "GetA2ATask" not in tool_names, tool_names
    assert "AskClientForInput" in tool_names, tool_names

    assert isinstance(discovered_card, dict), discovered_card
    assert discovered_card["supportedInterfaces"][0]["url"] == expected_card_url, discovered_card
    confirmation_result = result_body(next(
        result for result in results if result.get("name") == "AskClientForInput"
    ))
    expected_claim = {
        "merchant": "Northwind Electronics",
        "currency": "USD",
        "chargeAmounts": [49.95, 49.95],
        "expectedAmount": 49.95,
        "syntheticOnly": True,
    }
    assert confirmation_result["syntheticClaim"] == expected_claim, confirmation_result
    scenario_cases = json.loads(
        (ROOT / "blueprint/demo/01-client-agent.integration.test.json").read_text()
    )
    confirmation_step = next(
        instruction for instruction in scenario_cases["testCases"][0]["instructions"]
        if instruction["type"] == "COMPLETE_USER_TASK"
        and instruction["userTaskSelector"]["elementId"] == "AskClientForInput"
    )
    assert confirmation_result["text"] == confirmation_step["variables"]["followUp"], confirmation_result

    sent_tasks = []
    for result in results:
        if result.get("name") != "SendA2AMessage":
            continue
        response_body = result_body(result)
        if isinstance(response_body.get("result"), dict):
            sent_tasks.append(task_from_rpc(response_body))
    assert sent_tasks, "Client agent did not send an A2A message that created or updated a task"
    assert len({task["id"] for task in sent_tasks}) == 2, sent_tasks
    assert len({task["contextId"] for task in sent_tasks}) == 1, sent_tasks
    task = next(
        (value for value in sent_tasks
         if value["id"] == sent_tasks[0]["id"]
         and value["status"]["state"] == "TASK_STATE_COMPLETED"),
        None,
    )
    assert task is not None, f"Client subprocess did not return a completed A2A task: {sent_tasks}"
    assert task["id"] == sent_tasks[0]["id"], (task, sent_tasks)
    feedback_task = sent_tasks[-1]
    assert feedback_task["id"] != task["id"], (task, feedback_task)
    assert feedback_task["status"]["state"] == "TASK_STATE_COMPLETED", feedback_task
    reviews = [item for item in completed_tasks
               if item["elementId"] == "ReviewClientResult" and item["state"] == "COMPLETED"]
    assert len(reviews) == 2, reviews
    status, response = engine_request(
        "/v2/variables/search?truncateValues=false",
        {"filter": {"processInstanceKey": client_key, "name": "data"}},
    )
    assert status == 200, (status, response)
    budgets = sorted(json.loads(response)["items"], key=lambda item: int(item["scopeKey"]))
    assert len(budgets) == 2, budgets
    ceilings = [json.loads(item["value"])["limits"]["maxModelCalls"] for item in budgets]
    report["observedModelCallCeilings"] = ceilings
    report["observedFinalMetrics"] = agent["context"].get("metrics")
    # The mapped ceiling freezes the entry-time metric; agentContext can change during tool calls.
    prior_calls = ceilings[1] - 8
    assert ceilings[0] == 8 and prior_calls > 0, ceilings
    final_calls = agent["context"]["metrics"]["modelCalls"]
    assert prior_calls < final_calls <= ceilings[1], (prior_calls, final_calls, ceilings)
    user_messages = [
        message for message in task.get("history", [])
        if message.get("role") == "ROLE_USER"
    ]
    assert len(user_messages) >= 2, f"Expected initial and confirmed A2A messages: {user_messages}"
    initial_data_parts = [
        part for part in user_messages[0].get("parts", [])
        if isinstance(part, dict) and "data" in part
    ]
    assert not initial_data_parts, (
        f"Client sent structured data before explicit confirmation: {initial_data_parts}"
    )
    confirmed_parts = [
        part for message in user_messages[1:] for part in message.get("parts", [])
        if isinstance(part, dict) and "data" in part
    ]
    assert len(confirmed_parts) == 1, (
        f"Expected one confirmed synthetic data part after the initial message: {confirmed_parts}"
    )
    assert confirmed_parts[0]["data"].get("syntheticClaim") == expected_claim, confirmed_parts
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
    feedback_artifact = next(
        item for item in feedback_task.get("artifacts", []) if item["name"] == "reconciliation")
    assert feedback_artifact["parts"][0]["data"] == expected_artifact, feedback_artifact
    assert "TASK_STATE_COMPLETED" in result_text, result_text
    credentials = (env["PROOF_ENGINE_PASSWORD"], env["PROOF_A2A_API_KEY"], authorization)
    cursor = None
    while True:
        page = {"limit": 100}
        if cursor:
            page["after"] = cursor
        status, response = engine_request(
            "/v2/variables/search?truncateValues=false", {"filter": {}, "page": page}
        )
        assert status == 200, (status, response)
        assert not any(value in response for value in credentials), "Credential persisted in variables"
        variables = json.loads(response)
        cursor = variables.get("page", {}).get("endCursor")
        if not variables["items"] or len(variables["items"]) < 100:
            break
        assert cursor, "Variable search did not return a continuation cursor"
    report["checks"].append(
        "random engine password, A2A API key and Basic credential absent from untruncated persisted variables"
    )
    logs = subprocess.run(
        stack.command + ["logs", "--no-color", "camunda", "connectors"],
        env=env, capture_output=True, text=True, check=True, timeout=30,
    )
    assert not any(value in logs.stdout + logs.stderr for value in credentials), \
        "Credential found in owned engine/Connectors runtime logs"
    report["checks"].append(
        "random engine password, A2A API key and Basic credential absent from owned engine/Connectors logs"
    )

    report["checks"].append(
        "client AI agent discovered the card, authenticated A2A, requested explicit confirmation, "
        "continued the same task through its subprocess and reviewed the exact server-agent artifact"
    )
    report["checks"].append(
        "live user-feedback re-entry retained conversation and server context, created a new completed "
        "task with the exact artifact and used a fresh eight-call allowance without resetting metrics"
    )
    report.update({
        "verdict": "PASS",
        "serverTaskId": task["id"],
        "serverTaskState": task["status"]["state"],
        "feedbackTaskId": feedback_task["id"],
        "modelCallCeilings": ceilings,
        "modelCallsBeforeFeedback": prior_calls,
        "modelCallsAfterFeedback": final_calls,
        "artifact": expected_artifact,
        "clientProcessState": "COMPLETED",
        "clientToolCalls": tool_names,
        "assertedBehavior": {
            "clientRequestedExplicitConfirmation": ask_completed,
            "initialUserMessageContainsStructuredClaim": bool(initial_data_parts),
            "confirmedFollowUpStructuredClaimParts": len(confirmed_parts),
            "followUpReusedInitialTaskAndContext": True,
            "completedTaskReturnedBySendSubprocess": True,
        },
        "providerValidation": "Local Ollama override completed the actual Sub-process-v2 client and Job-Worker-v5 server calls.",
        "secretResolution": {
            "syntax": "camunda.secrets",
            "store": "disposable engine default file store",
            "secretNames": sorted(secret_values),
            "persistedCredentialLeakCheck": "PASS",
            "runtimeLogCredentialLeakCheck": "PASS",
        },
        "sourceAfter": source_snapshot(ROOT),
        "evidenceLocation": str(report_file),
    })
    assert report["sourceAfter"] == source_before, "Source changed during runtime verification"
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Client-agent 8.10 end-to-end verification PASS: {report_file}", flush=True)
    if os.environ.get("PROOF_HUB_HANDOFF") == "1":
        grpc_address = subprocess.run(
            stack.command + ["port", "camunda", "26500"],
            env=env, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
        handoff_dir = report_dir / "hub-runtime"
        handoff_dir.mkdir(mode=0o700)
        handoff_file = handoff_dir / "connection.json"
        release_file = handoff_dir / "release"
        with os.fdopen(os.open(handoff_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump({
                "source": source_before["targetCommit"],
                "engineUrl": engine_url,
                "connectorsUrl": connectors_url,
                "monitoringUrl": "http://" + monitoring,
                "grpcUrl": "http://" + grpc_address,
                "engineImage": report["engineImage"],
                "connectorsImage": report["connectorsImage"],
                "username": "proof",
                "password": env["PROOF_ENGINE_PASSWORD"],
                "secretDirectory": secret_directory.name,
                "certificateDirectory": tls_directory.name,
                "composeProject": stack.project,
                "releaseFile": str(release_file),
                "expiresAt": time.time() + 3600,
            }, stream, indent=2)
        print(f"Owned Hub runtime lease ready: {handoff_file}", flush=True)
        lease_deadline = time.monotonic() + 3600
        while not release_file.exists() and time.monotonic() < lease_deadline:
            time.sleep(2)
        print("Owned Hub runtime lease ended; cleaning up", flush=True)
        handoff_file.unlink()
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
        secret_directory.cleanup()
