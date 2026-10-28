import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from failures import B, Z, fault_model

SOURCE = Path(__file__).resolve().parents[2] / "blueprint/profiles/basic/02-a2a-server.bpmn"


class FailureFixtureTest(unittest.TestCase):
    def test_faults_are_local_to_create_task_and_never_embed_credentials(self):
        original = SOURCE.read_bytes()
        for mode, target, expected in (
                ("invalid-credentials", "authentication.password", "deliberately-invalid-noncredential"),
                ("insufficient-permissions", "authentication.password", "{{secrets.PROOF_RESTRICTED_PASSWORD}}"),
                ("revoked-credentials", "authentication.password", "{{secrets.PROOF_RESTRICTED_PASSWORD}}"),
                ("unreachable-engine-endpoint", "url", '="http://127.0.0.1:1/v2/process-instances"')):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "fault.bpmn"
                fault_model(SOURCE, output, mode)
                self.assertIn(f'xmlns:bpmn="{B}"', output.read_text())
                tree = ET.parse(output)
                task = next(item for item in tree.getroot().iter() if item.get("id") == "CreateTask")
                inputs = {item.get("target"): item.get("source") for item in task.iter(f"{{{Z}}}input")}
                self.assertEqual(inputs[target], expected)
                self.assertEqual(task.find(f"{{{B}}}extensionElements/{{{Z}}}taskDefinition").get("retries"), "1")
                self.assertEqual(inputs["connectionTimeoutInSeconds"], "=1")
                other = next(item for item in tree.getroot().iter() if item.get("id") == "CorrelateMessage")
                password = next(item.get("source") for item in other.iter(f"{{{Z}}}input")
                                if item.get("target") == "authentication.password")
                self.assertEqual(password, "{{secrets.ENGINE_PASSWORD}}")
        self.assertEqual(SOURCE.read_bytes(), original)
