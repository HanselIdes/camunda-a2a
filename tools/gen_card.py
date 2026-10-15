#!/usr/bin/env python3
"""Derives the Agent Card from the agent's tools so that the card cannot drift from them.

Each direct child of the AI Agent ad-hoc sub-process in bpmn/a2a-task.bpmn is a tool, and each tool
becomes one skill: id (element id, which is the tool name the model sees), name, description
(<bpmn:documentation>), tags and examples (zeebe:property a2a:tags, a2a:examples).

  python3 tools/gen_card.py --print   print the FEEL expression of the card
  python3 tools/gen_card.py --check   exit 1 when bpmn/a2a-card.bpmn differs from the generated card
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NS = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL", "z": "http://camunda.org/schema/zeebe/1.0"}
TASK = os.path.join(ROOT, "bpmn", "a2a-task.bpmn")
CARD = os.path.join(ROOT, "bpmn", "a2a-card.bpmn")


def feel_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


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


def card_expression(skills):
    """FEEL expression of the card without supportedInterfaces, which the webhook adds from the public URL."""
    return re.sub(r"\s+", " ", """={name: "camunda-a2a",
      description: "An A2A 1.0 agent implemented in BPMN with out-of-the-box Camunda connectors",
      version: "1.0.0", provider: {organization: "camunda-a2a", url: "https://github.com/HanselIdes/camunda-a2a"},
      capabilities: {streaming: false, pushNotifications: false, extendedAgentCard: false},
      defaultInputModes: ["text/plain", "application/json"], defaultOutputModes: ["text/plain", "application/json"],
      skills: %s}""" % skills_feel(skills)).strip()


CARD_LAST_MODIFIED = "Thu, 15 Oct 2026 12:00:00 GMT"


def card_etag(skills):
    """Strong validator that changes whenever the generated card changes."""
    import hashlib
    return '"%s"' % hashlib.sha256(card_expression(skills).encode()).hexdigest()[:16]


def committed_expression():
    root = ET.parse(CARD).getroot()
    for el in root.iter("{%s}script" % NS["z"]):
        if el.get("resultVariable") == "card":
            return el.get("expression")
    raise SystemExit("no card script in " + CARD)


def main(argv):
    expected = card_expression(skills_from_bpmn())
    if "--print" in argv:
        print(expected)
        return 0
    if "--check" in argv:
        actual = committed_expression()
        if actual != expected:
            print("bpmn/a2a-card.bpmn differs from the card generated from the agent tools; run tools/bpmn_gen/build.py")
            return 1
        print("card matches the %d agent tools" % len(skills_from_bpmn()))
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
