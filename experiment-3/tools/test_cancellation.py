import unittest
import xml.etree.ElementTree as ET

from bpmn_gen.cancellation import B, D, add_hook
from check_resources import ROOT


class CancellationHookTest(unittest.TestCase):
    def test_regeneration_preserves_authored_business_nodes_and_layout(self):
        root = ET.parse(ROOT / "bpmn/a2a-echo.bpmn").getroot()
        process = root.find(f"{{{B}}}process")
        authored = {element.get("id"): ET.tostring(element) for element in process
                    if element.get("id") != "A2ACancellation"}
        shapes = {element.get("bpmnElement"): ET.tostring(element) for element in root.iter(f"{{{D}}}BPMNShape")
                  if not element.get("bpmnElement").startswith("A2ACancel")
                  and element.get("bpmnElement") != "A2ASetCanceled"}
        add_hook(root)
        self.assertEqual(authored, {element.get("id"): ET.tostring(element) for element in process
                                    if element.get("id") != "A2ACancellation"})
        self.assertEqual(shapes, {element.get("bpmnElement"): ET.tostring(element)
                                 for element in root.iter(f"{{{D}}}BPMNShape")
                                 if not element.get("bpmnElement").startswith("A2ACancel")
                                 and element.get("bpmnElement") != "A2ASetCanceled"})

    def test_hook_regeneration_is_idempotent(self):
        root = ET.parse(ROOT / "bpmn/a2a-echo.bpmn").getroot()
        add_hook(root)
        ET.indent(root, space="  ")
        expected = ET.tostring(root)
        add_hook(root)
        ET.indent(root, space="  ")
        self.assertEqual(ET.tostring(root), expected)
        self.assertEqual(len([element for element in root.iter() if element.get("id") == "A2ACancellation"]), 1)


if __name__ == "__main__":
    unittest.main()
