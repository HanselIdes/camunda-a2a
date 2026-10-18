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
    def start(self, id, name, x=0, y=0, **kw):
        return self.node("startEvent", id, name, x, y, **kw)

    def end(self, id, name, x=0, y=0, **kw):
        return self.node("endEvent", id, name, x, y, **kw)

    def script(self, id, name, x, y, expr, result, **kw):
        ext = ("<zeebe:script expression=%s resultVariable=%s />" % (q(expr), q(result)))
        return self.node("scriptTask", id, name, x, y, ext=ext, **kw)

    def xor(self, id, name, x=0, y=0, **kw):
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

    def auto(self, rows, x0=150, dx=150, y0=40, dy=130, cols=None):
        """Places every top-level node on a grid: the column is the longest path from a start event (flows routed
        back or over are loops and do not count), the row comes from `rows` (default 0). Boundary events sit on the
        bottom edge of their host. Used for the protocol pools, which nobody models by hand."""
        cols = dict(cols or {})
        loop = lambda f: f.route is not None and (f.route.startswith("back") or f.route.startswith("over"))  # noqa: E731
        hosts = {n.id: n.attrs.split('"')[1] for n in self.nodes.values() if n.kind == "boundaryEvent"}
        rank = {nid: 0 for nid in self.nodes}
        for _ in range(len(self.nodes)):
            changed = False
            for f in self.flows:
                if loop(f):
                    continue
                src = hosts.get(f.src, f.src)
                if rank[f.tgt] < rank[src] + 1:
                    rank[f.tgt] = rank[src] + 1
                    changed = True
            if not changed:
                break
        rank.update(cols)
        for nid, n in self.nodes.items():
            if n.parent is not None or n.kind == "boundaryEvent":
                continue
            cx, top = x0 + rank[nid] * dx, y0 + rows.get(nid, 0) * dy
            if n.kind in ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent"):
                n.x, n.y = cx + 32, top + 22
            elif n.kind.endswith("Gateway"):
                n.x, n.y = cx + 25, top + 15
            else:
                n.x, n.y = cx, top
        for nid, host in hosts.items():
            h = self.nodes[host]
            self.nodes[nid].x, self.nodes[nid].y = h.x + h.w - 36, h.y + h.h - 18
        for f in self.flows:
            if f.route is None and self.nodes[f.src].kind.endswith("Gateway"):
                s, t = self.nodes[f.src], self.nodes[f.tgt]
                if t.y + t.h / 2 > s.y + s.h:
                    f.route = "down-in"
                elif t.y + t.h / 2 < s.y:
                    f.route = "up-in"

    def _shift(self, dx, dy):
        for n in self.nodes.values():
            n.x += dx
            n.y += dy

    def bbox(self):
        x0 = min(n.x for n in self.nodes.values())
        y0 = min(n.y for n in self.nodes.values())
        x1 = max(n.x + n.w for n in self.nodes.values())
        y1 = max(n.y + n.h for n in self.nodes.values())
        return x0, y0, x1, y1

    def parts(self):
        """The pieces of the XML: message and error definitions, the process element, shapes and edges."""
        messages = []
        for mid, (name, key) in self.messages.items():
            sub = ""
            if key:
                sub = "<bpmn:extensionElements><zeebe:subscription correlationKey=%s /></bpmn:extensionElements>" % q(key)
            messages.append('  <bpmn:message id=%s name=%s>%s</bpmn:message>' % (q(mid), q(name), sub))
        errs = sorted({n.inner.split('errorRef="')[1].split('"')[0] for n in self.nodes.values()
                       if 'errorRef="' in n.inner})
        errors = []
        for e in errs:
            code = self.error_codes.get(e, e) if hasattr(self, "error_codes") else e
            errors.append('  <bpmn:error id=%s name=%s errorCode=%s />' % (q(e), q(e), q(code)))
        process = ['  <bpmn:process id=%s name=%s isExecutable="true">' % (q(self.pid), q(self.name))]
        for nid in self.order:
            n = self.nodes[nid]
            if n.parent is None:
                process.append(self._node_xml(n, 2))
        for f in self.flows:
            if self.nodes[f.src].parent is None:
                process.append(self._flow_xml(f, 2))
        process.append("  </bpmn:process>")
        shapes, edges = [], []
        for nid in self.order:
            n = self.nodes[nid]
            extra = ""
            if n.kind in ("subProcess", "adHocSubProcess"):
                extra = ' isExpanded="true"'
            shapes.append('      <bpmndi:BPMNShape id=%s bpmnElement=%s%s>' % (q(nid + "_di"), q(nid), extra))
            shapes.append('        <dc:Bounds x="%d" y="%d" width="%d" height="%d" />' % (n.x, n.y, n.w, n.h))
            shapes.append('      </bpmndi:BPMNShape>')
        for f in self.flows:
            edges.append('      <bpmndi:BPMNEdge id=%s bpmnElement=%s>' % (q(f.id + "_di"), q(f.id)))
            for (x, y) in self._waypoints(f):
                edges.append('        <di:waypoint x="%d" y="%d" />' % (x, y))
            edges.append('      </bpmndi:BPMNEdge>')
        return {"messages": messages, "errors": errors, "process": process, "shapes": shapes, "edges": edges}

    def xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<bpmn:definitions %s id="Definitions_%s" targetNamespace="http://bpmn.io/schema/bpmn" '
               'modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.10.0">'
               % (NS, self.pid.replace("-", "_"))]
        pt = self.parts()
        out += pt["messages"] + pt["errors"] + pt["process"]
        out.append('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">')
        out.append('    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement=%s>' % q(self.pid))
        out += pt["shapes"] + pt["edges"]
        out.append("    </bpmndi:BPMNPlane>")
        out.append("  </bpmndi:BPMNDiagram>")
        out.append("</bpmn:definitions>")
        return "\n".join(out) + "\n"


