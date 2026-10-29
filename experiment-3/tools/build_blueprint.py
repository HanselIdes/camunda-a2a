#!/usr/bin/env python3
"""Generate the candidate demo; never rewrite the archived experiments."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import build_core
from build_core import B, Z, ROOT, REQUEST_MAPPING
from layout_bpmn import layout_xml
from gen_card import feel_str, json_string_expression, skills_from_bpmn, skills_feel
from bpmn_gen import build as original
from bpmn_gen.agent_client import CLIENT_RESULT_EXPRESSION, build as build_client_agent
from bpmn_gen.a2a_client_template import build as build_client_template
from bpmn_gen.cancellation import add_hook
from bpmn_gen.lib import Proc, q
from bpmn_gen.secrets import current_secret_expression, current_secret_mappings

CARD_RPC_URL_PROPERTY = "inbound.publicRpcUrl"
CARD_RPC_URL_PATTERN = "^https://[^ /]+/[^ ]*$"
DEMO_PUBLIC_RPC_URL = "https://camunda-a2a-demo.example.com/inbound/a2a"
RPC_REQUEST_MAPPING = REQUEST_MAPPING[:-1] + ", pushEnabled: false}"


def initialize_rpc_request(root):
    process = root.find(f"{{{B}}}process[@id='a2a-rpc']")
    start = process.find(f"{{{B}}}startEvent[@id='RpcReceived']")
    mapping = start.find(
        f"{{{B}}}extensionElements/{{{Z}}}properties/"
        f"{{{Z}}}property[@name='resultExpression']")
    mapping.set("value", RPC_REQUEST_MAPPING)
    outgoing = start.find(f"{{{B}}}outgoing")
    entry = process.find(f"{{{B}}}sequenceFlow[@id='{outgoing.text}']")
    old_entry_id = entry.get("id")
    entry.set("id", "Flow_RpcReceived_ParseRequest")
    outgoing.text = entry.get("id")
    entry.set("targetRef", "ParseRequest")
    parse = process.find(f"{{{B}}}scriptTask[@id='ParseRequest']")
    parse.find(f"{{{B}}}incoming").text = entry.get("id")
    removed = {"IsPushMethod", "ReadPushSetting", "PushSettingKnown"}
    for element in list(process):
        if element.get("id") in removed:
            process.remove(element)
        elif element.tag == f"{{{B}}}sequenceFlow" and element.get("sourceRef") in removed:
            removed.add(element.get("id"))
            process.remove(element)
    for plane in root.iter("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNPlane"):
        for element in list(plane):
            if element.get("bpmnElement") in removed:
                plane.remove(element)
            elif element.get("bpmnElement") == old_entry_id:
                element.set("bpmnElement", entry.get("id"))
                element.set("id", entry.get("id") + "_di")
    return root


def compact_server_responses(root):
    task_ids = (
        "BuildValidationError", "BuildTaskList", "BuildNewTaskResponse",
        "BuildNotFound", "BuildTaskView", "BuildCanceledView",
        "BuildNotCancelable", "BuildFollowUpResponse", "BuildFollowUpError",
        "CancellationTimeout", "BuildListFailure",
        "MarkCorrelated", "MarkNotCorrelated",
    )
    removed = set()
    for task_id in task_ids:
        process = next(p for p in root.findall(f"{{{B}}}process")
                       if p.find(f"{{{B}}}scriptTask[@id='{task_id}']") is not None)
        task = process.find(f"{{{B}}}scriptTask[@id='{task_id}']")
        outgoing = task.findall(f"{{{B}}}outgoing")
        if len(outgoing) != 1:
            raise ValueError(f"{task_id} must have exactly one outgoing flow")
        flow = process.find(f"{{{B}}}sequenceFlow[@id='{outgoing[0].text}']")
        end = process.find(f"{{{B}}}endEvent[@id='{flow.get('targetRef')}']")
        if end is None or len(end.findall(f"{{{B}}}incoming")) != 1:
            raise ValueError(f"{task_id} must lead directly to its own end event")
        script = task.find(f"{{{B}}}extensionElements/{{{Z}}}script")
        if script is None or end.find(f"{{{B}}}extensionElements") is not None:
            raise ValueError(f"{task_id} has unexpected execution configuration")
        extension = ET.Element(f"{{{B}}}extensionElements")
        mapping = ET.SubElement(extension, f"{{{Z}}}ioMapping")
        ET.SubElement(mapping, f"{{{Z}}}output",
                      source=script.get("expression"), target=script.get("resultVariable"))
        end.insert(0, extension)
        end.remove(end.find(f"{{{B}}}incoming"))
        for incoming in task.findall(f"{{{B}}}incoming"):
            process.find(f"{{{B}}}sequenceFlow[@id='{incoming.text}']").set("targetRef", end.get("id"))
            ET.SubElement(end, f"{{{B}}}incoming").text = incoming.text
        process.remove(task)
        process.remove(flow)
        removed.update((task_id, flow.get("id")))
    for plane in root.iter("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNPlane"):
        for element in list(plane):
            if element.get("bpmnElement") in removed:
                plane.remove(element)
    return root


def configure_card(root):
    for node in root.iter():
        for key, value in node.attrib.items():
            node.set(key, value.replace("X-A2A-Api-Key", "X-Api-Key")
                     .replace("x-a2a-api-key", "x-api-key"))
        if node.get(f"{{{Z}}}modelerTemplate", "").startswith("dev.hansel.a2a.core."):
            node.set(f"{{{Z}}}modelerTemplateVersion", "3")
    start = root.find(f".//{{{B}}}startEvent[@id='CardRequested']")
    documentation = start.find(f"{{{B}}}documentation")
    if documentation is None:
        documentation = ET.Element(f"{{{B}}}documentation")
        start.insert(0, documentation)
    documentation.text = (
        "The camunda-a2a-demo.example.com public RPC URL is a nonfunctional example. "
        "Replace it with the deployed HTTPS A2A RPC webhook URL before use; "
        "it must match the client's A2A_RPC_URL secret."
    )
    properties = start.find(f"{{{B}}}extensionElements/{{{Z}}}properties")
    ET.SubElement(properties, f"{{{Z}}}property", name=CARD_RPC_URL_PROPERTY, value=DEMO_PUBLIC_RPC_URL)
    response = properties.find(f"{{{Z}}}property[@name='inbound.responseExpression']")
    card = response.get("value").replace("camunda.secrets.A2A_RPC_URL", "rpcUrl")
    response.set("value", (
        '={rpcUrl: get value(correlation.activatedElement.delegate.properties, '
        f'"{CARD_RPC_URL_PROPERTY}"), response: if rpcUrl instance of string '
        f'and matches(rpcUrl, "{CARD_RPC_URL_PATTERN}") then {card[1:]} '
        'else {statusCode: 500, body: {error: "Configure the Agent Card HTTPS public RPC URL"}}}.response'
    ))
    return root

UPSTREAM = "https://raw.githubusercontent.com/camunda/connectors/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/"
AI = UPSTREAM + "connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json"
AI_CLIENT = ("https://raw.githubusercontent.com/camunda/connectors/"
             "b490d065b59ffe4788319609dbe41deb25e68e3f/connectors/agentic-ai/"
             "connector-agentic-ai/element-templates/agenticai-ai-agent-subprocess.v2.json")
HTTP = ("https://raw.githubusercontent.com/camunda/connectors/"
        "b490d065b59ffe4788319609dbe41deb25e68e3f/"
        "connectors/http/rest/element-templates/versioned/http-json-connector-13.json")
DEMO = ROOT / "blueprint/demo"
SAMPLE = ("Synthetic example only: Northwind Electronics charged USD 49.95 twice for one order. "
          "The expected charge was USD 49.95. Reconcile the two charges with your tool.")
SYSTEM = (
    "You help demonstrate card-dispute intake using synthetic data only. "
    "For each review call review_duplicate_charge; never calculate or supply financial fields yourself. "
    "The tool uses only the current request's explicit client confirmation, not values inferred from text. "
    "If the tool requests confirmation, reply NEED_INPUT: followed by its clarification instructions. "
    "After the tool returns, briefly describe its result. Do not authorize refunds, decide a real dispute, "
    "call external financial services or claim that matching amounts alone prove fraud."
)
CONFIRMATION_QUESTION = (
    "Confirm synthetic data only: supply one message data part with syntheticClaim containing "
    "merchant and currency (nonempty text), chargeAmounts (exactly two finite nonnegative numbers), "
    "expectedAmount (a finite nonnegative number), and syntheticOnly=true. "
    "Free text alone is context, not confirmation."
)
CONFIRMATION = original.one("""={
  parts: if req.message.parts instance of list then
    req.message.parts[item instance of context and item.data != null] else [],
  claim: if count(parts) = 1 then
    if parts[1].data instance of context then parts[1].data.syntheticClaim else null else null,
  validAmount: function(amount) if amount instance of number then
    amount >= 0 and amount - amount = 0 else false,
  valid: if claim instance of context then
    if claim.merchant instance of string and claim.currency instance of string then
      if string length(trim(claim.merchant)) > 0 and string length(trim(claim.currency)) > 0
         and claim.syntheticOnly = true then
        if claim.chargeAmounts instance of list then
          count(claim.chargeAmounts) = 2 and
          (every amount in claim.chargeAmounts satisfies validAmount(amount)) and
          validAmount(claim.expectedAmount)
        else false
      else false
    else false
  else false,
  result: {valid: valid = true, claim: if valid = true then
    {merchant: claim.merchant, currency: claim.currency, chargeAmounts: claim.chargeAmounts,
     expectedAmount: claim.expectedAmount, syntheticOnly: true} else null}
}.result""")
RECONCILIATION = original.one("""={
  merchant: confirmed.claim.merchant, currency: confirmed.claim.currency,
  chargeAmounts: confirmed.claim.chargeAmounts, expectedAmount: confirmed.claim.expectedAmount,
  paidAmount: decimal(sum(confirmed.claim.chargeAmounts), 2),
  overchargeAmount: decimal(max([sum(confirmed.claim.chargeAmounts) - confirmed.claim.expectedAmount, 0]), 2),
  matchingAmounts: every amount in confirmed.claim.chargeAmounts satisfies amount = confirmed.claim.expectedAmount,
  recommendation: "REQUEST_HUMAN_REVIEW", syntheticOnly: true}""")
CONFIRMATION_FIELDS = (
    ("claimMerchant", "Merchant", "textfield"),
    ("claimCurrency", "Currency", "textfield"),
    ("claimFirstAmount", "First charge amount", "number"),
    ("claimSecondAmount", "Second charge amount", "number"),
    ("claimExpectedAmount", "Expected order amount", "number"),
    ("claimSyntheticOnly", "I confirm these are synthetic demonstration values", "checkbox"),
)


def apply(path, template, element, settings):
    command = ["c8ctl", "element-template", "apply", template, element, str(path), "--in-place"]
    for name, value in settings:
        command.extend(["--set", f"{name}={value}"])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Failed to apply {template} to {element}: {result.stderr.strip()}")


def serialize(root, version="8.9.0"):
    root.set("{http://camunda.org/schema/modeler/1.0}executionPlatformVersion", version)
    for node in root.iter():
        if node.get(f"{{{Z}}}modelerTemplate") not in (
                "io.camunda.connectors.agenticai.aiagent.jobworker.v1",
                "io.camunda.connectors.agenticai.ai-agent-subprocess.v2",
                "dev.hansel.a2a.client.v1"):
            node.attrib.pop(f"{{{Z}}}modelerTemplateIcon", None)
    ET.indent(root, space="  ")
    return layout_xml(ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n")


def agent(path):
    p = original.agent_proc()
    p.pid, p.name = "a2a-card-dispute", "03 Server Agent - Synthetic Card Dispute"
    for node_id in ("convert_temperature", "list_tech_devices"):
        p.nodes.pop(node_id)
        p.order.remove(node_id)
    for node in p.nodes.values():
        if node.x >= 330:
            node.x += 200
    p.nodes["AgentTools"].name = "Review synthetic card dispute"
    prompt = ('=if count(req.message.parts[item.text instance of string]) = 0 then '
              '"Review the explicit client confirmation." else '
              'string join(req.message.parts[item.text instance of string].text, " ")')
    p.script("EncodePrompt", "Join client input", 340, 238, prompt, "promptText")
    p.script("ValidateConfirmation", "Validate client confirmation", 340, 340, CONFIRMATION, "confirmation")
    p.remove_flow("NextTurn", "AgentTools")
    p.flow("NextTurn", "EncodePrompt")
    p.flow("EncodePrompt", "ValidateConfirmation")
    p.flow("ValidateConfirmation", "AgentTools")
    io = '<zeebe:input source="=confirmation" target="confirmed" />'
    result = ("=if confirmed.valid = true then " + RECONCILIATION[1:]
              + " else {confirmationRequired: true, instruction: " + feel_str(CONFIRMATION_QUESTION) + "}")
    p.node("scriptTask", "review_duplicate_charge", "Reconcile synthetic charges", 680, 220, parent="AgentTools",
           doc="Call for every review. Checks explicit client confirmation; without it returns confirmation instructions. "
               "Reconciles only validated client-supplied synthetic amounts; accepts no model financial parameters. "
               "Returns arithmetic evidence for human review, not a refund authorization or fraud determination.",
           ext=('<zeebe:ioMapping>' + io + '</zeebe:ioMapping>'
                '<zeebe:script expression=%s resultVariable="toolCallResult" />' % q(result)
                + original.tool_ext("synthetic,card-dispute,reconciliation", SAMPLE)))
    outcome = original.one("""(for reply in [agent.responseText] return
      for ask in [reply instance of string and starts with(trim(reply), "NEED_INPUT:")] return
      for records in [flatten(for message in agent.context.conversation.messages[item.role = "tool_call_result"]
                      return message.results[item.name = "review_duplicate_charge"])] return
      for content in [if count(records) > 0 then records[count(records)].content else null] return
      for evidence in [if content instance of list
                       then content[item.type = "object"][1].content else content] return
      for expected in [if confirmation.valid = true then EXPECTED else null] return
      for grounded in [expected != null and evidence = expected] return
      {state: if confirmation.valid != true or ask then "TASK_STATE_INPUT_REQUIRED" else
              if grounded then "TASK_STATE_COMPLETED" else "TASK_STATE_FAILED",
       text: if confirmation.valid != true then QUESTION else
             if ask then trim(substring(trim(reply), 12)) else if grounded
             then "Synthetic charges reconciled for human review. No refund or financial action was performed."
             else "The agent did not produce the required reconciliation evidence.",
       artifacts: if confirmation.valid != true or ask then [] else if grounded then
         [{artifactId: uuid(), name: "reconciliation", parts: [{data: evidence}]}] else []})[1][1][1][1][1][1][1]""")
    outcome = outcome.replace("EXPECTED", RECONCILIATION[1:].replace("confirmed.", "confirmation."))
    outcome = outcome.replace("QUESTION", feel_str(CONFIRMATION_QUESTION))
    p.nodes["UpdateTask"].ext = p.nodes["UpdateTask"].ext.replace(q("={agent: agent}"), q("=" + outcome))
    path.write_text(p.xml())
    apply(path, AI, "AgentTools", [
        ("provider.type", "openaiCompatible"),
        ("provider.openaiCompatible.endpoint", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_API_ENDPOINT"),
        ("provider.openaiCompatible.authentication.apiKey", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_API_KEY"),
        ("provider.openaiCompatible.model.model", "=camunda.secrets.CAMUNDA_PROVIDED_LLM_DEFAULT_MODEL"),
        ("provider.openaiCompatible.model.parameters.temperature", "=0"),
        ("data.systemPrompt.prompt", "=" + feel_str(SYSTEM)),
        ("data.userPrompt.prompt", "=promptText"), ("agentContext", "=agent.context"),
        ("data.memory.storage.type", "in-process"), ("data.memory.contextWindowSize", "=20"),
        ("data.limits.maxModelCalls", "=8"), ("data.response.format.type", "text"),
        ("data.response.includeAgentContext", "true"),
        ("errorExpression", '=if error != null then bpmnError("AGENT_FAILED", string(error.message)) else null'),
        ("retries", "1"),
    ])
    return serialize(add_hook(ET.parse(path).getroot()), "8.10.0")


def assets():
    output = {}
    # Keep the authored business diagrams/layout; regenerate only their required cancellation hook.
    for path in (ROOT / "bpmn/a2a-echo.bpmn", ROOT / "tck/fixture/a2a-tck-fixture.bpmn"):
        output[path] = serialize(add_hook(ET.parse(path).getroot()))
    with tempfile.TemporaryDirectory(prefix="a2a-blueprint-") as directory:
        directory = Path(directory)
        agent_path = directory / "03-server-agent-card-dispute.bpmn"
        agent_content = agent(agent_path)
        output[DEMO / agent_path.name] = agent_content
        controlled_agent = ET.fromstring(agent_content)
        controlled_agent.find(f"{{{B}}}process").set("id", "a2a-controlled-agent")
        controlled_agent.find(
            "{http://www.omg.org/spec/BPMN/20100524/DI}BPMNDiagram/"
            "{http://www.omg.org/spec/BPMN/20100524/DI}BPMNPlane").set("bpmnElement", "a2a-controlled-agent")
        for field in controlled_agent.iter(f"{{{Z}}}input"):
            if field.get("target", "").startswith("provider."):
                field.set("source", "nonshipping-mocked-provider")
        output[ROOT / "tests/src/test/resources/bpmn/a2a-controlled-agent.bpmn"] = serialize(controlled_agent, "8.10.0")
        for authentication in ("basic", "oauth"):
            profile = configure_card(current_secret_mappings(
                ET.fromstring(build_core.build(authentication, agent_path))))
            output[ROOT / "blueprint/profiles" / authentication / "02-a2a-server.bpmn"] = serialize(
                compact_server_responses(initialize_rpc_request(profile)), "8.10.0")
        decision = ET.parse(ROOT / "dmn/a2a-validate.dmn").getroot()
        decision.set("name", "07 Server - Validate A2A Request")
        for element in decision.iter():
            if element.tag.endswith("}decision") and element.get("id") == "a2a-validate":
                element.set("name", "07 Server - Validate A2A Request")
        output[DEMO / "07-server-request-validation.dmn"] = (
            ET.tostring(decision, encoding="UTF-8", xml_declaration=True) + b"\n")
        templates = ROOT / "blueprint/templates"
        for template, filename in ((HTTP, "10-server-http-json-v13.json"),):
            fetched = subprocess.run(["c8ctl", "element-template", "get", template, "--no-icon"],
                                     check=True, capture_output=True, text=True)
            data = json.loads(fetched.stdout)
            assert data["id"] == "io.camunda.connectors.HttpJson.v2" and data["version"] == 13
            output[templates / filename] = (json.dumps(data, indent=2) + "\n").encode()
        for kind in ("rpc", "card"):
            data = json.loads((ROOT / f"element-templates/a2a-1.0-server-{kind}.json").read_text())
            data.pop("icon", None)
            data["name"] = ("Server - A2A RPC Endpoint" if kind == "rpc"
                            else "Server - Agent Card Endpoint")
            data.update(id=f"dev.hansel.a2a.core.{kind}.v1", version=3)
            data["engines"]["camunda"] = "^8.9"
            data["description"] = ("Direct stock-Connectors A2A 1.0 endpoint for a non-production blueprint. "
                                   "Targets engine and stock Connectors 8.9+; runtime verification pending for 8.9. "
                                   "The complete AI-agent demo still requires 8.10+. "
                                   "Only combinations documented in the setup guide are verified.")
            if kind == "rpc":
                next(p for p in data["properties"] if p.get("id") == "inbound.auth.type")["value"] = "APIKEY"
                mapping = next(p for p in data["properties"] if p.get("id") == "resultExpression")
                mapping["value"] = RPC_REQUEST_MAPPING
                mapping["description"] = ("Persist the JSON-RPC body and only content-type/a2a-version headers. "
                                          "Never persist authorization, API keys or arbitrary request headers.")
                for name, value in {
                    "inbound.auth.apiKeyLocator": '=request.headers.`x-api-key`',
                }.items():
                    data["properties"].append({"type": "Hidden", "id": name, "value": value,
                                               "binding": {"type": "zeebe:property", "name": name}})
                data["properties"].append({
                    "type": "String", "id": "inbound.auth.apiKey", "label": "Shared API key",
                    "group": "endpoint", "value": "{{secrets.A2A_API_KEY}}", "feel": "optional",
                    "constraints": {"notEmpty": True},
                    "description": ("8.9: {{secrets.A2A_API_KEY}} from the Connector secret store. "
                                    "8.10+: =camunda.secrets.A2A_API_KEY from the cluster secret store. "
                                    "Never enter a credential value in the diagram."),
                    "binding": {"type": "zeebe:property", "name": "inbound.auth.apiKey"},
                })
            else:
                root = ET.fromstring(output[ROOT / "blueprint/profiles/basic/02-a2a-server.bpmn"])
                card_start = root.find(f".//{{{B}}}startEvent[@id='CardRequested']")
                response = card_start.find(
                    f"{{{B}}}extensionElements/{{{Z}}}properties/"
                    f"{{{Z}}}property[@name='inbound.responseExpression']").get("value")
                field = next(p for p in data["properties"] if p.get("id") == "inbound.responseExpression")
                field["value"] = response
                field["description"] = ("Describe the selected BPMN process truthfully. Keep the complete "
                                        "public RPC URL field, API-key security scheme and disabled capabilities.")
                data["properties"].insert(data["properties"].index(field), {
                    "id": CARD_RPC_URL_PROPERTY,
                    "type": "String", "label": "Public RPC URL", "group": "card", "value": "",
                    "description": ("Required complete HTTPS A2A RPC webhook URL, including any cluster prefix. "
                                    "Must exactly match the client's A2A_RPC_URL secret. This URL is public, "
                                    "not a credential; webhook response expressions use local FEEL."),
                    "constraints": {"notEmpty": True, "pattern": {
                        "value": CARD_RPC_URL_PATTERN,
                        "message": "Enter the complete HTTPS public RPC URL, including the webhook path",
                    }},
                    "binding": {"type": "zeebe:property", "name": CARD_RPC_URL_PROPERTY},
                })
            filename = ("08-server-a2a-rpc-endpoint.json" if kind == "rpc"
                        else "09-server-agent-card-endpoint.json")
            for prop in data["properties"]:
                if "value" in prop and prop.get("id") != "inbound.auth.apiKey":
                    prop["value"] = current_secret_expression(prop["value"])
            output[templates / filename] = (json.dumps(data, indent=2) + "\n").encode()
        client_xml, client_forms, client_http, client_ai_settings = build_client_agent()
        client_template = directory / "a2a-client.json"
        template_content = (json.dumps(build_client_template(ROOT), indent=2) + "\n").encode()
        client_template.write_bytes(template_content)
        output[templates / "11-client-a2a.json"] = template_content
        client_path = directory / "01-client-agent.bpmn"
        client_path.write_text(client_xml)
        apply(client_path, AI_CLIENT, "ClientAgent", client_ai_settings)
        client_root = ET.parse(client_path).getroot()
        client_host = client_root.find(f".//{{{B}}}adHocSubProcess[@id='ClientAgent']")
        response = client_host.find(f"{{{B}}}extensionElements/{{{Z}}}ioMapping/{{{Z}}}output")
        if response is None or response.get("source") != "=agent":
            raise ValueError("Client Sub-process template changed its response output contract")
        response.set("target", "clientAgent")
        ET.SubElement(client_host.find(f"{{{B}}}extensionElements/{{{Z}}}ioMapping"),
                      f"{{{Z}}}output", source=CLIENT_RESULT_EXPRESSION, target="resultText")
        client_path.write_bytes(ET.tostring(client_root, encoding="UTF-8", xml_declaration=True))
        for element, settings in client_http.items():
            apply(client_path, str(client_template), element, settings)
        for filename, text in client_forms.items():
            output[DEMO / filename] = text.encode()
        output[DEMO / "01-client-agent.bpmn"] = serialize(ET.parse(client_path).getroot(), "8.10.0")
        literal = Proc("a2a-literal-prompt", "Literal prompt regression fixture")
        literal.start("LiteralStart", "Input received", 150, 62)
        literal.script("LiteralEncode", "Encode input", 230, 40, json_string_expression("=text"), "encoded")
        literal.end("LiteralEnd", "Input encoded", 390, 62)
        literal.flow("LiteralStart", "LiteralEncode")
        literal.flow("LiteralEncode", "LiteralEnd")
        output[ROOT / "tests/src/test/resources/bpmn/a2a-literal-prompt.bpmn"] = serialize(ET.fromstring(literal.xml()))
        controlled = Proc("a2a-controlled-business", "Nonshipping cancellation-order regression fixture")
        controlled.msg("ControlledFollowUpMessage", "a2a-send", "=task.id")
        controlled.start("ControlledStart", "Task received", 150, 62)
        controlled.xor("ControlledRoute", "Ask for input?", 230, 55)
        controlled.node("userTask", "ControlledWork", "Complete controlled business work", 340, 40,
                        ext="<zeebe:userTask />")
        original.update_call(controlled, "ControlledUpdate", "Commit completion", 520, 40,
                             '{state: "TASK_STATE_COMPLETED", text: "Controlled completion", artifacts: '
                             '[{artifactId: "controlled", parts: [{text: "Controlled artifact"}]}]}')
        original.update_call(controlled, "ControlledAsk", "Request client input", 340, 240,
                             '{state: "TASK_STATE_INPUT_REQUIRED", text: "Controlled clarification"}')
        controlled.catch_msg("ControlledFollowUp", "Follow-up received", 520, 262,
                             "ControlledFollowUpMessage", ext=original.follow_up_mapping())
        controlled.end("ControlledEnd", "Completed", 700, 62)
        controlled.flow("ControlledStart", "ControlledRoute")
        controlled.flow("ControlledRoute", "ControlledAsk", "yes",
                        cond='=req.message.parts[1].text = "input-required"', route="down-out")
        controlled.flow("ControlledRoute", "ControlledWork", "no", default=True)
        controlled.flow("ControlledAsk", "ControlledFollowUp")
        controlled.flow("ControlledFollowUp", "ControlledWork", route="over:175")
        controlled.flow("ControlledWork", "ControlledUpdate")
        controlled.flow("ControlledUpdate", "ControlledEnd")
        output[ROOT / "tests/src/test/resources/bpmn/a2a-controlled-business.bpmn"] = serialize(
            add_hook(ET.fromstring(controlled.xml())))
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
