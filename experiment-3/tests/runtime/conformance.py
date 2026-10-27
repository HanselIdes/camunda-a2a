"""Run unchanged pinned TCK assertions against the authenticated direct HTTPS target."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

TCK_SHA = "263b9cfaf16a554bdfb166a7ba5b67716e946349"
PATCHED_SOURCE_SHA256 = "8fd33aea1814e32723545d3725af254505bf990363c355679f9f779de7aed74a"


def source_snapshot(root):
    return {
        "targetCommit": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "targetWorktreeDirty": bool(subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True).strip()),
    }


def route_request(request, port, key):
    if (request.url.scheme != "https" or request.url.port != port
            or request.url.host not in ("127.0.0.1", "host.docker.internal")):
        return
    if request.url.path == "/.well-known/agent-card.json":
        request.url = request.url.copy_with(path="/inbound/a2a-card")
    # httpx appends "/" to the TCK's base URL; keep the exact advertised RPC path.
    if request.url.path == "/inbound/a2a/":
        request.url = request.url.copy_with(path="/inbound/a2a")
    if request.url.path == "/inbound/a2a":
        request.headers["X-A2A-Api-Key"] = key


def source_digest(root):
    paths = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-c", "-o", "--exclude-standard", "-z"]).split(b"\0")
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p):
        file = root / path.decode()
        data = os.readlink(file).encode() if file.is_symlink() else file.read_bytes()
        digest.update(path + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def run(root, reports, env, engine_url, connectors_url, certificate):
    checkout = Path(env["PROOF_TCK_DIRECTORY"]).resolve()
    head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if head != TCK_SHA or source_digest(checkout) != PATCHED_SOURCE_SHA256:
        raise ValueError("TCK must match the pinned commit plus the exact tracked cumulative patch")
    output = reports / "tck"
    output.mkdir(parents=True, exist_ok=False)
    target_env = dict(env, PROOF_TCK_REPORTS=str(output), PROOF_TCK_CONNECTORS_URL=connectors_url,
                      PROOF_TCK_CA=str(certificate))
    result = subprocess.run([str(checkout / ".venv/bin/python"), "-I", str(Path(__file__).resolve())],
                            cwd=checkout, env=target_env, capture_output=True, text=True)
    sensitive = [env[name] for name in ("PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD")]
    authorization = "Basic " + base64.b64encode(("proof:" + env["PROOF_ENGINE_PASSWORD"]).encode()).decode()
    sensitive.append(authorization)

    def redact(text):
        for value in sensitive:
            text = text.replace(value, "[REDACTED]")
        return text

    (output / "runner.log").write_text(redact(result.stdout + result.stderr))
    for file in output.rglob("*"):
        if file.is_file() and file.suffix in (".json", ".xml", ".html"):
            file.write_text(redact(file.read_text()))
    judge_env = dict(env, A2A_TCK_ENGINE_AUTHORIZATION=authorization)
    judge = subprocess.run([sys.executable, "-I", str(root / "tck/check_results.py"),
                            str(output), "--rest", engine_url],
                           env=judge_env, capture_output=True, text=True)
    (output / "gate.log").write_text(redact(judge.stdout + judge.stderr))
    print(redact(judge.stdout + judge.stderr), flush=True)
    (output / "provenance.json").write_text(json.dumps({
        "tckCommit": head, "patchedSourceSha256": PATCHED_SOURCE_SHA256,
        "pytestExit": result.returncode, "gateExit": judge.returncode,
        **source_snapshot(root),
        "engineImage": env.get("PROOF_ENGINE_IMAGE", "camunda/camunda:8.8.21"),
        "connectorsImage": env.get("PROOF_CONNECTORS_IMAGE", "camunda/connectors-bundle:8.9.0"),
        "exporterProfile": env["PROOF_EXPORTER_PROFILE"],
        "exporterBulkDelaySeconds": 1 if env["PROOF_EXPORTER_PROFILE"] == "low-latency" else 5,
        "clientExecutionThreads": 4,
        "activeVersionPolling": False,
        "target": "direct stock-Connectors HTTPS; explicit discovery URL; API-key trust boundary",
        "connectionAdaptations": [
            {"kind": "TLS", "change": "Trust the isolated runtime's CA; certificate verification stays enabled."},
            {"kind": "API key", "change": "Inject X-A2A-Api-Key only on the configured HTTPS RPC boundary."},
            {"kind": "card", "change": "Map well-known discovery to explicit /inbound/a2a-card; no ingress claim."},
            {"kind": "path", "change": "Remove only the runner-appended slash from the exact advertised RPC path."},
            {"kind": "host", "change": "Resolve host.docker.internal to loopback only for the isolated runtime port."},
        ],
        "assertionChanges": [],
        "timeoutChanges": [],
    }, indent=2) + "\n")
    if result.returncode or judge.returncode:
        raise RuntimeError(f"Conformance failed: pytest={result.returncode}, gate={judge.returncode}; see {output}")


def main():
    import socket
    import ssl
    import time
    from unittest.mock import patch
    from urllib.parse import urlparse

    import httpx
    import pytest

    origin = os.environ["PROOF_TCK_CONNECTORS_URL"]
    port = urlparse(origin).port
    ca = ssl.create_default_context(cafile=os.environ["PROOF_TCK_CA"])
    key = os.environ["PROOF_A2A_API_KEY"]
    original_init = httpx.Client.__init__
    original_send = httpx.Client.send
    original_resolve = socket.getaddrinfo
    timings = []

    def route(request):
        route_request(request, port, key)
        if request.url.port == port and request.url.host in ("127.0.0.1", "host.docker.internal"):
            record = {"method": request.method, "path": request.url.path,
                      "extensionsHeader": "A2A-Extensions" in request.headers}
            timings.append(record)
            request.extensions["proof_timing"] = (record, time.monotonic())

    def observe(client, request, *args, **kwargs):
        response = None
        try:
            response = original_send(client, request, *args, **kwargs)
            return response
        finally:
            timing = request.extensions.get("proof_timing")
            if timing:
                record, started = timing
                record.update(seconds=round(time.monotonic() - started, 3),
                              status=response.status_code if response is not None else None,
                              measurement="headers" if kwargs.get("stream") else "response-body")

    def configure(client, *args, **kwargs):
        hooks = dict(kwargs.get("event_hooks") or {})
        hooks["request"] = list(hooks.get("request", [])) + [route]
        kwargs.update(verify=ca, event_hooks=hooks, trust_env=False)
        original_init(client, *args, **kwargs)

    def resolve(host, service, *args, **kwargs):
        if host in ("host.docker.internal", b"host.docker.internal") and str(service) == str(port):
            host = "127.0.0.1"
        return original_resolve(host, service, *args, **kwargs)

    class Target:
        @pytest.fixture(scope="session", autouse=True)
        def direct_authenticated_target(self):
            with patch.object(httpx.Client, "__init__", configure), \
                    patch.object(httpx.Client, "send", observe), \
                    patch.object(socket, "getaddrinfo", resolve):
                try:
                    yield
                finally:
                    (Path(os.environ["PROOF_TCK_REPORTS"]) / "request-timings.json").write_text(
                        json.dumps(timings, indent=2) + "\n")

    output = Path(os.environ["PROOF_TCK_REPORTS"])
    args = ["tests/compatibility/", f"--sut-host={origin}", "--transport=jsonrpc", "-m", "must",
            "--tb=short", "-q", f"--compatibility-report={output / 'compatibility'}",
            f"--junitxml={output / 'junitreport.xml'}", f"--html={output / 'tck_report.html'}",
            "--self-contained-html"]
    sys.exit(pytest.main(args, plugins=[Target()]))


if __name__ == "__main__":
    main()
