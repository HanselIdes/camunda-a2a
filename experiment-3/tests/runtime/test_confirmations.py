import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from confirmations import CLAIM, EXPECTED, FORM_VALUES, data_part, invalid_claims


ROOT = Path(__file__).resolve().parents[2]
Z = "{http://camunda.org/schema/zeebe/1.0}"


class ConfirmationContractTest(unittest.TestCase):
    def test_client_fixture_has_independent_data(self):
        part = data_part()
        part["data"]["syntheticClaim"]["chargeAmounts"][0] = 0
        self.assertEqual(CLAIM["chargeAmounts"], [49.95, 49.95])
        self.assertEqual(len(EXPECTED), 9)

    def test_confirmation_tool_does_not_accept_model_financial_fields(self):
        root = ET.parse(ROOT / "blueprint/demo/03-server-agent-card-dispute.bpmn").getroot()
        tool = next(e for e in root.iter() if e.get("id") == "review_duplicate_charge")
        self.assertNotIn("fromAi(", ET.tostring(tool).decode())
        self.assertEqual([(e.get("source"), e.get("target")) for e in tool.iter(Z + "input")],
                         [("=confirmation", "confirmed")])
        validation = next(e for e in root.iter(Z + "script")
                          if e.get("resultVariable") == "confirmation")
        self.assertIn("req.message.parts", validation.get("expression"))
        self.assertNotIn("agent.", validation.get("expression"))
        self.assertNotIn("history", validation.get("expression"))

    def test_client_agent_history_uses_exact_nested_result_paths(self):
        root = ET.parse(ROOT / "blueprint/demo/01-client-agent.bpmn").getroot()
        discover = next(e for e in root.iter() if e.get("id") == "DiscoverAgentCard")
        card_expression = next(e for e in discover.iter(Z + "header")
                              if e.get("key") == "resultExpression").get("value")
        self.assertEqual(card_expression, "={agentCard: response.body}")

        send = next(e for e in root.iter() if e.get("id") == "SendA2AMessage")
        agent = next(e for e in root.iter() if e.get("id") == "ClientAgent")
        self.assertNotIn(discover, list(agent.iter()))
        send_output = next(e for e in send.iter(Z + "output")
                           if e.get("target") == "toolCallResult").get("source")
        self.assertEqual(send_output, "={response: remoteResponse, task: acceptedTask}")
        previous_task = next(e for e in send.iter(Z + "input")
                             if e.get("target") == "previousTask").get("source")
        self.assertIn('message.results[item.name = "SendA2AMessage"]', previous_task)
        self.assertIn('content[item.type = "object"][1].content', previous_task)
        self.assertIn('get value(content, "toolCallResult")', previous_task)
        self.assertIn("task.id", previous_task)
        self.assertIn("task.contextId", previous_task)
        self.assertNotIn("fromAi(", previous_task)

        confirmed_parts = next(e for e in send.iter(Z + "input")
                               if e.get("target") == "confirmedParts").get("source")
        self.assertIn('message.results[item.name = "AskClientForInput"]', confirmed_parts)
        self.assertIn('content[item.type = "object"][1].content', confirmed_parts)
        self.assertIn('get value(content, "toolCallResult")', confirmed_parts)
        self.assertIn("result.syntheticClaim", confirmed_parts)
        self.assertNotIn("SendA2AMessage", confirmed_parts)

        send_task = next(e for e in send.iter() if e.get("id") == "SendRemoteMessage")
        message = next(e for e in send_task.iter(Z + "input")
                       if e.get("target") == "message").get("source")
        self.assertIn("context merge([", message)
        self.assertIn("remoteText", message)
        self.assertIn("confirmedParts", message)
        self.assertIn("previousTask", message)
        self.assertNotIn("toolCall.claim", message)
        self.assertNotIn("toolCall.taskId", message)
        self.assertNotIn("toolCall.contextId", message)

        get_task = next(e for e in send.iter() if e.get("id") == "GetA2ATask")
        task_id = next(e for e in get_task.iter(Z + "input")
                       if e.get("target") == "taskId").get("source")
        self.assertIn("remoteResponse.result.task", task_id)
        self.assertIn("remoteResponse.result.id", task_id)
        self.assertNotIn("fromAi(", task_id)

        output_sources = {e.get("target"): e.get("source") for e in agent.iter(Z + "output")}
        self.assertEqual(output_sources["clientAgent"], "=agent")
        result_expression = output_sources["resultText"]
        self.assertIn("agent.responseText", result_expression)
        self.assertIn('message.results[item.name = "SendA2AMessage"]', result_expression)
        self.assertIn("task.status.state", result_expression)
        self.assertNotIn("PrepareClientResult", {e.get("id") for e in root.iter()})

    def test_client_result_review_requires_explicit_satisfaction(self):
        form = json.loads((ROOT / "blueprint/demo/06-client-agent-result.form").read_text())
        satisfied = next(component for component in form["components"]
                         if component.get("key") == "clientSatisfied")
        self.assertTrue(satisfied["validate"]["required"])
        self.assertEqual({value["value"] for value in satisfied["values"]}, {"yes", "no"})

    def test_server_card_uses_the_documented_prototype_placeholder(self):
        root = ET.parse(ROOT / "blueprint/profiles/basic/02-a2a-server.bpmn").getroot()
        public_url = next(e for e in root.iter(Z + "property")
                          if e.get("name") == "inbound.publicRpcUrl")
        self.assertEqual(
            public_url.get("value"),
            "https://camunda-a2a-demo.example.com/inbound/a2a",
        )

    def test_form_has_explicit_empty_confirmation_inputs(self):
        form = json.loads((ROOT / "blueprint/demo/05-client-agent-confirm.form").read_text())
        fields = {c.get("key"): c for c in form["components"] if c.get("key")}
        self.assertEqual(set(fields), set(FORM_VALUES) | {"followUp"})
        for key in FORM_VALUES:
            self.assertTrue(fields[key]["validate"]["required"])
            self.assertNotIn("defaultValue", fields[key])
            if fields[key]["type"] == "number":
                self.assertEqual(fields[key]["validate"]["min"], 0)
        root = ET.parse(ROOT / "blueprint/demo/01-client-agent.bpmn").getroot()
        task = next(e for e in root.iter() if e.get("id") == "AskClientForInput")
        inputs = {e.get("target"): e.get("source") for e in task.iter(Z + "input")}
        outputs = {e.get("target"): e.get("source") for e in task.iter(Z + "output")}
        self.assertEqual(set(inputs), {"question"})
        self.assertIn("fromAi(toolCall.question", inputs["question"])
        self.assertEqual(set(outputs), {"toolCallResult"})
        for key in fields:
            self.assertIn(key, outputs["toolCallResult"])
        self.assertIn("followUp", outputs["toolCallResult"])

    def test_regression_matrix_includes_malformed_and_nonfinite_values(self):
        names = {name for name, value in invalid_claims()}
        self.assertTrue({"missing-merchant", "missing-currency", "missing-chargeAmounts",
                         "missing-expectedAmount", "missing-syntheticOnly"} <= names)
        encoded = json.dumps(invalid_claims())
        self.assertIn("Infinity", encoded)
        self.assertIn("NaN", encoded)
