"""Run existing provision/deploy helpers, literal guide and independent SDK only."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
import urllib.error
import urllib.request

adapter = Path(__file__).with_name("matched-latest-run.py")
spec = importlib.util.spec_from_file_location("matched_adapter", adapter)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
native = module.RUNTIME / "verify.py"
parsed = ast.parse(native.read_text(), filename=str(native))
prefix = []
for statement in parsed.body:
    if isinstance(statement, ast.Try):
        break
    prefix.append(statement)
namespace = {"__file__": str(native), "__name__": "supplemental_provisioning"}
exec(compile(ast.Module(body=prefix, type_ignores=[]), str(native), "exec"), namespace)
stack = namespace["stack"]
env = namespace["env"]
reports = namespace["REPORTS"]
try:
    stack.start()
    namespace["record_exporter_configuration"]()
    root = namespace["ROOT"]
    resources = [root / "blueprint/profiles/basic/a2a-protocol.bpmn",
                 root / "blueprint/demo/a2a-card-dispute.bpmn", root / "dmn/a2a-validate.dmn",
                 root / "blueprint/demo/a2a-card.bpmn", root / "blueprint/demo/a2a-client.bpmn",
                 *list((root / "blueprint/demo").glob("*.form"))]
    namespace["deploy"](resources)
    deadline = time.monotonic() + 120
    while True:
        try:
            with urllib.request.urlopen(namespace["connectors_url"] + "/inbound/a2a-card",
                                        context=namespace["tls_context"], timeout=10) as response:
                assert response.status == 200
            break
        except urllib.error.URLError as error:
            if ((isinstance(error, urllib.error.HTTPError) and error.code != 404)
                    or time.monotonic() >= deadline):
                raise
            print("Safe card-readiness GET pending:", type(error).__name__, flush=True)
            time.sleep(1)
    module.guide_checks(env)
    sdk_env = dict(env, PROOF_SDK_CONNECTORS_URL=namespace["connectors_url"],
                   PROOF_SDK_CA=str(namespace["tls_path"] / "server.crt"),
                   PROOF_SDK_REPORT=str(reports / "sdk.json"))
    subprocess.run([env["PROOF_SDK_PYTHON"], "-I", str(module.RUNTIME / "independent_client.py")],
                   env=sdk_env, check=True)
    namespace["assert_no_persisted_credentials"]()
    assert namespace["source_snapshot"](root) == namespace["source_before"]
    namespace["record_provenance"](
        "PASS_SUPPLEMENTAL_ONLY", checks=["literal guide", "independent SDK", "credential exclusion"],
        exclusions=["native full run remains FAIL at model-prompt verbatim assertion", "no UI"])
finally:
    try:
        stack.close()
    finally:
        namespace["tls_directory"].cleanup()
