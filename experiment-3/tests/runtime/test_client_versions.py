"""Version headers on the current client, not the retired standalone verifier."""
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z = "http://camunda.org/schema/zeebe/1.0"


class ClientVersionContractTest(unittest.TestCase):
    def test_all_current_operations_send_the_advertised_version(self):
        root = ET.parse(ROOT / "blueprint/demo/01-client-agent.bpmn").getroot()
        for element_id in ("DiscoverAgentCard", "SendRemoteMessage", "GetA2ATask"):
            task = root.find(f".//{{{B}}}serviceTask[@id='{element_id}']")
            headers = task.find(
                f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}input[@target='headers']")
            self.assertIn('"A2A-Version": "1.0"', headers.get("source"), element_id)
        template = json.loads((ROOT / "blueprint/templates/11-client-a2a.json").read_text())
        headers = next(p["value"] for p in template["properties"] if p.get("id") == "headers")
        self.assertEqual(headers.count('"A2A-Version": "1.0"'), 2)

    def test_discovery_exposes_the_card_instead_of_inventing_a_rpc_url(self):
        root = ET.parse(ROOT / "blueprint/demo/01-client-agent.bpmn").getroot()
        task = root.find(f".//{{{B}}}serviceTask[@id='DiscoverAgentCard']")
        headers = {h.get("key"): h.get("value") for h in task.findall(
            f"{{{B}}}extensionElements/{{{Z}}}taskHeaders/{{{Z}}}header")}
        self.assertEqual(headers["resultExpression"], "={agentCard: response.body}")
