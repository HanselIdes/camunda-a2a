"""Required stock-BPMN cancellation hook for an adapted A2A business process."""
import xml.etree.ElementTree as ET

from .feel import TERMINAL, TS

B = "http://www.omg.org/spec/BPMN/20100524/MODEL"
Z = "http://camunda.org/schema/zeebe/1.0"
D = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"


def add_hook(root):
    process, = root.findall(f"{{{B}}}process")
    previous = next((element for element in process if element.get("id") == "A2ACancellation"), None)
    if previous is not None:
        identifiers = {element.get("id") for element in previous.iter() if element.get("id")} | {"A2ACancelMessage"}
        process.remove(previous)
        for parent in root.iter():
            for element in list(parent):
                if element.get("id") == "A2ACancelMessage" or element.get("bpmnElement") in identifiers:
                    parent.remove(element)
    message = ET.Element(f"{{{B}}}message", id="A2ACancelMessage", name="a2a-cancel")
    subscription = ET.SubElement(message, f"{{{B}}}extensionElements")
    ET.SubElement(subscription, f"{{{Z}}}subscription", correlationKey="=task.id")
    root.insert(list(root).index(process), message)
    hook = ET.SubElement(process, f"{{{B}}}subProcess", id="A2ACancellation",
                         name="Cancel this A2A task", triggeredByEvent="true")
    start = ET.SubElement(hook, f"{{{B}}}startEvent", id="A2ACancelRequested",
                          name="Cancellation requested", isInterrupting="true")
    ET.SubElement(start, f"{{{B}}}outgoing").text = "A2ACancelToState"
    ET.SubElement(start, f"{{{B}}}messageEventDefinition", id="A2ACancelRequested_def",
                  messageRef="A2ACancelMessage")
    script = ET.SubElement(hook, f"{{{B}}}scriptTask", id="A2ASetCanceled", name="Commit terminal outcome")
    extensions = ET.SubElement(script, f"{{{B}}}extensionElements")
    ET.SubElement(extensions, f"{{{Z}}}script", resultVariable="task", expression=(
        f"=if list contains({TERMINAL}, task.status.state) then task else "
        'context merge([task, {rev: task.rev + 1, artifacts: [], '
        f'status: {{state: "TASK_STATE_CANCELED", timestamp: {TS}}}}}])'))
    ET.SubElement(script, f"{{{B}}}incoming").text = "A2ACancelToState"
    ET.SubElement(script, f"{{{B}}}outgoing").text = "A2ACancelToEnd"
    end = ET.SubElement(hook, f"{{{B}}}endEvent", id="A2ACancelDone", name="Cancellation settled")
    ET.SubElement(end, f"{{{B}}}incoming").text = "A2ACancelToEnd"
    for identifier, source, target in (
            ("A2ACancelToState", "A2ACancelRequested", "A2ASetCanceled"),
            ("A2ACancelToEnd", "A2ASetCanceled", "A2ACancelDone")):
        ET.SubElement(hook, f"{{{B}}}sequenceFlow", id=identifier, sourceRef=source, targetRef=target)
    plane = root.find(f"{{{D}}}BPMNDiagram/{{{D}}}BPMNPlane")
    bounds = [shape.find(f"{{{DC}}}Bounds") for shape in plane.findall(f"{{{D}}}BPMNShape")]
    y = max(float(bound.get("y")) + float(bound.get("height")) for bound in bounds) + 80
    for identifier, x, offset, width, height in (
            ("A2ACancellation", 150, 0, 420, 160),
            ("A2ACancelRequested", 180, 62, 36, 36),
            ("A2ASetCanceled", 270, 40, 100, 80),
            ("A2ACancelDone", 450, 62, 36, 36)):
        shape = ET.SubElement(plane, f"{{{D}}}BPMNShape", id=identifier + "_di", bpmnElement=identifier)
        if identifier == "A2ACancellation":
            shape.set("isExpanded", "true")
        ET.SubElement(shape, f"{{{DC}}}Bounds", x=str(x), y=str(y + offset),
                      width=str(width), height=str(height))
    for identifier, left, right in (("A2ACancelToState", 216, 270), ("A2ACancelToEnd", 370, 450)):
        edge = ET.SubElement(plane, f"{{{D}}}BPMNEdge", id=identifier + "_di", bpmnElement=identifier)
        ET.SubElement(edge, f"{{{DI}}}waypoint", x=str(left), y=str(y + 80))
        ET.SubElement(edge, f"{{{DI}}}waypoint", x=str(right), y=str(y + 80))
    return root
