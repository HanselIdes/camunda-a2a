import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("gate", ROOT / "tck/check_results.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class GateAuditTest(unittest.TestCase):
    def run_gate(self, failed_requirement=False, early_skip=False):
        allowed, _, errors = gate.load_allowlist(ROOT / "tck/allowed-not-passing.txt")
        self.assertFalse(errors)
        requirements = {key: {"level": "MUST", "status": "NOT TESTED",
                              "transports": {"jsonrpc": "NOT TESTED"}, "errors": []} for key in allowed}
        requirements["CORE-SEND-001"] = {
            "level": "MUST", "status": "FAIL" if failed_requirement else "PASS",
            "transports": {"jsonrpc": "FAIL" if failed_requirement else "PASS"}, "errors": []}
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            (reports / "compatibility.json").write_text(json.dumps({"per_requirement": requirements}))
            suite = ET.Element("testsuite", tests="69" if early_skip else "68",
                               failures="0", errors="0", skipped="1" if early_skip else "0")
            for n in range(68):
                ET.SubElement(suite, "testcase", classname="synthetic_gate_unit", name=f"case_{n}")
            if early_skip:
                skipped = ET.SubElement(suite, "testcase",
                    classname="tests.compatibility.core_operations.test_transport_behavior.TestJsonRpcStreaming",
                    name="test_streaming_content_type")
                ET.SubElement(skipped, "skipped", message="Streaming capability not declared")
            ET.ElementTree(suite).write(reports / "junitreport.xml")
            with patch.dict("os.environ", {"A2A_TCK_ENGINE_AUTHORIZATION": "unit-test-authorization"}), \
                    patch.object(gate.urllib.request, "urlopen",
                                 return_value=io.BytesIO(b'{"page":{"totalItems":0}}')) as urlopen, \
                    contextlib.redirect_stdout(io.StringIO()):
                code = gate.main([str(reports)])
                request = urlopen.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "unit-test-authorization")
            audit_text = (reports / "gate.json").read_text()
            self.assertNotIn("unit-test-authorization", audit_text)
            return code, json.loads(audit_text)

    def test_every_allowlisted_requirement_retains_id_reason_and_note(self):
        code, audit = self.run_gate()
        self.assertEqual(code, 0)
        self.assertEqual(audit["verdict"], "OK")
        exclusions = [r for r in audit["mustRequirements"] if r["exclusion"]]
        self.assertEqual(len(exclusions), audit["mustAllowlisted"])
        self.assertTrue(all(r["id"] and r["exclusion"]["reason"] and r["exclusion"]["note"] for r in exclusions))

    def test_unallowlistable_failure_still_fails_gate(self):
        code, audit = self.run_gate(failed_requirement=True)
        self.assertEqual(code, 1)
        self.assertEqual(audit["verdict"], "FAIL")
        self.assertTrue(any("CORE-SEND-001" in problem for problem in audit["problems"]))

    def test_early_skip_retains_requirement_and_allowlist_reason(self):
        code, audit = self.run_gate(early_skip=True)
        self.assertEqual(code, 0)
        skipped = audit["skippedTests"][0]
        self.assertEqual(skipped["requirementIds"], ["JSONRPC-SSE-001"])
        self.assertTrue(skipped["allowlistMatches"])
        self.assertTrue(all(match["reason"] and match["note"] for match in skipped["allowlistMatches"]))


if __name__ == "__main__":
    unittest.main()
