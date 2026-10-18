#!/usr/bin/env python3
"""One-off: cuts the client half out of experiment 2's single diagram (bpmn/a2a-two-agents.bpmn).

Run once from experiment-3 with the experiment-2 file as argument. The result, bpmn/a2a-client.bpmn, is edited by hand
from then on, like any diagram drawn in Modeler.
"""
import sys
from lxml import etree

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
Z = "http://camunda.org/schema/zeebe/1.0"
n = lambda ns, t: "{%s}%s" % (ns, t)  # noqa: E731

tree = etree.parse(sys.argv[1])
root = tree.getroot()
collab = root.find(n(B, "collaboration"))
proc = root.find(n(B, "process"))

drop_ids = set()


def collect(el):
    for e in el.iter():
        if e.get("id"):
            drop_ids.add(e.get("id"))


# server lane, its two event sub-processes and the server notes
proc.remove(proc.find(n(B, "laneSet")))
for sid in ("Activity_1mwggyd", "Activity_0u82j95"):
    el = proc.find("./*[@id='%s']" % sid)
    collect(el)
    proc.remove(el)
for nid in ("Note_CardRequested", "Note_MessageReceived", "Note_FollowUp"):
    el = proc.find("./*[@id='%s']" % nid)
    collect(el)
    proc.remove(el)
for aid in ("Assoc_CardRequested", "Assoc_MessageReceived", "Assoc_FollowUp"):
    el = proc.find("./*[@id='%s']" % aid)
    collect(el)
    proc.remove(el)
for el in list(collab):
    if el.get("id") in ("Note_Push", "Assoc_Push"):
        collect(el)
        collab.remove(el)
# server messages
for m in root.findall(n(B, "message")):
    if m.get("id") in ("Message_1exsyfd", "Message_18a84rx", "Message_0iqkhta"):
        root.remove(m)

# rename the process and describe the new client
proc.set("id", "a2a-client")
proc.set("name", "A2A client agent")
part = collab.find(n(B, "participant"))
part.set("name", "A2A client agent")
part.set("processRef", "a2a-client")
part.set("id", "Participant_Client")
collab.find(n(B, "documentation")).text = (
    "A client agent that delegates work to a remote A2A 1.0 agent. It reads the remote agent's card, sends it tasks "
    "with the A2A 1.0 Client element template and receives the answers as push notifications through the A2A 1.0 "
    "Client Webhook. The server is a separate diagram, a2a-server.bpmn.")

# diagram: drop every shape and edge of removed elements
plane = root.find(".//" + n(DI, "BPMNPlane"))
plane.set("bpmnElement", collab.get("id"))
for e in list(plane):
    ref = e.get("bpmnElement")
    if ref in drop_ids or ref in ("Lane_Server", "Lane_Client", "Participant_Agents"):
        plane.remove(e)
tree.write(sys.argv[2], xml_declaration=True, encoding="UTF-8")
