import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HistoricalVerifierPreflightTest(unittest.TestCase):
    def test_current_resources_fail_before_reports_or_runtime_provisioning(self):
        verifier = Path(__file__).with_name("verify.py")
        for mode in ({}, {"PROOF_TCK_DIRECTORY": "/not-a-tck"},
                     {"PROOF_AGENT_PROCESS": "a2a-echo", "PROOF_OPERATIONAL_CHECKS": "1"}):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                reports = Path(directory) / "must-not-be-created"
                result = subprocess.run(
                    [sys.executable, str(verifier)],
                    env={**os.environ, **mode, "PROOF_REPORT_DIR": str(reports)},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("verify_client_agent.py", result.stderr)
                self.assertIn("Historical verifier modes are unsupported", result.stderr)
                self.assertFalse(reports.exists())
