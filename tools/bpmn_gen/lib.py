"""Tiny BPMN builder: declare elements with coordinates, get XML with diagram interchange.

Only what camunda-a2a needs: tasks, events, gateways, embedded and event sub-processes,
boundary events, message definitions. Connector templates are applied afterwards with
`c8ctl element-template apply` (see build.py).
"""
from xml.sax.saxutils import quoteattr

SIZES = {
    "startEvent": (36, 36), "endEvent": (36, 36), "intermediateCatchEvent": (36, 36),
    "intermediateThrowEvent": (36, 36), "boundaryEvent": (36, 36),
    "exclusiveGateway": (50, 50), "eventBasedGateway": (50, 50), "parallelGateway": (50, 50),
    "task": (100, 80), "scriptTask": (100, 80), "serviceTask": (100, 80),
    "businessRuleTask": (100, 80), "callActivity": (100, 80), "userTask": (100, 80),
}
NS = ('xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
      'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
      'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
      'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
      'xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" '
      'xmlns:modeler="http://camunda.org/schema/modeler/1.0" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')


def q(s):
    return quoteattr(s)


class Node:
    def __init__(self, kind, id, name, x, y, w, h, parent, ext, attrs, inner, doc=""):
        self.doc = doc
        self.kind, self.id, self.name = kind, id, name
        self.x, self.y, self.w, self.h = x, y, w, h
        self.parent, self.ext, self.attrs, self.inner = parent, ext, attrs, inner
        self.incoming, self.outgoing = [], []


class Flow:
    def __init__(self, id, src, tgt, name, cond, default, route):
        self.id, self.src, self.tgt, self.name = id, src, tgt, name
        self.cond, self.default, self.route = cond, default, route


