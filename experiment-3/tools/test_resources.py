import base64
import json
import unittest
import xml.etree.ElementTree as ET

from check_resources import PATHS, ROOT, check


RESOURCE_PATHS = (
    "blueprint/demo/01-client-agent.bpmn",
    "blueprint/profiles/basic/02-a2a-server.bpmn",
    "blueprint/demo/03-server-agent-card-dispute.bpmn",
    "blueprint/demo/04-client-agent-ask.form",
    "blueprint/demo/05-client-agent-confirm.form",
    "blueprint/demo/06-client-agent-result.form",
    "blueprint/demo/07-server-request-validation.dmn",
    "blueprint/templates/08-server-a2a-rpc-endpoint.json",
    "blueprint/templates/09-server-agent-card-endpoint.json",
    "blueprint/templates/10-server-http-json-v13.json",
    "blueprint/demo/README.md",
)
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
DI = "http://www.omg.org/spec/DD/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
Z = "http://camunda.org/schema/zeebe/1.0"


class ResourceClosureTest(unittest.TestCase):
    def setUp(self):
        self.resources = {path: (ROOT / path).read_bytes() for path in PATHS}

    def test_selected_import_set_is_closed(self):
        self.assertEqual(check(self.resources), 12)

    def test_template_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/02-a2a-server.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'zeebe:modelerTemplateVersion="13"', b'zeebe:modelerTemplateVersion="18"', 1)
        with self.assertRaisesRegex(ValueError, "missing template .*@18"):
            check(self.resources)

    def test_missing_form_is_rejected(self):
        path = "blueprint/demo/04-client-agent-ask.form"
        self.resources[path] = self.resources[path].replace(b'"a2a-client-ask"', b'"missing-form"')
        with self.assertRaisesRegex(ValueError, "unresolved formId a2a-client-ask"):
            check(self.resources)

    def test_connector_task_header_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/02-a2a-server.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'key="elementTemplateVersion" value="13"', b'key="elementTemplateVersion" value="18"', 1)
        with self.assertRaisesRegex(ValueError, "task-header template version 18 differs"):
            check(self.resources)

    def test_missing_called_process_is_rejected(self):
        path = "blueprint/demo/03-server-agent-card-dispute.bpmn"
        self.resources[path] = self.resources[path].replace(b'processId="a2a-task-update"',
                                                           b'processId="missing-process"')
        with self.assertRaisesRegex(ValueError, "unresolved processId missing-process"):
            check(self.resources)

    def test_ordered_import_manifest_and_display_names(self):
        self.assertEqual(PATHS, RESOURCE_PATHS)
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        processes = {node.get("id"): node for node in protocol.iter(f"{{{B}}}process")}
        self.assertEqual(processes["a2a-rpc"].get("name"), "02 A2A Server - Protocol and Discovery")
        self.assertIsNone(processes.get("a2a-card"))
        self.assertIsNotNone(protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='CardRequested']"))
        self.assertIsNotNone(protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='RpcReceived']"))

        server = ET.parse(ROOT / RESOURCE_PATHS[2]).getroot()
        server_process = server.find(f"{{{B}}}process")
        self.assertEqual(server_process.get("id"), "a2a-card-dispute")
        self.assertEqual(server_process.get("name"), "03 Server Agent - Synthetic Card Dispute")

        client = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        client_process = client.find(f"{{{B}}}process")
        self.assertEqual(client_process.get("id"), "a2a-client")
        self.assertEqual(client_process.get("name"), "01 Client Agent - Ask the Server")
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

    def test_agent_card_event_definition_follows_extensions_and_flow_references(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        start = protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='CardRequested']")
        tags = [child.tag for child in start]
        self.assertLess(tags.index(f"{{{B}}}extensionElements"), tags.index(f"{{{B}}}outgoing"))
        self.assertLess(tags.index(f"{{{B}}}outgoing"), tags.index(f"{{{B}}}messageEventDefinition"))

    def test_definitions_root_elements_precede_bpmn_diagrams(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        children = list(protocol)
        diagrams = [index for index, element in enumerate(children)
                    if element.tag == f"{{{D}}}BPMNDiagram"]
        relationships = [index for index, element in enumerate(children)
                         if element.tag == f"{{{B}}}relationship"]
        root_elements = [index for index, element in enumerate(children)
                         if element.tag not in (f"{{{D}}}BPMNDiagram",
                                                f"{{{B}}}relationship")]
        self.assertTrue(diagrams)
        self.assertLess(max(root_elements), min(diagrams))
        if relationships:
            self.assertLess(max(diagrams), min(relationships))

    def test_shipping_agent_loops_avoid_host_and_gateway_label(self):
        server = ET.parse(ROOT / RESOURCE_PATHS[2]).getroot()
        server_plane = server.find(f".//{{{D}}}BPMNPlane")
        route = next(edge for edge in server_plane
                     if edge.get("bpmnElement") == "Flow_FollowUp_NextTurn")
        points = [(float(point.get("x")), float(point.get("y")))
                  for point in route.findall(f"{{{DI}}}waypoint")]
        self.assertEqual(len(points), 4)
        host = next(shape for shape in server_plane if shape.get("bpmnElement") == "AgentTools")
        host_bounds = host.find(f"{{{DC}}}Bounds")
        self.assertLess(points[1][1], float(host_bounds.get("y")))

        client = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        client_plane = client.find(f".//{{{D}}}BPMNPlane")
        gateway = next(shape for shape in client_plane if shape.get("bpmnElement") == "ClientHasTools")
        label_bounds = gateway.find(
            f"{{{D}}}BPMNLabel/{{{DC}}}Bounds")
        gateway_bounds = gateway.find(f"{{{DC}}}Bounds")
        client_agent = next(shape for shape in client_plane
                            if shape.get("bpmnElement") == "ClientAgent")
        client_agent_bounds = client_agent.find(f"{{{DC}}}Bounds")
        self.assertLess(float(label_bounds.get("y")) + float(label_bounds.get("height")),
                        float(gateway_bounds.get("y")))
        self.assertGreaterEqual(
            float(label_bounds.get("x")),
            float(client_agent_bounds.get("x")) + float(client_agent_bounds.get("width")),
        )
        final_response = next(edge for edge in client_plane
                              if edge.get("bpmnElement") ==
                              "Flow_ClientHasTools_PrepareClientResult")
        final_response_bounds = final_response.find(
            f"{{{D}}}BPMNLabel/{{{DC}}}Bounds")
        final_response_x = float(final_response.find(f"{{{DI}}}waypoint").get("x"))
        self.assertLess(float(final_response_bounds.get("x"))
                        + float(final_response_bounds.get("width")), final_response_x)

    def test_protocol_drops_orphaned_auto_layout_labels(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        plane = protocol.find(f".//{{{D}}}BPMNPlane")
        for element_id in ("RpcReceived", "NewTaskReady", "NoSubscription"):
            shape = next(shape for shape in plane if shape.get("bpmnElement") == element_id)
            self.assertIsNone(shape.find(f"{{{D}}}BPMNLabel"))
        for element_id in ("IsPushMethod", "RouteRequest"):
            shape = next(shape for shape in plane if shape.get("bpmnElement") == element_id)
            bounds = shape.find(f"{{{DC}}}Bounds")
            label = shape.find(f"{{{D}}}BPMNLabel/{{{DC}}}Bounds")
            self.assertIsNotNone(label)
            self.assertLess(float(label.get("y")) + float(label.get("height")),
                            float(bounds.get("y")))

    def test_list_scan_retry_and_failure_routes_avoid_nodes(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        plane = protocol.find(f".//{{{D}}}BPMNPlane")
        route_points = {}
        for edge_id in ("Flow_ListScanDecision_WaitListVariables",
                        "Flow_ListScanDecision_FailListScan"):
            edge = next(edge for edge in plane if edge.get("bpmnElement") == edge_id)
            route_points[edge_id] = [
                (float(point.get("x")), float(point.get("y")))
                for point in edge.findall(f"{{{DI}}}waypoint")
            ]
        page_join = next(shape for shape in plane if shape.get("bpmnElement") == "ListProcessPageJoin")
        page_bounds = page_join.find(f"{{{DC}}}Bounds")
        wait = next(shape for shape in plane if shape.get("bpmnElement") == "WaitListVariables")
        wait_bounds = wait.find(f"{{{DC}}}Bounds")
        fail = next(shape for shape in plane if shape.get("bpmnElement") == "FailListScan")
        fail_bounds = fail.find(f"{{{DC}}}Bounds")

        wait_points = route_points["Flow_ListScanDecision_WaitListVariables"]
        fail_points = route_points["Flow_ListScanDecision_FailListScan"]
        self.assertLess(wait_points[2][0], float(page_bounds.get("x")))
        self.assertLess(wait_points[2][0], float(wait_bounds.get("x")))
        self.assertGreater(fail_points[2][0],
                           float(fail_bounds.get("x")) + float(fail_bounds.get("width")))
        self.assertEqual(wait_points[-1], (
            float(wait_bounds.get("x")) + float(wait_bounds.get("width")) / 2,
            float(wait_bounds.get("y")) + float(wait_bounds.get("height")),
        ))
        self.assertEqual(fail_points[-1], (
            float(fail_bounds.get("x")) + float(fail_bounds.get("width")) / 2,
            float(fail_bounds.get("y")),
        ))

    def test_obsolete_shipping_copies_are_absent(self):
        obsolete = (
            "blueprint/demo/03-client-agent.bpmn",
            "blueprint/profiles/basic/01-a2a-server.bpmn",
            "blueprint/profiles/oauth/01-a2a-server.bpmn",
            "blueprint/demo/02-server-agent-card-dispute.bpmn",
            "blueprint/templates/10-server-http-json-v12.json",
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

    def test_all_current_rest_assignments_use_version_13(self):
        template = json.loads((ROOT / "blueprint/templates/10-server-http-json-v13.json").read_text())
        self.assertEqual(template["id"], "io.camunda.connectors.HttpJson.v2")
        self.assertEqual(template["version"], 13)
        self.assertEqual(template["engines"]["camunda"], "^8.9")
        count = 0
        for directory in ("blueprint", "bpmn", "tck/fixture", "tests/src/test/resources"):
            for path in (ROOT / directory).rglob("*.bpmn"):
                for node in ET.parse(path).getroot().iter():
                    if node.get(f"{{{Z}}}modelerTemplate") != template["id"]:
                        continue
                    count += 1
                    with self.subTest(path=path, element=node.get("id")):
                        self.assertEqual(node.get(f"{{{Z}}}modelerTemplateVersion"), "13")
                        headers = {h.get("key"): h.get("value") for h in node.iter(f"{{{Z}}}header")}
                        self.assertEqual(headers["elementTemplateVersion"], "13")
        self.assertGreater(count, 0)

    def test_server_agent_preserves_template_icon(self):
        root = ET.parse(ROOT / RESOURCE_PATHS[2]).getroot()
        host = root.find(f".//{{{B}}}adHocSubProcess[@id='AgentTools']")
        self.assertEqual(host.get(f"{{{Z}}}modelerTemplate"),
                         "io.camunda.connectors.agenticai.aiagent.jobworker.v1")
        self.assertEqual(host.get(f"{{{Z}}}modelerTemplateVersion"), "5")
        icon = host.get(f"{{{Z}}}modelerTemplateIcon")
        self.assertIsNotNone(icon)
        prefix = "data:image/svg+xml;base64,"
        self.assertTrue(icon.startswith(prefix))
        svg = ET.fromstring(base64.b64decode(icon[len(prefix):], validate=True))
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")


if __name__ == "__main__":
    unittest.main()
