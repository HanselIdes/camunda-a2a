#!/usr/bin/env python3
"""Writes the one-purpose harness processes for the server templates into src/test/resources/harness.

Each harness holds the element under test, with its template applied by c8ctl, so the integration tests exercise exactly
the template output. Run from experiment-3/tests:  python3 scripts/gen_harness.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "src", "test", "resources", "harness")
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" '
        'xmlns:modeler="http://camunda.org/schema/modeler/1.0" id="Definitions_%(id)s" '
        'targetNamespace="http://bpmn.io/schema/bpmn" modeler:executionPlatform="Camunda Cloud" '
        'modeler:executionPlatformVersion="8.10.0">\n%(defs)s  <bpmn:process id="%(id)s" isExecutable="true">\n')


def shape(i, x, y, w=36, h=36):
    return ('    <bpmndi:BPMNShape id="%s_di" bpmnElement="%s"><dc:Bounds x="%d" y="%d" width="%d" height="%d" />'
            '</bpmndi:BPMNShape>\n' % (i, i, x, y, w, h))


def edge(i, *points):
    pts = "".join('<di:waypoint x="%d" y="%d" />' % p for p in points)
    return '    <bpmndi:BPMNEdge id="%s_di" bpmnElement="%s">%s</bpmndi:BPMNEdge>\n' % (i, i, pts)


def write(pid, defs, body, di, applies):
    xml = HEAD % {"id": pid, "defs": defs} + body + (
        '  </bpmn:process>\n  <bpmndi:BPMNDiagram id="D"><bpmndi:BPMNPlane id="P" bpmnElement="%s">\n%s'
        '  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>\n</bpmn:definitions>\n' % (pid, di))
    path = os.path.join(OUT, pid + ".bpmn")
    open(path, "w").write(xml)
    for template, element, sets in applies:
        cmd = ["c8ctl", "element-template", "apply", "-i", template, element, path]
        for k, v in sets:
            cmd += ["--set", "%s=%s" % (k, v)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            sys.exit("apply failed for %s/%s" % (pid, element))
    print("wrote", path)


# The Agent Card start event: every GET starts a run that ends right away.
write("h-card", "",
      '    <bpmn:startEvent id="Card" name="Card requested"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent>\n'
      '    <bpmn:endEvent id="End" name="Card served"><bpmn:incoming>F1</bpmn:incoming></bpmn:endEvent>\n'
      '    <bpmn:sequenceFlow id="F1" sourceRef="Card" targetRef="End" />\n',
      shape("Card", 150, 100) + shape("End", 300, 100) + edge("F1", (186, 118), (300, 118)),
      [("dev.hansel.a2a.server.card.v1", "Card", [("inbound.context", "h-card")])])

# The JSON-RPC start event: the run answers by setting rpcResponse, which the webhook returns as the HTTP body.
write("h-rpc", "",
      '    <bpmn:startEvent id="Rpc" name="Request received"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent>\n'
      '    <bpmn:scriptTask id="Echo" name="Echo the request"><bpmn:extensionElements><zeebe:script expression="={jsonrpc: &#34;2.0&#34;, '
      'id: rpc.id, result: {method: rpc.method, version: hdr.`a2a-version`, contentType: hdr.`content-type`}}" '
      'resultVariable="rpcResponse" /></bpmn:extensionElements><bpmn:incoming>F1</bpmn:incoming>'
      '<bpmn:outgoing>F2</bpmn:outgoing></bpmn:scriptTask>\n'
      '    <bpmn:endEvent id="End" name="Answered"><bpmn:incoming>F2</bpmn:incoming></bpmn:endEvent>\n'
      '    <bpmn:sequenceFlow id="F1" sourceRef="Rpc" targetRef="Echo" />\n'
      '    <bpmn:sequenceFlow id="F2" sourceRef="Echo" targetRef="End" />\n',
      shape("Rpc", 150, 100) + shape("Echo", 250, 78, 100, 80) + shape("End", 420, 100)
      + edge("F1", (186, 118), (250, 118)) + edge("F2", (350, 118), (420, 118)),
      [("dev.hansel.a2a.server.rpc.v1", "Rpc", [("inbound.context", "h-rpc")])])

# The push service task with its error boundary, like the delivery process of the server diagram.
write("h-push", '  <bpmn:error id="PushFailed" name="PushFailed" errorCode="PUSH_FAILED" />\n',
      '    <bpmn:startEvent id="Start" name="Started"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent>\n'
      '    <bpmn:serviceTask id="Push" name="Push task update"><bpmn:incoming>F1</bpmn:incoming>'
      '<bpmn:outgoing>F2</bpmn:outgoing></bpmn:serviceTask>\n'
      '    <bpmn:boundaryEvent id="Failed" name="Delivery failed" attachedToRef="Push"><bpmn:outgoing>F3</bpmn:outgoing>'
      '<bpmn:errorEventDefinition id="Failed_def" errorRef="PushFailed" /></bpmn:boundaryEvent>\n'
      '    <bpmn:endEvent id="End" name="Delivered"><bpmn:incoming>F2</bpmn:incoming></bpmn:endEvent>\n'
      '    <bpmn:endEvent id="GaveUp" name="Gave up"><bpmn:incoming>F3</bpmn:incoming></bpmn:endEvent>\n'
      '    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="Push" />\n'
      '    <bpmn:sequenceFlow id="F2" sourceRef="Push" targetRef="End" />\n'
      '    <bpmn:sequenceFlow id="F3" sourceRef="Failed" targetRef="GaveUp" />\n',
      shape("Start", 150, 100) + shape("Push", 250, 78, 100, 80) + shape("End", 420, 100) + shape("Failed", 282, 140)
      + shape("GaveUp", 420, 200) + edge("F1", (186, 118), (250, 118)) + edge("F2", (350, 118), (420, 118))
      + edge("F3", (300, 176), (300, 218), (420, 218)),
      [("dev.hansel.a2a.server.push.v1", "Push", [("retries", "2"), ("retryBackoff", "PT1S")])])
