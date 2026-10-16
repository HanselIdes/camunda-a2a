"""Minimal DMN decision-table writer."""
from xml.sax.saxutils import quoteattr as q, escape


def table(decision_id, name, inputs, outputs, rules, hit="FIRST", x=150, y=100):
    """inputs: [(label, expression, typeRef)], outputs: [(name, label, typeRef)],
    rules: [(description, [input entries], [output entries])]"""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" '
           'xmlns:dmndi="https://www.omg.org/spec/DMN/20191111/DMNDI/" '
           'xmlns:dc="http://www.omg.org/spec/DMN/20180521/DC/" '
           'xmlns:modeler="http://camunda.org/schema/modeler/1.0" '
           'id=%s name=%s namespace="http://camunda.org/schema/1.0/dmn" '
           'modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.10.0">'
           % (q("Definitions_" + decision_id.replace("-", "_")), q(name)),
           '  <decision id=%s name=%s>' % (q(decision_id), q(name)),
           '    <decisionTable id=%s hitPolicy=%s>' % (q(decision_id + "_table"), q(hit))]
    for i, (label, expr, typ) in enumerate(inputs):
        out.append('      <input id=%s label=%s>' % (q("In_%d" % i), q(label)))
        out.append('        <inputExpression id=%s typeRef=%s><text>%s</text></inputExpression>'
                   % (q("InExpr_%d" % i), q(typ), escape(expr)))
        out.append('      </input>')
    for i, (oname, label, typ) in enumerate(outputs):
        out.append('      <output id=%s label=%s name=%s typeRef=%s />'
                   % (q("Out_%d" % i), q(label), q(oname), q(typ)))
    for r, (desc, ins, outs) in enumerate(rules):
        out.append('      <rule id=%s>' % q("Rule_%d" % (r + 1)))
        if desc:
            out.append('        <description>%s</description>' % escape(desc))
        for i, e in enumerate(ins):
            out.append('        <inputEntry id=%s><text>%s</text></inputEntry>'
                       % (q("Rule_%d_in_%d" % (r + 1, i)), escape(e)))
        for i, e in enumerate(outs):
            out.append('        <outputEntry id=%s><text>%s</text></outputEntry>'
                       % (q("Rule_%d_out_%d" % (r + 1, i)), escape(e)))
        out.append('      </rule>')
    out.append('    </decisionTable>')
    out.append('  </decision>')
    out.append('  <dmndi:DMNDI>')
    out.append('    <dmndi:DMNDiagram id="DMNDiagram_1">')
    out.append('      <dmndi:DMNShape id=%s dmnElementRef=%s>' % (q(decision_id + "_di"), q(decision_id)))
    out.append('        <dc:Bounds height="80" width="180" x="%d" y="%d" />' % (x, y))
    out.append('      </dmndi:DMNShape>')
    out.append('    </dmndi:DMNDiagram>')
    out.append('  </dmndi:DMNDI>')
    out.append('</definitions>')
    return "\n".join(out) + "\n"
