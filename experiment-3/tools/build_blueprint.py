#!/usr/bin/env python3
"""Generate the 8.8-engine candidate demo; never rewrite the archived experiments."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

from build_core import B, Z, ROOT
from gen_card import feel_str, json_string_expression, skills_from_bpmn, skills_feel
from bpmn_gen import build as original
from bpmn_gen.agent import USER_PROMPT
from bpmn_gen.client import client
from bpmn_gen.lib import Proc, q

UPSTREAM = "https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/"
AI = UPSTREAM + "connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json"
HTTP = UPSTREAM + "connectors/http/rest/element-templates/versioned/http-json-connector-12.json"
DEMO = ROOT / "blueprint/demo"
SAMPLE = ("Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. "
          "The expected charge was USD 49.95. Reconcile the two charges with your tool.")
SYSTEM = (
    "You help demonstrate card-dispute intake using synthetic data only. "
    "For each review use review_duplicate_charge; never calculate a result yourself. "
    "You need the merchant, currency, two charge amounts and expected amount. "
    "If any are missing, call no tool and reply NEED_INPUT: followed by a clarification question. "
    "After the tool returns, briefly describe its result. Do not authorize refunds, decide a real dispute, "
    "call external financial services or claim that matching amounts alone prove fraud."
)


def apply(path, template, element, settings):
    command = ["c8ctl", "element-template", "apply", template, element, str(path), "--in-place"]
    for name, value in settings:
        command.extend(["--set", f"{name}={value}"])
    subprocess.run(command, check=True, capture_output=True, text=True)


def serialize(root):
    root.set("{http://camunda.org/schema/modeler/1.0}executionPlatformVersion", "8.8.0")
    for node in root.iter():
        node.attrib.pop(f"{{{Z}}}modelerTemplateIcon", None)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n"


def agent(path):
    p = original.agent_proc()
    p.pid, p.name = "a2a-card-dispute", "Synthetic card-dispute A2A agent"
    for node_id in ("convert_temperature", "list_tech_devices"):
        p.nodes.pop(node_id)
        p.order.remove(node_id)
    for node in p.nodes.values():
        if node.x >= 330:
            node.x += 200
    p.nodes["AgentTools"].name = "Review synthetic card dispute"
    p.script("EncodePrompt", "Preserve literal input", 340, 238,
             json_string_expression(USER_PROMPT), "jsonPrompt")
    p.remove_flow("NextTurn", "AgentTools")
    p.flow("NextTurn", "EncodePrompt")
    p.flow("EncodePrompt", "AgentTools")
    inputs = [
        ("merchant", "Merchant named in the synthetic claim", "string"),
        ("currency", "Currency code supplied by the client", "string"),
        ("firstAmount", "First charge amount", "number"),
        ("secondAmount", "Second charge amount", "number"),
        ("expectedAmount", "Expected amount for the single order", "number"),
    ]
    io = "".join('<zeebe:input source=%s target=%s />' %
                 (q(f"=fromAi(toolCall.{name}, {feel_str(description)}, {feel_str(kind)})"), q(name))
                 for name, description, kind in inputs)
    result = original.one("""={
      merchant: merchant, currency: currency, chargeAmounts: [firstAmount, secondAmount],
      expectedAmount: expectedAmount, paidAmount: decimal(firstAmount + secondAmount, 2),
      overchargeAmount: decimal(max([firstAmount + secondAmount - expectedAmount, 0]), 2),
      matchingAmounts: firstAmount = expectedAmount and secondAmount = expectedAmount,
      recommendation: "REQUEST_HUMAN_REVIEW", syntheticOnly: true}""")
    p.node("scriptTask", "review_duplicate_charge", "Reconcile synthetic charges", 680, 220, parent="AgentTools",
           doc="Reconciles two supplied synthetic charge amounts against one expected order amount. "
               "Returns arithmetic evidence for human review, not a refund authorization or fraud determination.",
           ext=('<zeebe:ioMapping>' + io + '</zeebe:ioMapping>'
                '<zeebe:script expression=%s resultVariable="toolCallResult" />' % q(result)
                + original.tool_ext("synthetic,card-dispute,reconciliation", SAMPLE)))
    outcome = original.one("""(for reply in [agent.responseText] return
      for ask in [reply instance of string and starts with(trim(reply), "NEED_INPUT:")] return
      for records in [flatten(for message in agent.context.conversation.messages[item.role = "tool_call_result"]
                      return message.results[item.name = "review_duplicate_charge"])] return
      for evidence in [if count(records) > 0 then records[count(records)].content else null] return
      {state: if ask then "TASK_STATE_INPUT_REQUIRED" else
              if evidence != null and evidence.syntheticOnly = true then "TASK_STATE_COMPLETED" else "TASK_STATE_FAILED",
       text: if ask then trim(substring(trim(reply), 12)) else if evidence != null and evidence.syntheticOnly = true
             then "Synthetic charges reconciled for human review. No refund or financial action was performed."
             else "The agent did not produce the required reconciliation evidence.",
       artifacts: if ask then [] else if evidence != null and evidence.syntheticOnly = true then
         [{artifactId: uuid(), name: "reconciliation", parts: [{data: evidence}]}] else []})[1][1][1][1]""")
    p.nodes["UpdateTask"].ext = p.nodes["UpdateTask"].ext.replace(q("={agent: agent}"), q("=" + outcome))
    path.write_text(p.xml())
    apply(path, AI, "AgentTools", [
        ("provider.type", "openaiCompatible"),
        ("provider.openaiCompatible.endpoint", "{{secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT}}"),
        ("provider.openaiCompatible.authentication.apiKey", "{{secrets.CAMUNDA_PROVIDED_LLM_API_KEY}}"),
        ("provider.openaiCompatible.model.model", "{{secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL}}"),
        ("provider.openaiCompatible.model.parameters.temperature", "=0"),
        ("data.systemPrompt.prompt", "=" + feel_str(SYSTEM)),
        ("data.userPrompt.prompt", "=jsonPrompt"), ("agentContext", "=agent.context"),
        ("data.memory.storage.type", "in-process"), ("data.memory.contextWindowSize", "=20"),
        ("data.limits.maxModelCalls", "=8"), ("data.response.format.type", "text"),
        ("data.response.includeAgentContext", "true"),
        ("errorExpression", '=if error != null then bpmnError("AGENT_FAILED", string(error.message)) else null'),
        ("retries", "1"),
    ])
    return serialize(ET.parse(path).getroot())


def card(path, agent_path):
    p = original.card_proc()
    path.write_text(p.xml())
    skills = skills_feel(skills_from_bpmn(agent_path))
    response = original.one("""={statusCode: 200, headers: {"Content-Type": "application/json"},
      body: {name: "Synthetic card-dispute reviewer", version: "0.1.0",
        description: "Non-production community demonstration. Reconciles synthetic charges for human review; "
                     + "performs no financial actions.",
        provider: {organization: "HanselIdes", url: "https://github.com/HanselIdes/camunda-a2a"},
        supportedInterfaces: [{url: "{{secrets.A2A_RPC_URL}}", protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
        capabilities: {streaming: false, pushNotifications: false, extendedAgentCard: false},
        defaultInputModes: ["text/plain"], defaultOutputModes: ["text/plain", "application/json"],
        securitySchemes: {a2aApiKey: {apiKeySecurityScheme: {location: "header", name: "X-A2A-Api-Key"}}},
        securityRequirements: [{schemes: {a2aApiKey: {}}}],
        skills: %s}}""" % skills)
    root = ET.parse(path).getroot()
    start = next(e for e in root.iter() if e.get("id") == "CardRequested")
    start.set(f"{{{Z}}}modelerTemplate", "dev.hansel.a2a.core.card.v1")
    start.set(f"{{{Z}}}modelerTemplateVersion", "1")
    extension = ET.SubElement(start, f"{{{B}}}extensionElements")
    start.remove(extension)
    start.insert(0, extension)
    properties = ET.SubElement(extension, f"{{{Z}}}properties")
    for name, value in {
        "inbound.type": "io.camunda:webhook:1", "inbound.context": "a2a-card",
        "inbound.auth.type": "NONE", "inbound.method": "get",
        "inbound.responseExpression": response,
    }.items():
        ET.SubElement(properties, f"{{{Z}}}property", {"name": name, "value": value})
    return serialize(root)


def assets():
    output = {}
    with tempfile.TemporaryDirectory(prefix="a2a-blueprint-") as directory:
        directory = Path(directory)
        agent_path = directory / "a2a-card-dispute.bpmn"
        output[DEMO / agent_path.name] = agent(agent_path)
        agent_path.write_bytes(output[DEMO / agent_path.name])
        output[DEMO / "a2a-card.bpmn"] = card(directory / "a2a-card.bpmn", agent_path)
        templates = ROOT / "blueprint/templates"
        for template, filename in ((HTTP, "http-json.json"),):
            fetched = subprocess.run(["c8ctl", "element-template", "get", template, "--no-icon"],
                                     check=True, capture_output=True, text=True)
            data = json.loads(fetched.stdout)
            assert data["id"] == "io.camunda.connectors.HttpJson.v2" and data["version"] == 12
            output[templates / filename] = (json.dumps(data, indent=2) + "\n").encode()
        for kind in ("rpc", "card"):
            data = json.loads((ROOT / f"element-templates/a2a-1.0-server-{kind}.json").read_text())
            data.pop("icon", None)
            data.update(id=f"dev.hansel.a2a.core.{kind}.v1", version=1)
            data["engines"]["camunda"] = "^8.8"
            data["description"] = ("Direct stock-Connectors A2A 1.0 endpoint for a non-production blueprint. "
                                   "Requires stock Connectors 8.9 or later with Camunda engine 8.8 or later; "
                                   "only combinations documented in the setup guide are verified.")
            if kind == "rpc":
                next(p for p in data["properties"] if p.get("id") == "inbound.auth.type")["value"] = "APIKEY"
                for name, value in {
                    "inbound.auth.apiKey": "{{secrets.A2A_API_KEY}}",
                    "inbound.auth.apiKeyLocator": '=request.headers.`x-a2a-api-key`',
                }.items():
                    data["properties"].append({"type": "Hidden", "id": name, "value": value,
                                               "binding": {"type": "zeebe:property", "name": name}})
            else:
                root = ET.fromstring(output[DEMO / "a2a-card.bpmn"])
                response = next(p.get("value") for p in root.iter(f"{{{Z}}}property")
                                if p.get("name") == "inbound.responseExpression")
                field = next(p for p in data["properties"] if p.get("id") == "inbound.responseExpression")
                field["value"] = response
                field["description"] = ("Describe the selected BPMN process truthfully. Keep the complete "
                                        "A2A_RPC_URL secret, API-key security scheme and disabled capabilities.")
            output[templates / f"a2a-core-{kind}.json"] = (json.dumps(data, indent=2) + "\n").encode()
        writes, applications = {}, []
        client(str(directory), lambda path, text: writes.__setitem__(path, text),
               lambda path, template, element, settings: applications.append((path, element, settings)), original.one)
        for path, text in writes.items():
            target = directory / Path(path).name
            if path.endswith(".form"):
                data = json.loads(text)
                if data["id"] == "a2a-client-ask":
                    data["components"][0]["text"] = "### Review a synthetic card dispute\n\n" + \
                        "A BPMN client calls the remote AI agent through authenticated A2A 1.0. No real financial actions."
                    data["components"][1]["defaultValue"] = SAMPLE
                output[DEMO / target.name] = (json.dumps(data, indent=2) + "\n").encode()
            else:
                target.write_text(text)
        for path, element, settings in applications:
            settings = [(name, "{{secrets.A2A_RPC_URL}}" if name == "url" and element != "DiscoverAgent" else value)
                        for name, value in settings]
            if element != "DiscoverAgent":
                settings = [(name, value[:-1] + ', "X-A2A-Api-Key": "{{secrets.A2A_API_KEY}}"}'
                             if name == "headers" else value) for name, value in settings]
            apply(directory / Path(path).name, HTTP, element, settings)
        client_path = directory / "a2a-client.bpmn"
        client_root = ET.parse(client_path).getroot()
        for script in client_root.iter(f"{{{Z}}}script"):
            if script.get("resultVariable") == "reply":
                script.set("expression", script.get("expression").replace(
                    "toolNames:", 'reconciliation: if t != null and t.artifacts instance of list then '
                    '(for a in t.artifacts[item.name = "reconciliation"] return a.parts[1].data)[1] else null, toolNames:'))
            elif script.get("resultVariable") == "resultText":
                script.set("expression", script.get("expression") + original.one(
                    """ + (if reply.reconciliation != null then
                       "\\n\\n**Synthetic reconciliation**\\n\\nMerchant: " + reply.reconciliation.merchant
                       + "\\n\\nPaid: " + string(reply.reconciliation.paidAmount) + " " + reply.reconciliation.currency
                       + "\\n\\nExpected: " + string(reply.reconciliation.expectedAmount) + " " + reply.reconciliation.currency
                       + "\\n\\nOvercharge: " + string(reply.reconciliation.overchargeAmount) + " " + reply.reconciliation.currency
                       + "\\n\\nNext step: " + reply.reconciliation.recommendation else "")"""))
        output[DEMO / client_path.name] = serialize(client_root)
        literal = Proc("a2a-literal-prompt", "Literal prompt regression fixture")
        literal.start("LiteralStart", "Input received", 150, 62)
        literal.script("LiteralEncode", "Encode input", 230, 40, json_string_expression("=text"), "encoded")
        literal.end("LiteralEnd", "Input encoded", 390, 62)
        literal.flow("LiteralStart", "LiteralEncode")
        literal.flow("LiteralEncode", "LiteralEnd")
        output[ROOT / "tests/src/test/resources/bpmn/a2a-literal-prompt.bpmn"] = serialize(ET.fromstring(literal.xml()))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = assets()
    for path, content in generated.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                parser.exit(1, f"Regenerate stale candidate asset: {path.relative_to(ROOT)}\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print("Candidate demo assets match" if args.check else "Generated candidate demo assets")