class Proc:
    def __init__(self, pid, name):
        self.pid, self.name = pid, name
        self.nodes, self.flows, self.messages = {}, [], {}
        self.order = []

    def msg(self, mid, name, key=None):
        self.messages[mid] = (name, key)
        return mid

    def node(self, kind, id, name="", x=0, y=0, w=None, h=None, parent=None,
             ext="", attrs="", inner="", doc=""):
        dw, dh = SIZES.get(kind, (100, 80))
        n = Node(kind, id, name, x, y, w or dw, h or dh, parent, ext, attrs, inner, doc)
        self.nodes[id] = n
        self.order.append(id)
        return id

    # convenience wrappers -------------------------------------------------
    def start(self, id, name, x, y, **kw):
        return self.node("startEvent", id, name, x, y, **kw)

    def end(self, id, name, x, y, **kw):
        return self.node("endEvent", id, name, x, y, **kw)

    def script(self, id, name, x, y, expr, result, **kw):
        ext = ("<zeebe:script expression=%s resultVariable=%s />" % (q(expr), q(result)))
        return self.node("scriptTask", id, name, x, y, ext=ext, **kw)

    def xor(self, id, name, x, y, **kw):
        return self.node("exclusiveGateway", id, name, x, y, **kw)

    def rule(self, id, name, x, y, decision, result, **kw):
        ext = "<zeebe:calledDecision decisionId=%s resultVariable=%s />" % (q(decision), q(result))
        return self.node("businessRuleTask", id, name, x, y, ext=ext, **kw)

    def call(self, id, name, x, y, process, inputs=(), outputs=(), **kw):
        io = "".join('<zeebe:input source=%s target=%s />' % (q(s), q(t)) for s, t in inputs)
        io += "".join('<zeebe:output source=%s target=%s />' % (q(s), q(t)) for s, t in outputs)
        ext = ("<zeebe:calledElement processId=%s propagateAllChildVariables=\"false\" "
               "propagateAllParentVariables=\"false\" />" % q(process))
        if io:
            ext += "<zeebe:ioMapping>%s</zeebe:ioMapping>" % io
        return self.node("callActivity", id, name, x, y, ext=ext, **kw)

    def msg_start(self, id, name, x, y, mid, interrupting, **kw):
        inner = '<bpmn:messageEventDefinition id=%s messageRef=%s />' % (q(id + "_def"), q(mid))
        return self.node("startEvent", id, name, x, y, inner=inner,
                         attrs="" if interrupting else 'isInterrupting="false"', **kw)

    def catch_msg(self, id, name, x, y, mid, **kw):
        inner = '<bpmn:messageEventDefinition id=%s messageRef=%s />' % (q(id + "_def"), q(mid))
        return self.node("intermediateCatchEvent", id, name, x, y, inner=inner, **kw)

    def catch_timer(self, id, name, x, y, duration_expr, **kw):
        inner = ('<bpmn:timerEventDefinition id=%s><bpmn:timeDuration xsi:type="bpmn:tFormalExpression">%s'
                 '</bpmn:timeDuration></bpmn:timerEventDefinition>' % (q(id + "_def"), esc(duration_expr)))
        return self.node("intermediateCatchEvent", id, name, x, y, inner=inner, **kw)

    def boundary_error(self, id, name, host, error_ref, x, y, **kw):
        inner = '<bpmn:errorEventDefinition id=%s errorRef=%s />' % (q(id + "_def"), q(error_ref))
        return self.node("boundaryEvent", id, name, x, y, attrs="attachedToRef=%s" % q(host),
                         inner=inner, **kw)

    def sub(self, id, name, x, y, w, h, kind="subProcess", **kw):
        return self.node(kind, id, name, x, y, w=w, h=h, **kw)

    def flow(self, src, tgt, name="", cond=None, default=False, route=None, id=None):
        fid = id or "Flow_%s_%s" % (src, tgt)
        f = Flow(fid, src, tgt, name, cond, default, route)
        self.flows.append(f)
        self.nodes[src].outgoing.append(fid)
        self.nodes[tgt].incoming.append(fid)
        return fid

    def remove_flow(self, src, tgt):
        for f in list(self.flows):
            if f.src == src and f.tgt == tgt:
                self.flows.remove(f)
                self.nodes[src].outgoing.remove(f.id)
                self.nodes[tgt].incoming.remove(f.id)

    # XML ------------------------------------------------------------------
    def _node_xml(self, n, ind):
        sp = "  " * ind
        a = " ".join(filter(None, [
            "id=%s" % q(n.id), ("name=%s" % q(n.name)) if n.name else "", n.attrs]))
        # default flow attribute for gateways
        for f in self.flows:
            if f.default and f.src == n.id:
                a += " default=%s" % q(f.id)
        out = [sp + "<bpmn:%s %s>" % (n.kind, a)]
        if n.doc:
            out.append(sp + "  <bpmn:documentation>%s</bpmn:documentation>" % esc(n.doc))
        if n.ext:
            out.append(sp + "  <bpmn:extensionElements>%s</bpmn:extensionElements>" % n.ext)
        for fid in n.incoming:
            out.append(sp + "  <bpmn:incoming>%s</bpmn:incoming>" % fid)
        for fid in n.outgoing:
            out.append(sp + "  <bpmn:outgoing>%s</bpmn:outgoing>" % fid)
        if n.inner:
            out.append(sp + "  " + n.inner)
        if n.kind in ("subProcess", "adHocSubProcess"):
            for cid in self.order:
                c = self.nodes[cid]
                if c.parent == n.id:
                    out.append(self._node_xml(c, ind + 1))
            for f in self.flows:
                if self.nodes[f.src].parent == n.id:
                    out.append(self._flow_xml(f, ind + 1))
        out.append(sp + "</bpmn:%s>" % n.kind)
        return "\n".join(out)

    def _flow_xml(self, f, ind):
        sp = "  " * ind
        a = "id=%s sourceRef=%s targetRef=%s" % (q(f.id), q(f.src), q(f.tgt))
        if f.name:
            a += " name=%s" % q(f.name)
        if f.cond is None:
            return sp + "<bpmn:sequenceFlow %s />" % a
        return (sp + "<bpmn:sequenceFlow %s>\n" % a + sp +
                '  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">%s</bpmn:conditionExpression>\n'
                % esc(f.cond) + sp + "</bpmn:sequenceFlow>")

    def _waypoints(self, f):
        s, t = self.nodes[f.src], self.nodes[f.tgt]
        sx, sy = s.x + s.w, s.y + s.h / 2
        tx, ty = t.x, t.y + t.h / 2
        r = f.route
        if r == "down-in":      # exit bottom, enter left of target
            return [(s.x + s.w / 2, s.y + s.h), (s.x + s.w / 2, ty), (tx, ty)]
        if r == "up-in":
            return [(s.x + s.w / 2, s.y), (s.x + s.w / 2, ty), (tx, ty)]
        if r and r.startswith("back"):   # loop back: below, optional depth after colon
            depth = int(r.split(":")[1]) if ":" in r else 60
            by = max(s.y + s.h, t.y + t.h) + depth
            return [(s.x + s.w / 2, s.y + s.h), (s.x + s.w / 2, by), (t.x + t.w / 2, by),
                    (t.x + t.w / 2, t.y + t.h)]
        if r and r.startswith("over"):   # loop forward over the top
            depth = int(r.split(":")[1]) if ":" in r else 60
            by = min(s.y, t.y) - depth
            return [(s.x + s.w / 2, s.y), (s.x + s.w / 2, by), (t.x + t.w / 2, by), (t.x + t.w / 2, t.y)]
        if r == "bottom-in":     # enter target from below (target is below-right)
            return [(sx, sy), (t.x + t.w / 2, sy), (t.x + t.w / 2, t.y)]
        if r == "to-bottom":
            return [(s.x + s.w / 2, s.y + s.h), (s.x + s.w / 2, ty), (tx, ty)]
        if s.kind == "boundaryEvent":
            sx, sy = s.x + s.w / 2, s.y + s.h
            return [(sx, sy), (sx, ty), (tx, ty)] if ty != sy else [(sx, sy), (tx, ty)]
        if abs(sy - ty) < 1:
            return [(sx, sy), (tx, ty)]
        mx = (sx + tx) / 2
        return [(sx, sy), (mx, sy), (mx, ty), (tx, ty)]

    def xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<bpmn:definitions %s id="Definitions_%s" targetNamespace="http://bpmn.io/schema/bpmn" '
               'modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.10.0">'
               % (NS, self.pid.replace("-", "_"))]
        for mid, (name, key) in self.messages.items():
            sub = ""
            if key:
                sub = "<bpmn:extensionElements><zeebe:subscription correlationKey=%s /></bpmn:extensionElements>" % q(key)
            out.append('  <bpmn:message id=%s name=%s>%s</bpmn:message>' % (q(mid), q(name), sub))
        errs = sorted({n.inner.split('errorRef="')[1].split('"')[0] for n in self.nodes.values()
                       if 'errorRef="' in n.inner})
        for e in errs:
            code = self.error_codes.get(e, e) if hasattr(self, "error_codes") else e
            out.append('  <bpmn:error id=%s name=%s errorCode=%s />' % (q(e), q(e), q(code)))
        out.append('  <bpmn:process id=%s name=%s isExecutable="true">' % (q(self.pid), q(self.name)))
        for nid in self.order:
            n = self.nodes[nid]
            if n.parent is None:
                out.append(self._node_xml(n, 2))
        for f in self.flows:
            if self.nodes[f.src].parent is None:
                out.append(self._flow_xml(f, 2))
        out.append("  </bpmn:process>")
        out.append('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">')
        out.append('    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement=%s>' % q(self.pid))
        for nid in self.order:
            n = self.nodes[nid]
            extra = ""
            if n.kind in ("subProcess", "adHocSubProcess"):
                extra = ' isExpanded="true"'
            out.append('      <bpmndi:BPMNShape id=%s bpmnElement=%s%s>' % (q(nid + "_di"), q(nid), extra))
            out.append('        <dc:Bounds x="%d" y="%d" width="%d" height="%d" />' % (n.x, n.y, n.w, n.h))
            out.append('      </bpmndi:BPMNShape>')
        for f in self.flows:
            out.append('      <bpmndi:BPMNEdge id=%s bpmnElement=%s>' % (q(f.id + "_di"), q(f.id)))
            for (x, y) in self._waypoints(f):
                out.append('        <di:waypoint x="%d" y="%d" />' % (x, y))
            out.append('      </bpmndi:BPMNEdge>')
        out.append("    </bpmndi:BPMNPlane>")
        out.append("  </bpmndi:BPMNDiagram>")
        out.append("</bpmn:definitions>")
        return "\n".join(out) + "\n"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
