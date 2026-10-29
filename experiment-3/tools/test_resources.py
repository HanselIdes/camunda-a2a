import base64
import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from check_resources import PATHS, ROOT, check
from bpmn_gen.secrets import current_secret_expression


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
    "blueprint/templates/11-client-a2a.json",
    "blueprint/templates/12-client-agent-feedback.json",
    "blueprint/demo/01-client-agent.integration.test.json",
    "blueprint/profiles/basic/02-a2a-server.test.json",
    "blueprint/demo/03-server-agent-card-dispute.test.json",
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
        self.assertEqual(check(self.resources), 17)

    def test_intermediate_builder_cli_cannot_overwrite_current_resources(self):
        before = {path: (ROOT / path).read_bytes() for path in PATHS}
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory) / "protocol.bpmn"
            output.write_text("must remain untouched")
            for arguments in (["--check"], ["--authentication", "basic", "--output", str(output)]):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools/build_core.py"), *arguments],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("build_blueprint.py", result.stderr)
                self.assertIn("--check", result.stderr)
                self.assertEqual(output.read_text(), "must remain untouched")
        self.assertEqual(before, {path: (ROOT / path).read_bytes() for path in PATHS})

    def test_current_secret_references_are_feel_and_keep_names(self):
        names = set()
        for path in ROOT.joinpath("blueprint").rglob("*"):
            if path.suffix != ".bpmn":
                continue
            text = path.read_text()
            self.assertNotIn("{{secrets.", text, path)
            self.assertNotIn("X-A2A-Api-Key", text, path)
            self.assertNotIn("x-a2a-api-key", text, path)
            self.assertNotRegex(text, r'["\']camunda\.secrets\.', path)
            names.update(re.findall(r"camunda\.secrets\.([A-Za-z_][A-Za-z0-9_]*)", text))
        self.assertEqual(names, {
            "ENGINE_URL", "ENGINE_USERNAME", "ENGINE_PASSWORD", "ENGINE_OAUTH_TOKEN_ENDPOINT",
            "ENGINE_CLIENT_ID", "ENGINE_CLIENT_SECRET", "ENGINE_AUDIENCE", "A2A_API_KEY",
            "A2A_RPC_URL", "A2A_AGENT_CARD_URL", "A2A_AGENT_PROCESS",
            "CAMUNDA_PROVIDED_LLM_API_ENDPOINT", "CAMUNDA_PROVIDED_LLM_API_KEY",
            "CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL",
        })
        for name in ("rpc", "card"):
            filename = ("08-server-a2a-rpc-endpoint.json" if name == "rpc"
                        else "09-server-agent-card-endpoint.json")
            template = json.loads((ROOT / "blueprint/templates" / filename).read_text())
            self.assertEqual(template["engines"]["camunda"], "^8.9")
            self.assertEqual(template["version"], 3)
            if name == "rpc":
                key = next(p for p in template["properties"] if p.get("id") == "inbound.auth.apiKey")
                self.assertEqual(key["value"], "{{secrets.A2A_API_KEY}}")
        template = json.loads((ROOT / "blueprint/templates/11-client-a2a.json").read_text())
        self.assertEqual(template["version"], 3)
        self.assertEqual(template["engines"]["camunda"], "^8.9")
        key = next(p for p in template["properties"] if p.get("id") == "apiKey")
        self.assertEqual(key["value"], "{{secrets.A2A_API_KEY}}")

    def test_secret_migration_preserves_feel_composition(self):
        self.assertEqual(current_secret_expression("{{secrets.TOKEN}}"), "=camunda.secrets.TOKEN")
        self.assertEqual(current_secret_expression('="{{secrets.URL}}" + "/v2"'),
                         '=camunda.secrets.URL + "/v2"')
        self.assertEqual(current_secret_expression('={key: "{{secrets.TOKEN}}"}'),
                         '={key: camunda.secrets.TOKEN}')
        with self.assertRaises(ValueError):
            current_secret_expression('="prefix-{{secrets.TOKEN}}"')

    def test_card_public_url_is_explicit_required_and_not_a_secret_callback(self):
        template = json.loads((ROOT / "blueprint/templates/09-server-agent-card-endpoint.json").read_text())
        field = next(p for p in template["properties"] if p.get("id") == "inbound.publicRpcUrl")
        self.assertEqual(field["value"], "")
        self.assertEqual(field["type"], "String")
        self.assertTrue(field["constraints"]["notEmpty"])
        pattern = field["constraints"]["pattern"]["value"]
        self.assertIsNotNone(re.fullmatch(pattern, "https://example.test/cluster/inbound/a2a"))
        for invalid in ("", "http://example.test/inbound/a2a", "https://example.test/has space"):
            self.assertIsNone(re.fullmatch(pattern, invalid))
        for profile in ("basic", "oauth"):
            root = ET.parse(ROOT / f"blueprint/profiles/{profile}/02-a2a-server.bpmn").getroot()
            properties = root.find(
                f".//{{{B}}}startEvent[@id='CardRequested']/{{{B}}}extensionElements/{{{Z}}}properties"
            )
            field = properties.find(f"{{{Z}}}property[@name='inbound.publicRpcUrl']")
            self.assertEqual(field.get("value"),
                             "https://camunda-a2a-demo.example.com/inbound/a2a")
            documentation = root.find(
                f".//{{{B}}}startEvent[@id='CardRequested']/{{{B}}}documentation").text
            self.assertIn("nonfunctional", documentation)
            self.assertIn("Replace it", documentation)
            response = properties.find(f"{{{Z}}}property[@name='inbound.responseExpression']").get("value")
            self.assertNotIn("camunda.secrets", response)
            self.assertIn("inbound.publicRpcUrl", response)
            self.assertIn('name: "X-Api-Key"', response)
            self.assertIn("statusCode: 500", response)
            template_response = next(p["value"] for p in template["properties"]
                                     if p.get("id") == "inbound.responseExpression")
            self.assertEqual(template_response, response)

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

    def test_missing_client_template_is_rejected(self):
        path = "blueprint/templates/11-client-a2a.json"
        data = json.loads(self.resources[path])
        data["id"] = "missing-client-template"
        self.resources[path] = json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError, "missing template dev.hansel.a2a.client.v1@3"):
            check(self.resources)

    def test_missing_scenario_process_is_rejected(self):
        path = "blueprint/demo/01-client-agent.integration.test.json"
        data = json.loads(self.resources[path])
        data["processId"] = "missing-process"
        self.resources[path] = json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError, "unresolved scenario processId missing-process"):
            check(self.resources)

    def test_empty_scenarios_are_rejected(self):
        path = "blueprint/profiles/basic/02-a2a-server.test.json"
        data = json.loads(self.resources[path])
        data["testCases"] = []
        self.resources[path] = json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError, "missing Web Modeler test cases"):
            check(self.resources)

    def test_web_modeler_scenarios_reference_current_process_elements(self):
        processes = {}
        for path, content in self.resources.items():
            if path.endswith(".bpmn"):
                processes.update({p.get("id"): p for p in ET.fromstring(content).iter(f"{{{B}}}process")})

        def references(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("elementId", "afterElementId"):
                        yield key, child
                    elif key == "processDefinitionId":
                        yield key, child
                    elif key != "variables":
                        yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)

        for path, content in self.resources.items():
            if not path.endswith(".test.json"):
                continue
            data = json.loads(content)
            self.assertEqual(data["$schema"],
                             "https://camunda.com/json-schema/cpt-test-cases/8.10/schema.json")
            element_ids = {e.get("id") for e in processes[data["processId"]].iter() if e.get("id")}
            for key, reference in references(data["testCases"]):
                with self.subTest(path=path, reference=reference):
                    self.assertIn(reference, processes if key == "processDefinitionId" else element_ids)

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
        client_agent = client.find(f".//{{{B}}}adHocSubProcess[@id='ClientAgent']")
        self.assertEqual(client_agent.get(f"{{{Z}}}modelerTemplate"),
                         "dev.hansel.a2a.client-agent.v1")
        self.assertEqual(client_agent.get(f"{{{Z}}}modelerTemplateVersion"), "1")
        self.assertIsNone(client_agent.find(f"{{{B}}}multiInstanceLoopCharacteristics"))
        self.assertIsNone(client.find(f".//*[@id='ClientTools']"))
        self.assertIsNone(client.find(f".//*[@id='ClientHasTools']"))
        definition = client_agent.find(f"{{{B}}}extensionElements/{{{Z}}}taskDefinition")
        self.assertEqual(definition.get("type"), "io.camunda.agenticai:aiagent:subprocess:2")
        inputs = {e.get("target"): e.get("source") for e in client_agent.findall(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input")}
        self.assertEqual(inputs["agentContext"], "=clientAgent.context")
        self.assertEqual(inputs["data.limits.maxModelCalls"],
                         "=(if agentContext.metrics.modelCalls instance of number "
                         "then agentContext.metrics.modelCalls else 0) + 8")
        self.assertEqual(inputs["data.response.includeAgentContext"], "true")
        template = json.loads(self.resources["blueprint/templates/12-client-agent-feedback.json"])
        limit = next(p for p in template["properties"] if p.get("id") == "data.limits.maxModelCalls")
        self.assertEqual((limit["type"], limit["feel"]), ("Text", "required"))
        self.assertEqual(client.get("{http://camunda.org/schema/modeler/1.0}executionPlatformVersion"),
                         "8.10.0")
        output = client_agent.find(f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}output")
        self.assertEqual((output.get("source"), output.get("target")), ("=agent", "clientAgent"))
        tool_ids = {node.get("id") for node in client_agent}
        root_tools = {"ReadIntakeGuidance", "CheckConfirmedDetails", "DraftReviewNote",
                      "SendA2AMessage", "AskClientForInput"}
        self.assertEqual(tool_ids - {None}, root_tools)
        for node in client_agent:
            if node.get("id") in root_tools:
                self.assertIsNone(node.find(f"{{{B}}}incoming"))
                self.assertIsNotNone(node.find(f"{{{B}}}documentation"))
                self.assertIn("toolCallResult", ET.tostring(node).decode())
        discovery = client_process.find(f"{{{B}}}serviceTask[@id='DiscoverAgentCard']")
        self.assertIsNotNone(discovery)
        remote = client_agent.find(f"{{{B}}}subProcess[@id='SendA2AMessage']")
        self.assertIsNotNone(remote.find(f"{{{B}}}serviceTask[@id='SendRemoteMessage']"))
        self.assertIsNotNone(remote.find(f"{{{B}}}serviceTask[@id='GetA2ATask']"))
        for node in (discovery, *remote.findall(f"{{{B}}}serviceTask")):
            self.assertEqual(node.get(f"{{{Z}}}modelerTemplate"), "dev.hansel.a2a.client.v1")
            self.assertEqual(node.get(f"{{{Z}}}modelerTemplateVersion"), "3")

    def test_agent_card_event_definition_follows_extensions_and_flow_references(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        start = protocol.find(
            f".//{{{B}}}process[@id='a2a-rpc']/{{{B}}}startEvent[@id='CardRequested']")
        tags = [child.tag for child in start]
        self.assertLess(tags.index(f"{{{B}}}extensionElements"), tags.index(f"{{{B}}}outgoing"))
        self.assertLess(tags.index(f"{{{B}}}outgoing"), tags.index(f"{{{B}}}messageEventDefinition"))

    def test_client_confirmation_and_remote_identity_are_not_model_supplied(self):
        root = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        remote = root.find(f".//{{{B}}}subProcess[@id='SendA2AMessage']")
        inputs = {e.get("target"): e.get("source") for e in remote.findall(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input")}
        self.assertEqual(set(inputs), {"remoteText", "previousTask", "confirmedParts", "remoteResponse"})
        self.assertEqual(inputs["remoteResponse"], "=null")
        self.assertIn("fromAi(toolCall.text,", inputs["remoteText"])
        for key in ("confirmedParts", "previousTask"):
            self.assertNotIn("fromAi(", inputs[key])
            self.assertIn('content[item.type = "object"][1].content', inputs[key])
        self.assertIn('message.results[item.name = "AskClientForInput"]', inputs["confirmedParts"])
        self.assertIn("syntheticClaim: result.syntheticClaim", inputs["confirmedParts"])
        self.assertIn('message.results[item.name = "SendA2AMessage"]', inputs["previousTask"])
        self.assertIn("{taskId: task.id, contextId: task.contextId}", inputs["previousTask"])
        for state in ("COMPLETED", "CANCELED", "FAILED", "REJECTED"):
            self.assertIn(f"TASK_STATE_{state}", inputs["previousTask"])
        self.assertIn("{contextId: task.contextId}", inputs["previousTask"])
        form_task = root.find(f".//{{{B}}}userTask[@id='AskClientForInput']")
        confirmation = form_task.find(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}output").get("source")
        for field in ("claimMerchant", "claimCurrency", "claimFirstAmount",
                      "claimSecondAmount", "claimExpectedAmount", "claimSyntheticOnly"):
            self.assertIn(field, confirmation)
        self.assertNotIn("fromAi(", confirmation)
        send = remote.find(f"{{{B}}}serviceTask[@id='SendRemoteMessage']")
        send_inputs = {e.get("target"): e.get("source") for e in send.findall(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input")}
        self.assertIn("confirmedParts", send_inputs["message"])
        self.assertIn("previousTask", send_inputs["message"])
        poll = remote.find(f"{{{B}}}serviceTask[@id='GetA2ATask']")
        poll_inputs = {e.get("target"): e.get("source") for e in poll.findall(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input")}
        self.assertEqual(poll_inputs["taskId"],
                         "=if remoteResponse.result.task instance of context then "
                         "remoteResponse.result.task.id else remoteResponse.result.id")
        self.assertNotIn("fromAi(", poll_inputs["taskId"])

    def test_client_uses_stock_api_key_binding_without_staged_secret_headers(self):
        template = json.loads(self.resources["blueprint/templates/11-client-a2a.json"])
        key = next(p for p in template["properties"] if p.get("id") == "apiKey")
        self.assertEqual(key["binding"], {"type": "zeebe:input", "name": "authentication.value"})
        root = ET.fromstring(self.resources["blueprint/demo/01-client-agent.bpmn"])
        for element_id in ("SendRemoteMessage", "GetA2ATask"):
            task = root.find(f".//{{{B}}}serviceTask[@id='{element_id}']")
            inputs = {e.get("target"): e.get("source") for e in task.findall(
                f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input")}
            self.assertEqual(inputs["authentication.value"], "=camunda.secrets.A2A_API_KEY")
            self.assertEqual(inputs["authentication.apiKeyLocation"], "headers")
            self.assertEqual(inputs["authentication.name"], "X-Api-Key")
            self.assertNotIn("apiKey", inputs)
            self.assertNotIn("Api-Key", inputs["headers"])

    def test_client_remote_polling_and_user_feedback_are_explicit(self):
        root = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        remote = root.find(f".//{{{B}}}subProcess[@id='SendA2AMessage']")
        self.assertEqual(remote.find(
            f"{{{B}}}intermediateCatchEvent[@id='WaitBeforeRemotePoll']/"
            f"{{{B}}}timerEventDefinition/{{{B}}}timeDuration").text, '="PT2S"')
        loop = remote.find(
            f"{{{B}}}sequenceFlow[@id='Flow_RemoteTaskState_RemotePollJoin']")
        condition = loop.find(f"{{{B}}}conditionExpression").text
        self.assertIn('remoteResponse.error = null', condition)
        self.assertIn('"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"', condition)
        self.assertEqual(
            remote.find(f"{{{B}}}exclusiveGateway[@id='RemoteTaskState']").get("default"),
            "Flow_RemoteTaskState_RemoteReplyJoin")
        for join_id, target_id in (("RemotePollJoin", "WaitBeforeRemotePoll"),
                                   ("RemoteReplyJoin", "RemoteReplyReceived")):
            join = remote.find(f"{{{B}}}exclusiveGateway[@id='{join_id}']")
            self.assertIsNotNone(join)
            self.assertEqual(
                {flow.text for flow in join.findall(f"{{{B}}}incoming")},
                {f"Flow_RemoteTaskAccepted_{join_id}", f"Flow_RemoteTaskState_{join_id}"})
            self.assertEqual(
                [flow.text for flow in join.findall(f"{{{B}}}outgoing")],
                [f"Flow_{join_id}_{target_id}"])
            self.assertIsNotNone(remote.find(
                f"{{{B}}}sequenceFlow[@sourceRef='{join_id}'][@targetRef='{target_id}']"))
            target = remote.find(f".//*[@id='{target_id}']")
            self.assertEqual([flow.text for flow in target.findall(f"{{{B}}}incoming")],
                             [f"Flow_{join_id}_{target_id}"])
        self.assertEqual(remote.find(
            f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}output").attrib,
            {"source": "=remoteResponse", "target": "toolCallResult"})
        self.assertNotRegex(ET.tostring(remote).decode(),
                            r"(?i)(pollCount|pollAttempts|pollLimit|maxPolls|CountPoll)")
        self.assertFalse(remote.findall(f"{{{B}}}scriptTask"))
        for source, target in (("QuestionAsked", "DiscoverAgentCard"),
                               ("DiscoverAgentCard", "ClientJoin"),
                               ("ClientJoin", "ClientAgent"),
                               ("ClientAgent", "ReviewClientResult"),
                               ("ReviewClientResult", "ClientSatisfied"),
                               ("ClientSatisfied", "PrepareClientFollowUp"),
                               ("PrepareClientFollowUp", "ClientJoin")):
            self.assertIsNotNone(root.find(
                f".//{{{B}}}sequenceFlow[@sourceRef='{source}'][@targetRef='{target}']"))
        finish = root.find(f".//{{{B}}}sequenceFlow[@id='"
                           "Flow_ClientSatisfied_ClientConversationFinished']")
        self.assertEqual(finish.find(f"{{{B}}}conditionExpression").text,
                         '=clientSatisfied = "yes"')
        feedback = root.find(f".//{{{B}}}scriptTask[@id='PrepareClientFollowUp']/"
                             f"{{{B}}}extensionElements/{{{Z}}}script")
        self.assertEqual(feedback.get("expression"), "=clientFeedback")
        self.assertEqual(feedback.get("resultVariable"), "question")

    def test_protocol_response_and_push_initialization_mappings_remain_executable(self):
        removed = ("BuildValidationError", "BuildTaskList", "BuildNewTaskResponse",
                   "BuildNotFound", "BuildTaskView", "BuildCanceledView",
                   "BuildNotCancelable", "BuildFollowUpResponse", "BuildFollowUpError",
                   "CancellationTimeout", "BuildListFailure", "MarkCorrelated",
                   "MarkNotCorrelated", "IsPushMethod", "ReadPushSetting", "PushSettingKnown")
        response_ends = ("ValidationErrorReady", "TaskListReady", "NewTaskReady",
                         "NotFoundReady", "TaskViewReady", "CanceledReady",
                         "NotCancelableReady", "FollowUpReady", "FollowUpErrorReady",
                         "CancellationErrorReady", "ListFailureReady")
        template = json.loads((ROOT / "blueprint/templates/08-server-a2a-rpc-endpoint.json").read_text())
        expected = next(p["value"] for p in template["properties"] if p.get("id") == "resultExpression")
        for profile in ("basic", "oauth"):
            root = ET.parse(ROOT / f"blueprint/profiles/{profile}/02-a2a-server.bpmn").getroot()
            for element_id in removed:
                self.assertIsNone(root.find(f".//*[@id='{element_id}']"))
            start = root.find(f".//{{{B}}}startEvent[@id='RpcReceived']")
            mapping = start.find(
                f"{{{B}}}extensionElements/{{{Z}}}properties/"
                f"{{{Z}}}property[@name='resultExpression']").get("value")
            self.assertEqual(mapping, expected)
            self.assertIn("pushEnabled: false", mapping)
            self.assertNotIn("request.headers.`x-api-key`", mapping)
            self.assertIsNotNone(root.find(
                f".//{{{B}}}sequenceFlow[@sourceRef='RpcReceived'][@targetRef='ParseRequest']"))
            for end_id in (*response_ends, "Correlated", "NotCorrelated"):
                end = root.find(f".//{{{B}}}endEvent[@id='{end_id}']")
                output = end.find(f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}output")
                self.assertIsNotNone(output, end_id)
                self.assertTrue(output.get("source").startswith("="), end_id)
                self.assertTrue(end.findall(f"{{{B}}}incoming"), end_id)
                if end_id in response_ends:
                    self.assertEqual(output.get("target"), "rpcResponse")
                    self.assertIn('jsonrpc: "2.0"', output.get("source"))
                else:
                    self.assertEqual(output.get("target"), "correlated")
                    self.assertEqual(output.get("source"), "=true" if end_id == "Correlated" else "=false")

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

    def assert_route_avoids_unrelated_nodes(self, root, edge_id):
        plane = root.find(f".//{{{D}}}BPMNPlane")
        flow = root.find(f".//{{{B}}}sequenceFlow[@id='{edge_id}']")
        edge = next(e for e in plane if e.get("bpmnElement") == edge_id)
        points = [(float(p.get("x")), float(p.get("y")))
                  for p in edge.findall(f"{{{DI}}}waypoint")]
        self.assertGreaterEqual(len(points), 2)
        nodes = {e.get("id"): e for e in root.iter() if e.get("id")}
        for shape in plane.findall(f"{{{D}}}BPMNShape"):
            element_id = shape.get("bpmnElement")
            node = nodes[element_id]
            if node.tag in {f"{{{B}}}{tag}" for tag in
                            ("participant", "subProcess", "adHocSubProcess")}:
                continue
            x, y, width, height = (float(shape.find(f"{{{DC}}}Bounds").get(key))
                                   for key in ("x", "y", "width", "height"))
            if element_id in (flow.get("sourceRef"), flow.get("targetRef")):
                point = points[0] if element_id == flow.get("sourceRef") else points[-1]
                self.assertTrue(x <= point[0] <= x + width and y <= point[1] <= y + height,
                                (edge_id, element_id, point))
                continue
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                self.assertTrue(x1 == x2 or y1 == y2, (edge_id, "non-orthogonal route"))
                crosses = (
                    x1 == x2 and x < x1 < x + width
                    and max(min(y1, y2), y) < min(max(y1, y2), y + height)
                ) or (
                    y1 == y2 and y < y1 < y + height
                    and max(min(x1, x2), x) < min(max(x1, x2), x + width)
                )
                self.assertFalse(crosses, (edge_id, element_id))
        return points

    def test_shipping_agent_loops_avoid_host_and_client_nodes(self):
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
        client_agent = next(shape for shape in client_plane
                            if shape.get("bpmnElement") == "ClientAgent")
        client_agent_bounds = client_agent.find(f"{{{DC}}}Bounds")
        shapes = {shape.get("bpmnElement"): shape.find(f"{{{DC}}}Bounds")
                  for shape in client_plane.findall(f"{{{D}}}BPMNShape")}
        for parent_id in ("ClientAgent", "SendA2AMessage"):
            parent = client.find(f".//*[@id='{parent_id}']")
            box = shapes[parent_id]
            x, y, width, height = (float(box.get(key))
                                   for key in ("x", "y", "width", "height"))
            for child in parent:
                if child.get("id") not in shapes:
                    continue
                child_box = shapes[child.get("id")]
                cx, cy, cw, ch = (float(child_box.get(key))
                                   for key in ("x", "y", "width", "height"))
                self.assertGreater(cx, x, child.get("id"))
                self.assertGreater(cy, y, child.get("id"))
                self.assertLess(cx + cw, x + width, child.get("id"))
                self.assertLess(cy + ch, y + height, child.get("id"))
        edges = list(client_plane.findall(f"{{{D}}}BPMNEdge"))
        flows = {e.get("id") for e in client.iter(f"{{{B}}}sequenceFlow")}
        self.assertEqual({e.get("bpmnElement") for e in edges}, flows)
        for edge in edges:
            self.assert_route_avoids_unrelated_nodes(client, edge.get("bpmnElement"))
        feedback = self.assert_route_avoids_unrelated_nodes(
            client, "Flow_PrepareClientFollowUp_ClientJoin")
        self.assertGreater(feedback[0][1],
                           float(client_agent_bounds.get("y")) +
                           float(client_agent_bounds.get("height")))

    def test_protocol_labels_and_aligned_pools_have_meaningful_geometry(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        plane = protocol.find(f".//{{{D}}}BPMNPlane")
        for element_id in ("RpcReceived", "NewTaskReady", "NoSubscription"):
            shape = next(shape for shape in plane if shape.get("bpmnElement") == element_id)
            label = shape.find(f"{{{D}}}BPMNLabel/{{{DC}}}Bounds")
            box = shape.find(f"{{{DC}}}Bounds")
            self.assertIsNotNone(label)
            self.assertGreater(float(label.get("width")), 0)
            self.assertGreater(float(label.get("y")), float(box.get("y")))
        for element_id in ("RouteRequest",):
            shape = next(shape for shape in plane if shape.get("bpmnElement") == element_id)
            bounds = shape.find(f"{{{DC}}}Bounds")
            label = shape.find(f"{{{D}}}BPMNLabel/{{{DC}}}Bounds")
            self.assertIsNotNone(label)
            self.assertLess(float(label.get("y")) + float(label.get("height")),
                            float(bounds.get("y")))
        for profile in ("basic", "oauth"):
            root = ET.parse(ROOT / f"blueprint/profiles/{profile}/02-a2a-server.bpmn").getroot()
            participants = {p.get("id") for p in root.iter(f"{{{B}}}participant")}
            pools = [s.find(f"{{{DC}}}Bounds") for s in root.iter(f"{{{D}}}BPMNShape")
                     if s.get("bpmnElement") in participants]
            self.assertEqual(len(pools), 5)
            bottom = 0
            for box in sorted(pools, key=lambda b: float(b.get("y"))):
                self.assertEqual(float(box.get("x")), 60)
                self.assertGreater(float(box.get("width")), 0)
                self.assertGreater(float(box.get("height")), 0)
                self.assertGreater(float(box.get("y")), bottom)
                bottom = float(box.get("y")) + float(box.get("height"))

    def test_list_scan_retry_and_failure_routes_avoid_nodes(self):
        protocol = ET.parse(ROOT / RESOURCE_PATHS[1]).getroot()
        for edge_id in ("Flow_ListScanDecision_WaitListVariables",
                        "Flow_ListScanDecision_FailListScan"):
            with self.subTest(edge=edge_id):
                self.assert_route_avoids_unrelated_nodes(protocol, edge_id)

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
        client = ET.parse(ROOT / RESOURCE_PATHS[0]).getroot()
        client_host = client.find(f".//{{{B}}}adHocSubProcess[@id='ClientAgent']")
        self.assertEqual(client_host.get(f"{{{Z}}}modelerTemplateIcon"), icon)
        prefix = "data:image/svg+xml;base64,"
        self.assertTrue(icon.startswith(prefix))
        svg = ET.fromstring(base64.b64decode(icon[len(prefix):], validate=True))
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")


if __name__ == "__main__":
    unittest.main()
