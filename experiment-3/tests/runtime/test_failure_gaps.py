import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from failure_gaps import B, Z, correlation_fault, observe_fault

SOURCE = Path(__file__).resolve().parents[2] / "blueprint/profiles/basic/a2a-protocol.bpmn"


class FailureGapTest(unittest.TestCase):
    def test_only_correlation_url_changes(self):
        original = ET.parse(SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "fault.bpmn"
            correlation_fault(SOURCE, target)
            modified = ET.parse(target)
            self.assertIn(f'xmlns:bpmn="{B}"', target.read_text())
            task = next(item for item in modified.getroot().iter() if item.get("id") == "CorrelateMessage")
            url = next(item for item in task.iter(f"{{{Z}}}input") if item.get("target") == "url")
            self.assertEqual(url.get("source"), '="http://127.0.0.1:1/v2/messages/correlation"')
            old_task = next(item for item in original.getroot().iter() if item.get("id") == "CorrelateMessage")
            old_url = next(item for item in old_task.iter(f"{{{Z}}}input") if item.get("target") == "url")
            url.set("source", old_url.get("source"))
            self.assertEqual(ET.tostring(original.getroot()), ET.tostring(modified.getroot()))

    def test_success_and_empty_200_cannot_be_fault_evidence(self):
        for response in ({"result": {"status": "COMPLETED"}}, None, {}, {"error": {}, "result": {}}):
            with self.subTest(response=response), self.assertRaises(AssertionError):
                observe_fault(lambda: (200, response))

    def test_explicit_error_and_timeout_are_distinct(self):
        self.assertEqual(observe_fault(lambda: (503, "unavailable"))["client"], "explicit-error")
        with patch("failure_gaps.time.monotonic", side_effect=[10, 15]):
            def timeout():
                raise TimeoutError()
            self.assertEqual(observe_fault(timeout), {
                "client": "five-second-client-timeout", "seconds": 5})
