"""Session-only infrastructure adapter; never modifies blueprint or native checks."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
import urllib.request

ROOT = Path.cwd()
RUNTIME = ROOT / "experiment-3/tests/runtime"
OUT = Path(os.environ["PROOF_REPORT_DIR"])
CONTROL = OUT.with_name(OUT.name + "-control")
CONTROL.mkdir(mode=0o700, exist_ok=False)
sys.path.insert(0, str(RUNTIME))
import isolation


def output(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def guide_checks(env):
    destination = OUT / "exact-guide"
    destination.mkdir()
    guide = ROOT / "experiment-3/blueprint/README.md"
    blocks = re.findall(r"```bash\n(.*?)```", guide.read_text(), re.DOTALL)
    lab = next(b for b in blocks if b.startswith("A2A_CURL_ARGS=(--cacert"))
    calls = next(b for b in blocks if b.startswith('curl --fail "${A2A_CURL_ARGS[@]}" "$A2A_AGENT_CARD_URL"'))
    card, send = calls.split("\n", 1)
    poll = next(b for b in blocks if 'id\\":\\"demo-poll' in b)
    port = env["PROOF_CONNECTORS_PORT"]
    external = dict(env, A2A_CA_FILE=env["PROOF_CERTIFICATE_DIR"] + "/server.crt",
                    A2A_CONNECTORS_PORT=port, A2A_RPC_URL=f"https://host.docker.internal:{port}/inbound/a2a",
                    A2A_AGENT_CARD_URL=f"https://host.docker.internal:{port}/inbound/a2a-card",
                    A2A_API_KEY=env["PROOF_A2A_API_KEY"])
    commands = []

    def execute(name, command):
        script = lab + "\n" + command
        result = subprocess.run(["bash", "-eu", "-c", script], env=external,
                                capture_output=True, timeout=180)
        assert not any(env[k].encode() in result.stdout + result.stderr for k in (
            "PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD"))
        (destination / (name + ".body")).write_bytes(result.stdout)
        (destination / (name + ".stderr")).write_bytes(result.stderr)
        commands.append({"name": name, "exactGuideBash": script, "exitCode": result.returncode})
        write(destination / "commands.json", commands)
        assert result.returncode == 0, (name, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        assert "error" not in data, data
        return data

    discovered = execute("card", card)
    assert discovered["supportedInterfaces"][0]["url"] == external["A2A_RPC_URL"]
    assert discovered["capabilities"]["pushNotifications"] is False
    initial = execute("send", send)
    task = initial["result"]["task"]
    external["TASK_ID"] = task["id"]
    deadline = time.monotonic() + 300
    polls = 0
    while True:
        task = execute("poll-" + str(polls), poll)["result"]
        polls += 1
        assert task["id"] == external["TASK_ID"]
        if task["status"]["state"] != "TASK_STATE_WORKING":
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Exact guide task visibility expired; do not resubmit")
        time.sleep(2)
    expected = {"merchant": "Northwind Electronics", "currency": "USD",
                "chargeAmounts": [49.95, 49.95], "expectedAmount": 49.95,
                "paidAmount": 99.9, "overchargeAmount": 49.95, "matchingAmounts": True,
                "recommendation": "REQUEST_HUMAN_REVIEW", "syntheticOnly": True}
    assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
    observed = next(a for a in task["artifacts"] if a["name"] == "reconciliation")["parts"][0]["data"]
    assert observed == expected, observed
    write(destination / "assertions.json", {
        "verdict": "PASS", "guideSha256": hashlib.sha256(guide.read_bytes()).hexdigest(),
        "source": output(["git", "rev-parse", "HEAD"]), "expected": expected, "observed": observed,
        "initialState": initial["result"]["task"]["status"]["state"], "pollRequests": polls,
        "tls": "Verified validation CA and hostname; exact documented lab-only --resolve",
        "scope": "External commands only, not UI or human usability"})
    print("Literal current guide card/send/get and all nine fields: PASS", flush=True)


original_init = isolation.IsolatedCompose.__init__


def initialize(self, compose, env):
    original_init(self, compose, env)
    override = CONTROL / "infrastructure.yml"
    override.write_text("""services:
  elasticsearch:
    image: """ + os.environ["MATCHED_STORAGE_IMAGE"] + """
    mem_limit: 1536m
  camunda:
    mem_limit: 2560m
  connectors:
    mem_limit: 1g
    environment:
      JAVA_TOOL_OPTIONS: -Xmx512m -Djavax.net.ssl.trustStore=/certificates/trust.p12 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=${PROOF_TLS_PASSWORD}
""")
    self.command.extend(["-f", str(override)])
    write(CONTROL / "ownership.json", {
        "project": self.project, "enginePort": env["PROOF_ENGINE_PORT"],
        "connectorsPort": env["PROOF_CONNECTORS_PORT"],
        "storageImage": os.environ["MATCHED_STORAGE_IMAGE"],
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "modeler": "N/A: no editor used", "deployment": "REST API at engine version",
        "dockerVersion": output(["docker", "version", "--format", "{{.Server.Version}}"]),
        "composeVersion": output(["docker", "compose", "version", "--short"]),
        "pythonVersion": sys.version, "curlVersion": output(["curl", "--version"]).splitlines()[0],
        "ollamaVersion": json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/version")),
        "model": next(m for m in json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags"))["models"]
                      if m["name"] == "qwen3-coder-30b-64k:latest"),
    })


def close(self):
    self.release_ports()
    if not self.started:
        return
    try:
        provenance = OUT / "runtime-provenance.json"
        if (os.environ.get("MATCHED_EXACT_GUIDE") and provenance.exists()
                and json.loads(provenance.read_text())["verdict"] == "PASS"):
            guide_checks(self.env)
    finally:
        try:
            ids = output(self.command + ["ps", "-aq"], env=self.env).split()
            inspected = json.loads(output(["docker", "inspect", *ids])) if ids else []
            safe = []
            for container in inspected:
                safe.append({k: container[k] for k in ("Id", "Name", "Image", "State", "Mounts")})
            write(CONTROL / "containers-before-cleanup.json", safe)
            images = {}
            for container in inspected:
                image = json.loads(output(["docker", "image", "inspect", container["Image"]]))[0]
                images[container["Name"]] = {k: image.get(k) for k in (
                    "Id", "RepoTags", "RepoDigests", "Architecture", "Os")}
            write(CONTROL / "images.json", images)
            logs = output(self.command + ["logs", "--no-color"], env=self.env)
            for key in ("PROOF_ENGINE_PASSWORD", "PROOF_A2A_API_KEY", "PROOF_TLS_PASSWORD",
                        "PROOF_RESTRICTED_PASSWORD"):
                logs = logs.replace(self.env[key], "[REDACTED]")
            (CONTROL / "runtime.log").write_text(logs + "\n")
        finally:
            subprocess.run(self.command + ["down", "--volumes"], env=self.env, check=True)
            self.started = False
            remains = {}
            label = "label=com.docker.compose.project=" + self.project
            for resource in ("container", "network", "volume"):
                remains[resource] = output(["docker", resource, "ls", "-q", "--filter", label])
            assert not any(remains.values()), remains
            write(CONTROL / "cleanup.json", {
                "verdict": "PASS", "project": self.project, "remainingOwnedResources": remains,
                "completedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()})


isolation.IsolatedCompose.__init__ = initialize
isolation.IsolatedCompose.close = close
if __name__ == "__main__":
    runpy.run_path(str(RUNTIME / "verify.py"), run_name="__main__")
