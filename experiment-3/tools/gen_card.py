#!/usr/bin/env python3
"""Derives the Agent Card from the agent's tools so that the card cannot drift from them.

Each direct child of the AI Agent ad-hoc sub-process in bpmn/a2a-agent.bpmn is a tool, and each tool
becomes one skill: id (element id, which is the tool name the model sees), name, description
(<bpmn:documentation>), tags and examples (zeebe:property a2a:tags, a2a:examples).

  python3 tools/gen_card.py --print   print the response expression of the Agent Card start event
  python3 tools/gen_card.py --check   exit 1 when the committed expression differs from the generated card
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NS = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL", "z": "http://camunda.org/schema/zeebe/1.0"}
SERVER = os.path.join(ROOT, "bpmn", "a2a-agent.bpmn")
TASK = CARD = SERVER


def feel_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def json_string_expression(expression):
    """Keep literal prompts intact when the stock connector binds an @FEEL String."""
    escaped = expression.removeprefix("=")
    for pattern, replacement in ((r"\\", r"\\\\"), ('"', r'\\"')):
        escaped = f"replace({escaped}, {feel_str(pattern)}, {feel_str(replacement)})"
    for code in range(32):
        pattern, replacement = rf"\u{code:04x}", rf"\\u{code:04x}"
        escaped = f"replace({escaped}, {feel_str(pattern)}, {feel_str(replacement)})"
    return f"={feel_str(chr(34))} + {escaped} + {feel_str(chr(34))}"


def feel_list(items):
    return "[%s]" % ", ".join(feel_str(i) for i in items)


def skills_from_bpmn(path=TASK):
    root = ET.parse(path).getroot()
    host = None
    for el in root.iter("{%s}adHocSubProcess" % NS["b"]):
        host = el
        break
    if host is None:
        raise SystemExit("no ad-hoc sub-process in " + path)
    skills = []
    for child in host:
        if not child.tag.startswith("{%s}" % NS["b"]):
            continue
        tag = child.tag.split("}")[1]
        if tag in ("incoming", "outgoing", "documentation", "extensionElements", "multiInstanceLoopCharacteristics"):
            continue
        if tag not in ("scriptTask", "serviceTask", "businessRuleTask", "userTask", "callActivity", "subProcess", "task"):
            continue
        doc = child.find("b:documentation", NS)
        props = {p.get("name"): p.get("value")
                 for p in child.findall("b:extensionElements/z:properties/z:property", NS)}
        skills.append({
            "id": child.get("id"), "name": child.get("name") or child.get("id"),
            "description": (doc.text or "").strip() if doc is not None else "",
            "tags": [t for t in props.get("a2a:tags", "").split(",") if t],
            "examples": [e for e in props.get("a2a:examples", "").split("|") if e],
        })
    if not skills:
        raise SystemExit("the agent has no tools")
    return skills


def skills_feel(skills):
    items = []
    for s in skills:
        entries = ["id: %s" % feel_str(s["id"]), "name: %s" % feel_str(s["name"]),
                   "description: %s" % feel_str(s["description"]), "tags: %s" % feel_list(s["tags"])]
        if s["examples"]:
            entries.append("examples: %s" % feel_list(s["examples"]))
        items.append("{%s}" % ", ".join(entries))
    return "[%s]" % ", ".join(items)


def card_context(skills):
    """The card without the parts the server adds: name, description, version, provider and the skills."""
    return re.sub(r"\s+", " ", """{name: "Task agent",
      description: "Answers questions with its tools and asks for clarification when a request is ambiguous.",
      version: "1.0.0", provider: {organization: "camunda-a2a", url: "https://github.com/HanselIdes/camunda-a2a"},
      skills: %s}""" % skills_feel(skills)).strip()


def card_response(skills):
    """The response expression of the A2A 1.0 Server: Agent Card start event: the card plus the JSON-RPC endpoint
    and the capabilities, which come from the secrets A2A_PUBLIC_URL and A2A_PUSH_ENABLED."""
    return re.sub(r"\s+", " ", """={card: %s,
      response: {statusCode: 200,
        headers: {"Content-Type": "application/json", "Cache-Control": "public, max-age=300", "ETag": %s,
                  "Last-Modified": "%s"},
        body: context merge([card, {
          supportedInterfaces: [{url: "{{secrets.A2A_PUBLIC_URL}}/a2a", protocolBinding: "JSONRPC", protocolVersion: "1.0"}],
          capabilities: {streaming: false, pushNotifications: "{{secrets.A2A_PUSH_ENABLED}}" = "true",
                         extendedAgentCard: false},
          defaultInputModes: ["text/plain", "application/json"],
          defaultOutputModes: ["text/plain", "application/json"]}])}}.response"""
                  % (card_context(skills), feel_str('"%s"' % card_etag(skills)), CARD_LAST_MODIFIED)).strip()


CARD_LAST_MODIFIED = "Thu, 15 Oct 2026 12:00:00 GMT"


def card_etag(skills):
    """Strong validator that changes whenever the generated card changes."""
    import hashlib
    return hashlib.sha256(card_context(skills).encode()).hexdigest()[:16]


def committed_expression():
    root = ET.parse(CARD).getroot()
    for el in root.iter("{%s}property" % NS["z"]):
        if el.get("name") == "inbound.responseExpression" and "card:" in (el.get("value") or ""):
            return el.get("value")
    raise SystemExit("no card response expression in " + CARD)


def main(argv):
    expected = card_response(skills_from_bpmn())
    if "--print" in argv:
        print(expected)
        return 0
    if "--check" in argv:
        actual = committed_expression()
        if actual != expected:
            print("the Agent Card start event differs from the card generated from the agent tools; run tools/bpmn_gen/build.py")
            return 1
        print("card matches the %d agent tools" % len(skills_from_bpmn()))
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