class Collab:
    """Several executable processes in one diagram: one pool per process, stacked top to bottom."""

    def __init__(self, cid, name, doc=""):
        self.cid, self.name, self.doc = cid, name, doc
        self.pools = []

    def add(self, proc, label, note=""):
        self.pools.append((proc, label, note))

    def xml(self):
        seen = {}
        for proc, _, _ in self.pools:
            for nid in list(proc.nodes) + [f.id for f in proc.flows]:
                if nid in seen:
                    raise SystemExit("id %s is used by %s and %s" % (nid, seen[nid], proc.pid))
                seen[nid] = proc.pid
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<bpmn:definitions %s id="Definitions_%s" targetNamespace="http://bpmn.io/schema/bpmn" '
               'modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.10.0">'
               % (NS, self.cid.replace("-", "_")),
               '  <bpmn:collaboration id=%s>' % q(self.cid)]
        if self.doc:
            out.append("    <bpmn:documentation>%s</bpmn:documentation>" % esc(self.doc))
        for proc, label, _ in self.pools:
            out.append('    <bpmn:participant id=%s name=%s processRef=%s />'
                       % (q("Pool_" + proc.pid), q(label), q(proc.pid)))
        out.append("  </bpmn:collaboration>")
        messages, errors, procs, shapes, edges = [], [], [], [], []
        top = 40
        for proc, label, _ in self.pools:
            x0, y0, x1, y1 = proc.bbox()
            pool_x, pool_y = 60, top
            dy = pool_y + 40 - y0
            proc._shift(0, dy)
            pt = proc.parts()
            proc._shift(0, -dy)
            messages += [m for m in pt["messages"] if m not in messages]
            errors += [e for e in pt["errors"] if e not in errors]
            procs += pt["process"]
            width = int(x1 + 80 - pool_x)
            height = int(y1 - y0 + 80)
            shapes.append('      <bpmndi:BPMNShape id=%s bpmnElement=%s isHorizontal="true">'
                          % (q("Pool_" + proc.pid + "_di"), q("Pool_" + proc.pid)))
            shapes.append('        <dc:Bounds x="%d" y="%d" width="%d" height="%d" />' % (pool_x, pool_y, width, height))
            shapes.append('      </bpmndi:BPMNShape>')
            shapes += pt["shapes"]
            edges += pt["edges"]
            top += height + 40
        out += messages + errors + procs
        out.append('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">')
        out.append('    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement=%s>' % q(self.cid))
        out += shapes + edges
        out.append("    </bpmndi:BPMNPlane>")
        out.append("  </bpmndi:BPMNDiagram>")
        out.append("</bpmn:definitions>")
        return "\n".join(out) + "\n"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
