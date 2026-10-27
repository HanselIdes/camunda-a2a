import unittest
import xml.etree.ElementTree as ET

from check_resources import PATHS, ROOT, check


RESOURCE_PATHS = (
    "blueprint/profiles/basic/01-a2a-server.bpmn",
    "blueprint/demo/02-server-agent-card-dispute.bpmn",
    "blueprint/demo/03-client-agent.bpmn",
    "blueprint/demo/04-client-agent-ask.form",
    "blueprint/demo/05-client-agent-confirm.form",
    "blueprint/demo/06-client-agent-result.form",
    "blueprint/demo/07-server-request-validation.dmn",
    "blueprint/templates/08-server-a2a-rpc-endpoint.json",
    "blueprint/templates/09-server-agent-card-endpoint.json",
    "blueprint/templates/10-server-http-json-v12.json",
    "blueprint/demo/README.md",
)
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z = "http://camunda.org/schema/zeebe/1.0"


class ResourceClosureTest(unittest.TestCase):
    def setUp(self):
        self.resources = {path: (ROOT / path).read_bytes() for path in PATHS}

    def test_selected_import_set_is_closed(self):
        self.assertEqual(check(self.resources), 12)

    def test_template_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/01-a2a-server.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'zeebe:modelerTemplateVersion="12"', b'zeebe:modelerTemplateVersion="18"', 1)
        with self.assertRaisesRegex(ValueError, "missing template .*@18"):
            check(self.resources)

    def test_missing_form_is_rejected(self):
        path = "blueprint/demo/04-client-agent-ask.form"
        self.resources[path] = self.resources[path].replace(b'"a2a-client-ask"', b'"missing-form"')
        with self.assertRaisesRegex(ValueError, "unresolved formId a2a-client-ask"):
            check(self.resources)

    def test_connector_task_header_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/01-a2a-server.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'key="elementTemplateVersion" value="12"', b'key="elementTemplateVersion" value="18"', 1)
        with self.assertRaisesRegex(ValueError, "task-header template version 18 differs"):
            check(self.resources)

    def test_missing_called_process_is_rejected(self):
        path = "blueprint/demo/02-server-agent-card-dispute.bpmn"
        self.resources[path] = self.resources[path].replace(b'processId="a2a-task-update"',
                                                           b'processId="missing-process"')
        with self.assertRaisesRegex(ValueError, "unresolved processId missing-process"):
            check(self.resources)

    def test_ordered_import_manifest_and_display_names(self):
        self.assertEqual(PATHS, RESOURCE_PATHS)
        protocol = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        processes = {node.get("id"): node for node in protocol.iter(f"{{{B}}}process")}
        self.assertEqual(processes["a2a-rpc"].get("name"), "01 A2A Server - Protocol and Discovery")
        self.assertIsNone(processes.get("a2a-card"))
        self.assertIsNotNone(protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='CardRequested']"))
        self.assertIsNotNone(protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='RpcReceived']"))

        server = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        server_process = server.find(f"{{{B}}}process")
        self.assertEqual(server_process.get("id"), "a2a-card-dispute")
        self.assertEqual(server_process.get("name"), "02 Server Agent - Synthetic Card Dispute")

        client = ET.parse(ROOT / RESOURCE_PATHS[2]).getroot()
        client_process = client.find(f"{{{B}}}process")
        self.assertEqual(client_process.get("id"), "a2a-client")
        self.assertEqual(client_process.get("name"), "03 Client Agent - Ask the Server")
        client_agent = client.find(f".//{{{B}}}serviceTask[@id='ClientAgent']")
        self.assertEqual(client_agent.get(f"{{{Z}}}modelerTemplate"),
                         "io.camunda.connectors.agenticai.aiagent.v1")
        self.assertEqual(client_agent.get(f"{{{Z}}}modelerTemplateVersion"), "8")
        tools = client.find(f".//{{{B}}}adHocSubProcess[@id='ClientTools']")
        loop = tools.find(f"{{{B}}}multiInstanceLoopCharacteristics")
        loop_mapping = loop.find(f"{{{B}}}extensionElements/{{{Z}}}loopCharacteristics")
        self.assertEqual(loop_mapping.get("inputCollection"), "=clientAgent.toolCalls")
        tool_ids = {node.get("id") for node in tools}
        self.assertTrue({"DiscoverAgentCard", "SendA2AMessage", "GetA2ATask", "AskClientForInput"}
                        .issubset(tool_ids))

    def test_obsolete_shipping_copies_are_absent(self):
        obsolete = (
            "blueprint/profiles/basic/a2a-protocol.bpmn",
            "blueprint/profiles/oauth/a2a-protocol.bpmn",
            "blueprint/demo/a2a-card.bpmn",
            "blueprint/demo/a2a-card-dispute.bpmn",
            "blueprint/demo/a2a-client.bpmn",
            "blueprint/demo/a2a-client-ask.form",
            "blueprint/demo/a2a-client-answer.form",
            "blueprint/demo/a2a-client-result.form",
            "blueprint/templates/a2a-core-card.json",
            "blueprint/templates/a2a-core-rpc.json",
            "blueprint/templates/http-json.json",
            "blueprint/templates/11-client-ai-agent-task-v8.json",
        )
        for path in obsolete:
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists())


if __name__ == "__main__":
    unittest.main()
