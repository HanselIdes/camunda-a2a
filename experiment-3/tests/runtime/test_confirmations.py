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
        root = ET.parse(ROOT / "blueprint/demo/02-server-agent-card-dispute.bpmn").getroot()
        tool = next(e for e in root.iter() if e.get("id") == "review_duplicate_charge")
        self.assertNotIn("fromAi(", ET.tostring(tool).decode())
        self.assertEqual([(e.get("source"), e.get("target")) for e in tool.iter(Z + "input")],
                         [("=confirmation", "confirmed")])
        validation = next(e for e in root.iter(Z + "script")
                          if e.get("resultVariable") == "confirmation")
        self.assertIn("req.message.parts", validation.get("expression"))
        self.assertNotIn("agent.", validation.get("expression"))
        self.assertNotIn("history", validation.get("expression"))

    def test_form_has_explicit_empty_confirmation_inputs(self):
        form = json.loads((ROOT / "blueprint/demo/05-client-agent-confirm.form").read_text())
        fields = {c.get("key"): c for c in form["components"] if c.get("key")}
        self.assertEqual(set(fields), set(FORM_VALUES) | {"followUp"})
        for key in FORM_VALUES:
            self.assertTrue(fields[key]["validate"]["required"])
            self.assertNotIn("defaultValue", fields[key])
            if fields[key]["type"] == "number":
                self.assertEqual(fields[key]["validate"]["min"], 0)
        root = ET.parse(ROOT / "blueprint/demo/03-client-agent.bpmn").getroot()
        task = next(e for e in root.iter() if e.get("id") == "AnswerAgent")
        inputs = {e.get("target"): e.get("source") for e in task.iter(Z + "input")}
        self.assertEqual(inputs, {key: "=null" for key in fields})

    def test_regression_matrix_includes_malformed_and_nonfinite_values(self):
        names = {name for name, value in invalid_claims()}
        self.assertTrue({"missing-merchant", "missing-currency", "missing-chargeAmounts",
                         "missing-expectedAmount", "missing-syntheticOnly"} <= names)
        encoded = json.dumps(invalid_claims())
        self.assertIn("Infinity", encoded)
        self.assertIn("NaN", encoded)
