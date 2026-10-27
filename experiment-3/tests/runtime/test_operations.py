from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from operations import B, D, controlled_model

SOURCE = Path(__file__).resolve().parents[2] / "tests/src/test/resources/bpmn/a2a-controlled-business.bpmn"


class ControlledModelTest(unittest.TestCase):
    def test_selected_process_and_di_use_the_same_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "controlled.bpmn"
            original = SOURCE.read_bytes()
            controlled_model(SOURCE, target, "a2a-echo")
            root = ET.parse(target).getroot()
            self.assertEqual(root.find(f"{{{B}}}process").get("id"), "a2a-echo")
            self.assertEqual(root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane").get("bpmnElement"), "a2a-echo")
            namespaces = {prefix: uri for _, (prefix, uri) in ET.iterparse(target, events=["start-ns"])}
            self.assertEqual(namespaces["bpmn"], B)
            self.assertEqual(SOURCE.read_bytes(), original)
            self.assertEqual(len([element for element in root.iter()
                                  if element.get("id") == "A2ACancellation"]), 1)

    def test_missing_hook_fixture_has_no_handler_message_or_dangling_di(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing-hook.bpmn"
            controlled_model(SOURCE, target, "a2a-echo", hook=False)
            root = ET.parse(target).getroot()
            identifiers = {element.get("id") for element in root.iter() if element.get("id")}
            self.assertNotIn("A2ACancellation", identifiers)
            self.assertNotIn("A2ACancelMessage", identifiers)
            self.assertIn("ControlledWork", identifiers)
            for element in root.iter():
                if element.get("bpmnElement"):
                    self.assertIn(element.get("bpmnElement"), identifiers)


if __name__ == "__main__":
    unittest.main()
