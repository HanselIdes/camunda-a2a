import json
import tempfile
import unittest
from pathlib import Path

from client_versions import run

ROOT = Path(__file__).resolve().parents[2]


class ClientVersionProofTest(unittest.TestCase):
    def request(self, path, body=None, timeout=None):
        if path == "/v2/process-instances":
            self.versions.append(body["variables"]["response"]["body"]["supportedInterfaces"][0]["protocolVersion"])
            return 200, json.dumps({"processInstanceKey": "100"})
        name = body["filter"]["name"]
        if name == "rpcResponse":
            values = [{"processInstanceKey": str(index), "scopeKey": str(index),
                       "value": json.dumps({"result": {"id": "test-task"}})} for index in (1, 2)]
        elif name == "versionResult":
            values = [{"value": json.dumps({"agentUrl": "https://example.test/a2a"})}]
        elif name == "hdr":
            values = [{"value": json.dumps({"a2a-version": self.header})}]
        else:
            values = [{"value": json.dumps({"method":
                "SendMessage" if body["filter"]["processInstanceKey"] == "1" else "GetTask"})}]
        return 200, json.dumps({"items": values})

    def test_patch_cards_and_native_headers_are_both_required(self):
        self.versions, self.header = [], "1.0"
        with tempfile.TemporaryDirectory() as directory:
            run(ROOT, Path(directory), self.request, lambda files: None, "test-task",
                {"supportedInterfaces": [{"protocolVersion": "1.0", "url": "https://example.test/a2a"}]})
            report = json.loads((Path(directory) / "bpmn-client-versions.json").read_text())
            self.assertEqual(self.versions, ["1.0", "1.0.2", "1.0.999"])
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual(len(report["receivedRequestVersions"]), 2)

    def test_missing_native_header_cannot_pass(self):
        self.versions, self.header = [], None
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(AssertionError):
            run(ROOT, Path(directory), self.request, lambda files: None, "test-task",
                {"supportedInterfaces": [{"protocolVersion": "1.0", "url": "https://example.test/a2a"}]})
